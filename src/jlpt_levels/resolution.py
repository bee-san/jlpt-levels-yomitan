from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .identity import canonical_json_bytes


class ResolutionError(ValueError):
    pass


POLICY = {"name": "direct-evidence-resolution", "version": "1.0.0"}
_MATCH_PRIORITY = {"exact-match": 2, "normalized-match": 1}
_EVIDENCE_FIELDS = (
    "evidenceId",
    "sourceId",
    "sourceRecord",
    "snapshotSha256",
    "capturedAt",
    "assertedLevel",
)


def _records(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ResolutionError(f"{path}:{line_number}: invalid JSON") from error
            if not isinstance(record, dict):
                raise ResolutionError(f"{path}:{line_number}: record must be an object")
            records.append(record)
    return records


def _unique(records: Iterable[dict], field: str, kind: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for record in records:
        identity = record.get(field)
        if not isinstance(identity, str) or not identity or identity in indexed:
            raise ResolutionError(f"duplicate or invalid {kind} identity: {identity!r}")
        indexed[identity] = record
    return indexed


def _confidence(kind: str, selected: list[dict], lower_tier_disagreement: bool) -> float:
    independent_sources = len({item["sourceId"] for item in selected})
    if kind == "exact-match":
        value = 0.97 if independent_sources > 1 else 0.90
    else:
        value = 0.85 if independent_sources > 1 else 0.75
    if lower_tier_disagreement:
        value -= 0.05
    return round(value, 2)


def _classification_evidence(source: dict) -> dict:
    result = {field: source[field] for field in _EVIDENCE_FIELDS}
    if "quote" in source:
        result["quote"] = source["quote"]
    return result


def resolve_records(
    lexemes: Iterable[dict], evidence: Iterable[dict], matches: Iterable[dict]
) -> tuple[list[dict], dict]:
    lexeme_by_id = _unique(lexemes, "lexemeId", "lexeme")
    evidence_by_id = _unique(evidence, "evidenceId", "evidence")
    votes_by_lexeme: dict[str, list[dict]] = defaultdict(list)
    seen_matches: set[str] = set()

    for match in matches:
        evidence_id = match.get("evidenceId")
        kind = match.get("matchKind")
        targets = match.get("targetLexemeIds")
        if evidence_id in seen_matches:
            raise ResolutionError(f"duplicate match for evidence: {evidence_id!r}")
        if evidence_id not in evidence_by_id:
            raise ResolutionError(f"match references unknown evidence: {evidence_id!r}")
        if kind not in _MATCH_PRIORITY:
            raise ResolutionError(f"invalid match kind: {kind!r}")
        if not isinstance(targets, list) or not targets or len(set(targets)) != len(targets):
            raise ResolutionError(f"invalid targets for evidence: {evidence_id!r}")
        seen_matches.add(evidence_id)
        for target in targets:
            if target not in lexeme_by_id:
                raise ResolutionError(f"match references unknown lexeme: {target!r}")
            votes_by_lexeme[target].append(
                {"evidence": evidence_by_id[evidence_id], "matchKind": kind}
            )

    classifications: list[dict] = []
    decisions: list[dict] = []
    unresolved: list[dict] = []
    level_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    vote_source_counts: Counter[str] = Counter()
    vote_match_counts: Counter[str] = Counter()
    match_counts: Counter[str] = Counter()

    for lexeme_id in sorted(votes_by_lexeme):
        votes = sorted(
            votes_by_lexeme[lexeme_id],
            key=lambda item: item["evidence"]["evidenceId"],
        )
        for vote in votes:
            vote_source_counts[vote["evidence"]["sourceId"]] += 1
            vote_match_counts[vote["matchKind"]] += 1
        strongest = max(_MATCH_PRIORITY[item["matchKind"]] for item in votes)
        decisive = [item for item in votes if _MATCH_PRIORITY[item["matchKind"]] == strongest]
        decisive_levels = sorted({item["evidence"]["assertedLevel"] for item in decisive})
        all_levels = sorted({item["evidence"]["assertedLevel"] for item in votes})
        audit_votes = [
            {"matchKind": item["matchKind"], **item["evidence"]} for item in votes
        ]
        if len(decisive_levels) != 1:
            record = {
                "lexemeId": lexeme_id,
                "levels": decisive_levels,
                "reason": "strongest direct evidence disagrees; deterministic inference or adjudication required",
                "strongestMatchKind": decisive[0]["matchKind"],
                "votes": audit_votes,
            }
            unresolved.append(record)
            decisions.append({"status": "unresolved-conflict", **record})
            continue

        level = decisive_levels[0]
        selected = [item["evidence"] for item in decisive if item["evidence"]["assertedLevel"] == level]
        lower_disagreement = len(all_levels) > 1
        classification = {
            "confidence": _confidence(decisive[0]["matchKind"], selected, lower_disagreement),
            "conflict": len(all_levels) > 1,
            "evidence": [_classification_evidence(item) for item in (entry["evidence"] for entry in votes)],
            "level": level,
            "lexemeId": lexeme_id,
            "method": "direct",
            "policy": {
                **POLICY,
                "selectedEvidenceIds": sorted(item["evidenceId"] for item in selected),
            },
        }
        classifications.append(classification)
        level_counts[level] += 1
        match_counts[decisive[0]["matchKind"]] += 1
        for source_id in {item["sourceId"] for item in selected}:
            source_counts[source_id] += 1
        decisions.append(
            {
                "classification": classification,
                "status": "resolved",
                "strongestMatchKind": decisive[0]["matchKind"],
                "votes": audit_votes,
            }
        )

    matched_evidence = set(seen_matches)
    audit = {
        "schemaVersion": 1,
        "policy": {
            **POLICY,
            "confidenceCalibration": {
                "exactSingleSource": 0.90,
                "exactIndependentCorroboration": 0.97,
                "normalizedSingleSource": 0.75,
                "normalizedIndependentCorroboration": 0.85,
                "lowerTierDisagreementPenalty": 0.05,
            },
            "rule": "use exact evidence when present, otherwise normalized evidence; resolve only unanimous strongest-tier levels; duplicate rows from one source do not increase confidence",
        },
        "coverage": {
            "lexemes": {
                "total": len(lexeme_by_id),
                "withDirectVotes": len(votes_by_lexeme),
                "resolvedDirect": len(classifications),
                "unresolvedDirectConflict": len(unresolved),
                "withoutDirectVotes": len(lexeme_by_id) - len(votes_by_lexeme),
            },
            "evidence": {
                "total": len(evidence_by_id),
                "matched": len(matched_evidence),
                "notInMatchInput": len(evidence_by_id) - len(matched_evidence),
            },
            "resolvedByLevel": {level: level_counts[level] for level in ("N5", "N4", "N3", "N2", "N1")},
            "resolvedBySource": dict(sorted(source_counts.items())),
            "resolvedByMethod": {"direct": len(classifications)},
            "resolvedByMatchKind": dict(sorted(match_counts.items())),
            "directVotesBySource": dict(sorted(vote_source_counts.items())),
            "directVotesByMatchKind": dict(sorted(vote_match_counts.items())),
        },
        "decisions": decisions,
        "unresolvedConflicts": unresolved,
    }
    if len(classifications) + len(unresolved) != len(votes_by_lexeme):
        raise AssertionError("resolution lost lexemes with direct votes")
    return classifications, audit


def resolve_files(
    lexemes_path: Path,
    evidence_path: Path,
    matches_path: Path,
    classifications_path: Path,
    audit_path: Path,
) -> dict:
    classifications, audit = resolve_records(
        _records(lexemes_path), _records(evidence_path), _records(matches_path)
    )
    classifications_path.parent.mkdir(parents=True, exist_ok=True)
    with classifications_path.open("wb") as output:
        for record in classifications:
            output.write(canonical_json_bytes(record))
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_bytes(canonical_json_bytes(audit))
    return audit
