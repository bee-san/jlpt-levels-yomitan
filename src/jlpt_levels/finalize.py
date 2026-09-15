from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .contracts import errors
from .identity import canonical_json_bytes

LEVELS = ("N5", "N4", "N3", "N2", "N1", "N0")
METHODS = ("direct", "inferred", "adjudicated")
PRECEDENCE = {method: index for index, method in enumerate(METHODS)}
POLICY = {"name": "complete-classification-merge", "version": "1.0.0"}


class FinalizationError(ValueError):
    pass


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise FinalizationError(f"{path}:{number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise FinalizationError(f"{path}:{number}: row must be an object")
            rows.append(row)
    return rows


def _index(rows: Iterable[dict], kind: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        identity = row.get("lexemeId")
        if not isinstance(identity, str) or not identity:
            raise FinalizationError(f"{kind} row lacks lexemeId")
        if identity in result:
            raise FinalizationError(f"duplicate {kind} lexemeId: {identity}")
        result[identity] = row
    return result


def _validate_classifications(rows: Iterable[dict], expected_method: str) -> None:
    for row in rows:
        if row.get("method") != expected_method:
            raise FinalizationError(
                f"{expected_method} input contains method {row.get('method')!r} for {row.get('lexemeId')!r}"
            )
        found = errors("classification.schema.json", row)
        if found:
            raise FinalizationError(f"invalid {expected_method} classification {row.get('lexemeId')}: {found[0]}")


def _confidence_report(rows: list[dict]) -> dict:
    by_method: dict[str, list[float]] = defaultdict(list)
    buckets: Counter[str] = Counter()
    for row in rows:
        value = float(row["confidence"])
        by_method[row["method"]].append(value)
        if value < 0.5:
            buckets["0.00-0.49"] += 1
        elif value < 0.75:
            buckets["0.50-0.74"] += 1
        elif value < 0.9:
            buckets["0.75-0.89"] += 1
        else:
            buckets["0.90-1.00"] += 1
    return {
        "schemaVersion": 1,
        "buckets": {key: buckets[key] for key in ("0.00-0.49", "0.50-0.74", "0.75-0.89", "0.90-1.00")},
        "byMethod": {
            method: {
                "count": len(values),
                "minimum": min(values) if values else None,
                "maximum": max(values) if values else None,
                "mean": round(sum(values) / len(values), 6) if values else None,
            }
            for method in METHODS
            for values in [by_method[method]]
        },
    }


def _change_report(
    rows: list[dict], baseline: Iterable[dict] | None, explanations: dict[str, str] | None
) -> dict:
    current = _index(rows, "current classification")
    previous = _index(baseline or [], "baseline classification")
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    changed = []
    for identity in sorted(set(current) & set(previous)):
        before, after = previous[identity], current[identity]
        if (before.get("level"), before.get("method")) != (after.get("level"), after.get("method")):
            changed.append({
                "lexemeId": identity,
                "from": {"level": before.get("level"), "method": before.get("method")},
                "to": {"level": after.get("level"), "method": after.get("method")},
            })
    explanations = explanations or {}
    affected = set(added) | set(removed) | {item["lexemeId"] for item in changed}
    invalid_explanations = sorted(
        identity for identity, reason in explanations.items()
        if identity not in affected or not isinstance(reason, str) or not reason.strip()
    )
    if invalid_explanations:
        raise FinalizationError(f"invalid or stale change explanation: {invalid_explanations[0]}")
    unexplained = sorted(affected - set(explanations))
    if baseline is not None and unexplained:
        raise FinalizationError(f"unexplained classification changes: {len(unexplained)}; first={unexplained[0]}")
    return {
        "schemaVersion": 1,
        "baselineProvided": baseline is not None,
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed), "unchanged": len(current) - len(added) - len(changed)},
        "addedLexemeIds": added,
        "removedLexemeIds": removed,
        "changed": changed,
        "explanations": {identity: explanations[identity] for identity in sorted(explanations)},
        "unexplainedLexemeIds": unexplained,
    }


def finalize_records(
    lexemes: Iterable[dict],
    direct: Iterable[dict],
    inferred: Iterable[dict],
    adjudicated: Iterable[dict],
    direct_audit: dict,
    *,
    baseline: Iterable[dict] | None = None,
    change_explanations: dict[str, str] | None = None,
) -> tuple[list[dict], dict[str, dict]]:
    census = _index(lexemes, "census")
    inputs = {
        "direct": list(direct),
        "inferred": list(inferred),
        "adjudicated": list(adjudicated),
    }
    for method in METHODS:
        _validate_classifications(inputs[method], method)
    indexed = {method: _index(inputs[method], method) for method in METHODS}
    for method, records in indexed.items():
        extras = sorted(set(records) - set(census))
        if extras:
            raise FinalizationError(f"{method} classifications contain non-census lexemeId: {extras[0]}")

    direct_conflicts = direct_audit.get("unresolvedConflicts")
    if not isinstance(direct_conflicts, list):
        raise FinalizationError("direct audit lacks unresolvedConflicts array")
    conflict_by_id = _index(direct_conflicts, "direct conflict")
    extras = sorted(set(conflict_by_id) - set(census))
    if extras:
        raise FinalizationError(f"direct audit conflict is outside census: {extras[0]}")
    overlap = sorted(set(conflict_by_id) & set(indexed["direct"]))
    if overlap:
        raise FinalizationError(f"direct audit marks a directly resolved lexeme conflicted: {overlap[0]}")

    final: list[dict] = []
    shadowed: list[dict] = []
    conflict_resolutions: list[dict] = []
    missing: list[str] = []
    for identity in sorted(census):
        candidates = [(method, indexed[method][identity]) for method in METHODS if identity in indexed[method]]
        if not candidates:
            missing.append(identity)
            continue
        method, selected = min(candidates, key=lambda item: PRECEDENCE[item[0]])
        selected = dict(selected)
        flags = list(selected.get("flags", []))
        if identity in conflict_by_id:
            flags.append("unresolved-direct-evidence-conflict")
            conflict_resolutions.append({
                "lexemeId": identity,
                "directConflict": conflict_by_id[identity],
                "resolvedBy": method,
                "selectedLevel": selected["level"],
            })
        if flags:
            selected["flags"] = sorted(set(flags))
        final.append(selected)
        for lower_method, lower in candidates:
            if lower_method != method:
                shadowed.append({
                    "lexemeId": identity,
                    "selectedMethod": method,
                    "shadowedMethod": lower_method,
                    "selectedLevel": selected["level"],
                    "shadowedLevel": lower["level"],
                })
    if missing:
        raise FinalizationError(f"classification coverage incomplete: {len(missing)} missing; first={missing[0]}")
    if len(final) != len(census):
        raise AssertionError("final classification count differs from census")

    level_counts = Counter(row["level"] for row in final)
    method_counts = Counter(row["method"] for row in final)
    source_selected: Counter[str] = Counter()
    source_votes: Counter[str] = Counter()
    for row in final:
        if row["method"] == "direct":
            selected_ids = set(row["policy"]["selectedEvidenceIds"])
            for evidence in row["evidence"]:
                source_votes[evidence["sourceId"]] += 1
                if evidence["evidenceId"] in selected_ids:
                    source_selected[evidence["sourceId"]] += 1

    coverage = {
        "schemaVersion": 1,
        "policy": {**POLICY, "precedence": list(METHODS)},
        "census": len(census),
        "classifications": len(final),
        "complete": True,
        "byLevel": {level: level_counts[level] for level in LEVELS},
        "byMethod": {method: method_counts[method] for method in METHODS},
        "inputRows": {method: len(inputs[method]) for method in METHODS},
        "shadowedRows": len(shadowed),
    }
    reports = {
        "coverage": coverage,
        "confidence": _confidence_report(final),
        "conflicts": {
            "schemaVersion": 1,
            "counts": {"unresolvedDirectInput": len(conflict_by_id), "resolvedInFinal": len(conflict_resolutions), "shadowed": len(shadowed)},
            "directConflictResolutions": conflict_resolutions,
            "shadowed": shadowed,
        },
        "sources": {
            "schemaVersion": 1,
            "selectedDirectClassificationsBySource": dict(sorted(source_selected.items())),
            "retainedDirectVotesBySource": dict(sorted(source_votes.items())),
            "note": "Counts describe attributable third-party assertions; inferred and adjudicated labels are project estimates, not official JLPT assignments.",
        },
        "changes": _change_report(final, baseline, change_explanations),
    }
    return final, reports


def finalize_files(
    lexemes_path: Path,
    direct_path: Path,
    inferred_path: Path,
    adjudicated_path: Path,
    direct_audit_path: Path,
    output_path: Path,
    reports_dir: Path,
    *,
    baseline_path: Path | None = None,
    change_explanations_path: Path | None = None,
) -> dict[str, dict]:
    change_explanations = None
    if change_explanations_path is not None:
        change_explanations = json.loads(change_explanations_path.read_text(encoding="utf-8"))
        if not isinstance(change_explanations, dict):
            raise FinalizationError("change explanations must be a lexemeId-to-reason object")
    final, reports = finalize_records(
        read_jsonl(lexemes_path),
        read_jsonl(direct_path),
        read_jsonl(inferred_path),
        read_jsonl(adjudicated_path),
        json.loads(direct_audit_path.read_text(encoding="utf-8")),
        baseline=read_jsonl(baseline_path) if baseline_path is not None else None,
        change_explanations=change_explanations,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output:
        for row in final:
            output.write(canonical_json_bytes(row))
    reports_dir.mkdir(parents=True, exist_ok=True)
    for name, report in reports.items():
        (reports_dir / f"{name}.json").write_bytes(canonical_json_bytes(report))
    manifest = {
        "schemaVersion": 1,
        "policy": POLICY,
        "classificationsSha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "reports": {
            name: hashlib.sha256((reports_dir / f"{name}.json").read_bytes()).hexdigest()
            for name in sorted(reports)
        },
    }
    (reports_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return reports
