from __future__ import annotations

import json
from pathlib import Path

import pytest

from jlpt_levels.contracts import errors
from jlpt_levels.identity import lexeme_id
from jlpt_levels.resolution import ResolutionError, resolve_files, resolve_records


def lexeme(term: str, reading: str) -> dict:
    return {"lexemeId": lexeme_id(term, reading), "term": term, "reading": reading}


def evidence(identity: str, level: str, source: str = "source-a") -> dict:
    suffix = identity.rsplit(":", 1)[-1]
    return {
        "assertedLevel": level,
        "capturedAt": "2026-09-15T00:00:00Z",
        "evidenceId": identity,
        "sourceId": source,
        "sourceRecord": f"row-{suffix}",
        "snapshotSha256": suffix[0] * 64,
    }


def match(identity: str, target: str, kind: str = "exact-match") -> dict:
    return {"evidenceId": identity, "matchKind": kind, "targetLexemeIds": [target]}


def test_exact_evidence_wins_over_normalized_without_discarding_conflict() -> None:
    row = lexeme("猫", "ねこ")
    exact = evidence("evidence:" + "a" * 64, "N5")
    normalized = evidence("evidence:" + "b" * 64, "N4", "source-b")
    classifications, audit = resolve_records(
        [row],
        [normalized, exact],
        [match(normalized["evidenceId"], row["lexemeId"], "normalized-match"), match(exact["evidenceId"], row["lexemeId"])],
    )
    result = classifications[0]
    assert result["level"] == "N5"
    assert result["conflict"] is True
    assert result["confidence"] == 0.85
    assert result["policy"]["selectedEvidenceIds"] == [exact["evidenceId"]]
    assert {item["evidenceId"] for item in result["evidence"]} == {exact["evidenceId"], normalized["evidenceId"]}
    assert audit["coverage"]["resolvedByMatchKind"] == {"exact-match": 1}


def test_conflicting_strongest_votes_are_unresolved_not_majority_voted() -> None:
    row = lexeme("橋", "はし")
    votes = [
        evidence("evidence:" + "a" * 64, "N4", "source-a"),
        evidence("evidence:" + "b" * 64, "N4", "source-a"),
        evidence("evidence:" + "c" * 64, "N3", "source-b"),
    ]
    classifications, audit = resolve_records(
        [row], votes, [match(item["evidenceId"], row["lexemeId"]) for item in votes]
    )
    assert classifications == []
    assert audit["coverage"]["lexemes"]["unresolvedDirectConflict"] == 1
    unresolved = audit["unresolvedConflicts"][0]
    assert unresolved["levels"] == ["N3", "N4"]
    assert len(unresolved["votes"]) == 3


def test_independent_sources_not_duplicate_rows_raise_confidence() -> None:
    row = lexeme("犬", "いぬ")
    duplicate_source = [
        evidence("evidence:" + "a" * 64, "N5", "source-a"),
        evidence("evidence:" + "b" * 64, "N5", "source-a"),
    ]
    classifications, _ = resolve_records(
        [row], duplicate_source, [match(item["evidenceId"], row["lexemeId"]) for item in duplicate_source]
    )
    assert classifications[0]["confidence"] == 0.90
    corroborated = duplicate_source + [evidence("evidence:" + "c" * 64, "N5", "source-b")]
    classifications, audit = resolve_records(
        [row], corroborated, [match(item["evidenceId"], row["lexemeId"]) for item in corroborated]
    )
    assert classifications[0]["confidence"] == 0.97
    assert audit["coverage"]["resolvedBySource"] == {"source-a": 1, "source-b": 1}


def test_coverage_counts_unmatched_lexemes_and_evidence() -> None:
    cat, dog = lexeme("猫", "ねこ"), lexeme("犬", "いぬ")
    used = evidence("evidence:" + "a" * 64, "N5")
    unused = evidence("evidence:" + "b" * 64, "N4")
    _, audit = resolve_records([cat, dog], [used, unused], [match(used["evidenceId"], cat["lexemeId"])])
    assert audit["coverage"]["lexemes"] == {
        "total": 2,
        "withDirectVotes": 1,
        "resolvedDirect": 1,
        "unresolvedDirectConflict": 0,
        "withoutDirectVotes": 1,
    }
    assert audit["coverage"]["evidence"] == {"total": 2, "matched": 1, "notInMatchInput": 1}
    assert audit["coverage"]["resolvedByLevel"] == {"N5": 1, "N4": 0, "N3": 0, "N2": 0, "N1": 0}


def test_invalid_and_dangling_inputs_fail_closed() -> None:
    row = lexeme("猫", "ねこ")
    item = evidence("evidence:" + "a" * 64, "N5")
    with pytest.raises(ResolutionError, match="unknown evidence"):
        resolve_records([row], [item], [match("evidence:" + "b" * 64, row["lexemeId"])])
    with pytest.raises(ResolutionError, match="unknown lexeme"):
        resolve_records([row], [item], [match(item["evidenceId"], lexeme_id("犬", "いぬ"))])
    with pytest.raises(ResolutionError, match="duplicate match"):
        resolve_records([row], [item], [match(item["evidenceId"], row["lexemeId"])] * 2)


def test_outputs_are_deterministic_and_validate_classification_contract(tmp_path: Path) -> None:
    row = lexeme("猫", "ねこ")
    item = evidence("evidence:" + "a" * 64, "N5")
    inputs = []
    for name, records in (("lexemes", [row]), ("evidence", [item]), ("matches", [match(item["evidenceId"], row["lexemeId"])])):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
        inputs.append(path)
    first_classifications, first_audit = tmp_path / "first.jsonl", tmp_path / "first-audit.json"
    second_classifications, second_audit = tmp_path / "second.jsonl", tmp_path / "second-audit.json"
    resolve_files(inputs[0], inputs[1], inputs[2], first_classifications, first_audit)
    resolve_files(inputs[0], inputs[1], inputs[2], second_classifications, second_audit)
    assert first_classifications.read_bytes() == second_classifications.read_bytes()
    assert first_audit.read_bytes() == second_audit.read_bytes()
    result = json.loads(first_classifications.read_text(encoding="utf-8"))
    assert errors("classification.schema.json", result) == []
