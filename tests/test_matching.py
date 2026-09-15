from __future__ import annotations

import json
from pathlib import Path

import pytest

from jlpt_levels.identity import lexeme_id
from jlpt_levels.matching import MatchingError, match_files, match_records, normalize_text


def lexeme(term: str, reading: str, *sequences: int) -> dict:
    return {
        "lexemeId": lexeme_id(term, reading),
        "term": term,
        "reading": reading,
        "jitendex": {
            "upstreamIds": [f"jitendex:sequence:{item}" for item in sequences],
            "occurrences": [{"bank": "term_bank_1.json", "row": 0, "sequence": item} for item in sequences],
            "dictionarySha256": "0" * 64,
        },
    }


def evidence(identity: str, term: str, reading: str) -> dict:
    return {"evidenceId": identity, "term": term, "reading": reading}


def test_script_and_iteration_mark_normalization_is_conservative() -> None:
    assert normalize_text("カタカナ") == "かたかな"
    assert normalize_text("時々") == "時時"
    assert normalize_text("くゝ") == "くく"
    assert normalize_text("くゞ") == "くぐ"
    assert normalize_text("ば") == "ば"
    assert normalize_text("々時") == "々時"
    assert normalize_text("んゞ") == "んゞ"


def test_exact_and_normalized_matches_are_reported_separately() -> None:
    rows = [lexeme("時々", "ときどき", 1), lexeme("カタカナ", "カタカナ", 2)]
    items = [evidence("e:1", "時々", "ときどき"), evidence("e:2", "かたかな", "かたかな")]
    matches, report = match_records(rows, items)
    assert [item["matchKind"] for item in matches] == ["exact-match", "normalized-match"]
    assert report["counts"] == {"exact-match": 1, "normalized-match": 1, "ambiguous": 0, "unmatched": 0}


def test_orthographic_variants_expand_only_with_shared_jitendex_identity_and_reading() -> None:
    rows = [
        lexeme("取り扱う", "とりあつかう", 10),
        lexeme("取扱う", "とりあつかう", 10),
        lexeme("取扱い", "とりあつかい", 10),
    ]
    matches, _ = match_records(rows, [evidence("e:1", "取り扱う", "とりあつかう")])
    assert matches[0]["targetLexemeIds"] == sorted([
        lexeme_id("取り扱う", "とりあつかう"), lexeme_id("取扱う", "とりあつかう")
    ])


def test_homographs_are_never_smeared_across_readings_or_unrelated_entries() -> None:
    rows = [
        lexeme("生", "せい", 20), lexeme("生", "しょう", 21),
        lexeme("はし", "はし", 30), lexeme("ハシ", "ハシ", 31),
    ]
    matches, report = match_records(rows, [
        evidence("e:reading", "生", "せい"), evidence("e:ambiguous", "ハシ", "はし")
    ])
    assert matches[0]["targetLexemeIds"] == [lexeme_id("生", "せい")]
    assert report["counts"]["ambiguous"] == 1
    assert report["ambiguous"][0]["candidateLexemeIds"] == sorted([
        lexeme_id("はし", "はし"), lexeme_id("ハシ", "ハシ")
    ])


def test_okurigana_is_not_guessed_and_unmatched_is_explicit() -> None:
    _, report = match_records(
        [lexeme("行う", "おこなう", 40)],
        [evidence("e:1", "行なう", "おこなう")],
    )
    assert report["counts"]["unmatched"] == 1
    assert report["unmatched"][0]["reason"] == "no exact or conservative normalized lexeme"


def test_every_evidence_record_has_exactly_one_outcome() -> None:
    rows = [lexeme("猫", "ねこ", 1)]
    with pytest.raises(MatchingError, match="duplicate or invalid evidence identity"):
        match_records(rows, [evidence("e:1", "猫", "ねこ"), evidence("e:1", "犬", "いぬ")])


def test_identity_and_jsonl_inputs_fail_closed(tmp_path: Path) -> None:
    bad = lexeme("猫", "ねこ", 1)
    bad["lexemeId"] = lexeme_id("犬", "いぬ")
    with pytest.raises(MatchingError, match="identity mismatch"):
        match_records([bad], [])
    source = tmp_path / "bad.jsonl"
    source.write_text("not json\n", encoding="utf-8")
    evidence_path = tmp_path / "evidence.jsonl"
    evidence_path.write_text("", encoding="utf-8")
    with pytest.raises(MatchingError, match="invalid JSON"):
        match_files(source, evidence_path, tmp_path / "matches", tmp_path / "report")


def test_file_outputs_are_canonical_and_deterministic(tmp_path: Path) -> None:
    lexemes_path = tmp_path / "lexemes.jsonl"
    evidence_path = tmp_path / "evidence.jsonl"
    lexemes_path.write_text(json.dumps(lexeme("猫", "ねこ", 1), ensure_ascii=False) + "\n", encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence("e:1", "猫", "ねこ"), ensure_ascii=False) + "\n", encoding="utf-8")
    first_matches, first_report = tmp_path / "first.jsonl", tmp_path / "first-report.json"
    second_matches, second_report = tmp_path / "second.jsonl", tmp_path / "second-report.json"
    match_files(lexemes_path, evidence_path, first_matches, first_report)
    match_files(lexemes_path, evidence_path, second_matches, second_report)
    assert first_matches.read_bytes() == second_matches.read_bytes()
    assert first_report.read_bytes() == second_report.read_bytes()
    assert first_report.read_bytes().endswith(b"\n")
