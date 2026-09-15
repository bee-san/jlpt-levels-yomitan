from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from jlpt_levels.finalize import FinalizationError, finalize_files, finalize_records
from jlpt_levels.identity import lexeme_id


def lexeme(term: str, reading: str) -> dict:
    return {"lexemeId": lexeme_id(term, reading), "term": term, "reading": reading}


def direct(row: dict, level: str = "N5") -> dict:
    evidence_id = "evidence:" + "a" * 64
    return {
        "lexemeId": row["lexemeId"], "level": level, "method": "direct", "confidence": 0.9,
        "conflict": False,
        "evidence": [{
            "evidenceId": evidence_id, "sourceId": "source-a", "sourceRecord": "row-1",
            "snapshotSha256": "b" * 64, "capturedAt": "2026-09-15T00:00:00Z", "assertedLevel": level,
        }],
        "policy": {"name": "direct-evidence-resolution", "version": "1.0.0", "selectedEvidenceIds": [evidence_id]},
    }


def estimate(row: dict, method: str, level: str, confidence: float = 0.7) -> dict:
    result = {
        "lexemeId": row["lexemeId"], "level": level, "method": method, "confidence": confidence,
        "conflict": False, "evidence": [], "features": {},
        "policy": {"name": "test-policy", "version": "1.0.0"},
    }
    if method == "adjudicated":
        result["adjudication"] = {
            "provider": "bedrock", "model": "global.openai.gpt-5.6-luna", "promptVersion": "1.0.0",
            "inputSha256": "c" * 64, "outputSha256": "d" * 64, "batchSize": 1,
            "runAt": "2026-09-15T00:00:00Z",
        }
    if level == "N0":
        result["features"]["postN1DifficultySignals"] = ["attested-specialist-register"]
    return result


def audit(conflicts=()) -> dict:
    return {"unresolvedConflicts": list(conflicts)}


def test_strict_precedence_complete_reports_and_conflict_flag() -> None:
    cat, dog, owl = lexeme("猫", "ねこ"), lexeme("犬", "いぬ"), lexeme("梟", "ふくろう")
    conflict = {"lexemeId": dog["lexemeId"], "levels": ["N3", "N4"], "votes": [], "reason": "fixture", "strongestMatchKind": "exact-match"}
    final, reports = finalize_records(
        [cat, dog, owl],
        [direct(cat)],
        [estimate(cat, "inferred", "N4"), estimate(dog, "inferred", "N3")],
        [estimate(owl, "adjudicated", "N0")],
        audit([conflict]),
    )
    by_id = {row["lexemeId"]: row for row in final}
    assert by_id[cat["lexemeId"]]["method"] == "direct"
    assert by_id[dog["lexemeId"]]["flags"] == ["unresolved-direct-evidence-conflict"]
    assert by_id[owl["lexemeId"]]["level"] == "N0"
    assert reports["coverage"]["complete"] is True
    assert reports["coverage"]["byMethod"] == {"direct": 1, "inferred": 1, "adjudicated": 1}
    assert reports["coverage"]["byLevel"] == {"N5": 1, "N4": 0, "N3": 1, "N2": 0, "N1": 0, "N0": 1}
    assert reports["conflicts"]["counts"] == {"unresolvedDirectInput": 1, "resolvedInFinal": 1, "shadowed": 1}
    assert reports["sources"]["selectedDirectClassificationsBySource"] == {"source-a": 1}


def test_missing_extra_duplicate_and_invalid_rows_fail_closed() -> None:
    cat, dog = lexeme("猫", "ねこ"), lexeme("犬", "いぬ")
    with pytest.raises(FinalizationError, match="coverage incomplete"):
        finalize_records([cat, dog], [direct(cat)], [], [], audit())
    with pytest.raises(FinalizationError, match="non-census"):
        finalize_records([cat], [direct(dog)], [], [], audit())
    with pytest.raises(FinalizationError, match="duplicate direct"):
        finalize_records([cat], [direct(cat), direct(cat)], [], [], audit())
    invalid = direct(cat)
    invalid["level"] = "N0"
    with pytest.raises(FinalizationError, match="invalid direct classification"):
        finalize_records([cat], [invalid], [], [], audit())


def test_inference_cannot_masquerade_as_direct_or_official() -> None:
    cat = lexeme("猫", "ねこ")
    masquerade = estimate(cat, "inferred", "N4")
    masquerade["method"] = "direct"
    with pytest.raises(FinalizationError, match="invalid direct classification"):
        finalize_records([cat], [masquerade], [], [], audit())


def test_change_report_exposes_every_level_or_method_regression() -> None:
    cat, dog = lexeme("猫", "ねこ"), lexeme("犬", "いぬ")
    current = [direct(cat), estimate(dog, "inferred", "N3")]
    baseline = [direct(cat), estimate(dog, "adjudicated", "N4")]
    with pytest.raises(FinalizationError, match="unexplained classification changes"):
        finalize_records([cat, dog], [current[0]], [current[1]], [], audit(), baseline=baseline)
    _, reports = finalize_records(
        [cat, dog], [current[0]], [current[1]], [], audit(), baseline=baseline,
        change_explanations={dog["lexemeId"]: "new locked source evidence changed calibration"},
    )
    assert reports["changes"]["counts"] == {"added": 0, "removed": 0, "changed": 1, "unchanged": 1}
    assert reports["changes"]["changed"][0]["from"] == {"level": "N4", "method": "adjudicated"}
    assert reports["changes"]["changed"][0]["to"] == {"level": "N3", "method": "inferred"}
    assert reports["changes"]["unexplainedLexemeIds"] == []
    with pytest.raises(FinalizationError, match="stale change explanation"):
        finalize_records(
            [cat, dog], [current[0]], [current[1]], [], audit(), baseline=current,
            change_explanations={dog["lexemeId"]: "stale"},
        )


def test_files_are_deterministic_and_manifest_binds_every_report(tmp_path: Path) -> None:
    cat = lexeme("猫", "ねこ")
    paths = {}
    for name, rows in {"lexemes": [cat], "direct": [direct(cat)], "inferred": [], "adjudicated": []}.items():
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        paths[name] = path
    direct_audit = tmp_path / "direct-audit.json"
    direct_audit.write_text(json.dumps(audit()), encoding="utf-8")
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    first_reports, second_reports = tmp_path / "first-reports", tmp_path / "second-reports"
    finalize_files(paths["lexemes"], paths["direct"], paths["inferred"], paths["adjudicated"], direct_audit, first, first_reports)
    finalize_files(paths["lexemes"], paths["direct"], paths["inferred"], paths["adjudicated"], direct_audit, second, second_reports)
    assert first.read_bytes() == second.read_bytes()
    assert {path.name: path.read_bytes() for path in first_reports.iterdir()} == {path.name: path.read_bytes() for path in second_reports.iterdir()}
    manifest = json.loads((first_reports / "manifest.json").read_text())
    assert set(manifest["reports"]) == {"changes", "confidence", "conflicts", "coverage", "sources"}
