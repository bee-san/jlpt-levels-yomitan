from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from jlpt_levels.identity import canonical_json_bytes, lexeme_id
from jlpt_levels.package import PackagingError, build_dictionary


def _lexeme(term: str, reading: str) -> dict:
    return {
        "lexemeId": lexeme_id(term, reading),
        "term": term,
        "reading": reading,
        "jitendex": {
            "dictionarySha256": "b" * 64,
            "occurrences": [{"bank": "term_bank_1.json", "row": 0, "sequence": 1}],
            "upstreamIds": ["jitendex:sequence:1"],
        },
    }


def _classification(lexeme: dict, level: str, *, conflict: bool = False) -> dict:
    features: dict[str, object] = {"maximumComponentKanjiLevel": level}
    if level == "N0":
        features["postN1DifficultySignals"] = ["specialist-register"]
    if conflict:
        selected_id = "evidence:" + "c" * 64
        return {
            "lexemeId": lexeme["lexemeId"],
            "level": level,
            "method": "direct",
            "confidence": 0.75,
            "conflict": True,
            "policy": {"name": "direct-evidence-resolution", "version": "1.0.0", "selectedEvidenceIds": [selected_id]},
            "evidence": [
                {"evidenceId": selected_id, "sourceId": "source-a", "sourceRecord": "1", "snapshotSha256": "d" * 64, "capturedAt": "2026-09-15T00:00:00Z", "assertedLevel": level},
                {"evidenceId": "evidence:" + "e" * 64, "sourceId": "source-b", "sourceRecord": "2", "snapshotSha256": "f" * 64, "capturedAt": "2026-09-15T00:00:00Z", "assertedLevel": "N4"},
            ],
        }
    return {
        "lexemeId": lexeme["lexemeId"],
        "level": level,
        "method": "inferred",
        "confidence": 0.75,
        "conflict": False,
        "policy": {"name": "conservative-lexeme-inference", "version": "1.0.0"},
        "evidence": [],
        "features": features,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))


def _inputs(tmp_path: Path, count: int = 7) -> tuple[Path, Path, Path, Path, Path]:
    levels = ["N5", "N4", "N3", "N2", "N1", "N0", "N3"]
    lexemes = [_lexeme(f"語{index}", f"ご{index}") for index in range(count)]
    classifications = [
        _classification(lexeme, levels[index], conflict=index == 2)
        for index, lexeme in enumerate(lexemes)
    ]
    lexemes_path = tmp_path / "lexemes.jsonl"
    classifications_path = tmp_path / "classifications.jsonl"
    registry_path = tmp_path / "sources.json"
    vocabulary_registry_path = tmp_path / "vocabulary-sources.json"
    lock_path = tmp_path / "jitendex.lock.json"
    _write_jsonl(lexemes_path, list(reversed(lexemes)))
    _write_jsonl(classifications_path, classifications)
    registry_path.write_bytes(canonical_json_bytes({
        "version": 1,
        "sources": [{
            "id": "jitendex",
            "acquisition": {"sha256": "b" * 64},
            "license": {"status": "verified", "redistributable": True, "attribution": "Jitendex CC BY-SA 4.0"},
        }],
    }))
    vocabulary_registry_path.write_bytes(canonical_json_bytes({
        "version": 1,
        "sources": [
            {"id": "source-a", "license": {"redistributable": True, "attribution": "Source A"}},
            {"id": "source-b", "license": {"redistributable": True, "attribution": "Source B"}},
        ],
    }))
    lock_path.write_bytes(canonical_json_bytes({
        "artifact": {"sha256": "b" * 64},
        "release": {"tag": "2026.08.11.0"},
    }))
    return lexemes_path, classifications_path, registry_path, vocabulary_registry_path, lock_path


def _build(tmp_path: Path, name: str = "one", *, bank_size: int = 3):
    lexemes, classifications, registry, vocabulary_registry, lock = _inputs(tmp_path)
    return build_dictionary(
        lexemes,
        classifications,
        registry,
        vocabulary_registry,
        lock,
        tmp_path / name,
        revision="2026.09.15",
        created_at="2026-09-15T00:00:00Z",
        bank_size=bank_size,
    )


def test_build_emits_reproducible_valid_yomitan_zip_and_sidecars(tmp_path: Path) -> None:
    first = _build(tmp_path, "first")
    second = _build(tmp_path, "second")

    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    assert first.zip_sha256 == hashlib.sha256(first.zip_path.read_bytes()).hexdigest()
    assert first.sha256s_path.read_text(encoding="utf-8") == f"{first.zip_sha256}  {first.zip_path.name}\n"

    with zipfile.ZipFile(first.zip_path) as archive:
        assert archive.namelist() == [
            "index.json",
            "term_meta_bank_1.json",
            "term_meta_bank_2.json",
            "term_meta_bank_3.json",
        ]
        assert len({info.date_time for info in archive.infolist()}) == 1
        index = json.loads(archive.read("index.json"))
        banks = [json.loads(archive.read(name)) for name in archive.namelist()[1:]]

    assert index["format"] == 3
    assert index["frequencyMode"] == "rank-based"
    assert index["revision"] == "2026.09.15"
    assert "N0 is harder than N1" in index["description"]
    assert [len(bank) for bank in banks] == [3, 3, 1]
    rows = [row for bank in banks for row in bank]
    assert rows == sorted(rows, key=lambda row: (row[0], row[2]["reading"]))
    assert {row[2]["frequency"]["displayValue"]: row[2]["frequency"]["value"] for row in rows} == {
        "N5": 1,
        "N4": 2,
        "N3": 3,
        "N2": 4,
        "N1": 5,
        "N0": 6,
    }

    root = Path(__file__).parents[1]
    index_schema = json.loads((root / "schemas/vendor/yomitan/d34832d756e05dc00945e5b7d7ebc80963299a7a/dictionary-index-schema.json").read_text())
    bank_schema = json.loads((root / "schemas/vendor/yomitan/d34832d756e05dc00945e5b7d7ebc80963299a7a/dictionary-term-meta-bank-v3-schema.json").read_text())
    Draft7Validator(index_schema).validate(index)
    for bank in banks:
        Draft7Validator(bank_schema).validate(bank)

    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["lexemes"] == 7
    assert manifest["counts"]["classifications"] == 7
    assert manifest["counts"]["conflicts"] == 1
    assert manifest["counts"]["levels"] == {"N0": 1, "N1": 1, "N2": 1, "N3": 2, "N4": 1, "N5": 1}
    assert manifest["inputs"]["lexemes"]["sha256"] == hashlib.sha256((tmp_path / "lexemes.jsonl").read_bytes()).hexdigest()
    assert manifest["inputs"]["classifications"]["sha256"] == hashlib.sha256((tmp_path / "classifications.jsonl").read_bytes()).hexdigest()
    assert manifest["inputs"]["vocabularySourceRegistry"]["sha256"] == hashlib.sha256((tmp_path / "vocabulary-sources.json").read_bytes()).hexdigest()
    assert manifest["inputs"]["jitendexLock"]["sha256"] == hashlib.sha256((tmp_path / "jitendex.lock.json").read_bytes()).hexdigest()
    assert [item["path"] for item in manifest["files"]] == archive.namelist()
    for item in manifest["files"]:
        with zipfile.ZipFile(first.zip_path) as archive:
            payload = archive.read(item["path"])
        assert item["bytes"] == len(payload)
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()


def test_build_preserves_written_form_and_reading_precision(tmp_path: Path) -> None:
    term = "生"
    lexemes = [_lexeme(term, "せい"), _lexeme(term, "なま")]
    classifications = [_classification(lexemes[0], "N2"), _classification(lexemes[1], "N1")]
    paths = _inputs(tmp_path)[:2]
    _write_jsonl(paths[0], lexemes)
    _write_jsonl(paths[1], classifications)
    result = build_dictionary(
        paths[0], paths[1], tmp_path / "sources.json", tmp_path / "vocabulary-sources.json",
        tmp_path / "jitendex.lock.json", tmp_path / "out", revision="2026.09.15", created_at="2026-09-15T00:00:00Z",
    )
    with zipfile.ZipFile(result.zip_path) as archive:
        rows = json.loads(archive.read("term_meta_bank_1.json"))
    assert [(row[0], row[2]["reading"], row[2]["frequency"]["displayValue"]) for row in rows] == [
        ("生", "せい", "N2"),
        ("生", "なま", "N1"),
    ]


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_build_fails_closed_on_classification_census_mismatch(tmp_path: Path, mutation: str) -> None:
    lexemes_path, classifications_path, registry, vocabulary_registry, lock = _inputs(tmp_path)
    rows = [json.loads(line) for line in classifications_path.read_text().splitlines()]
    if mutation == "missing":
        rows.pop()
    elif mutation == "extra":
        foreign = _lexeme("外", "そと")
        rows.append(_classification(foreign, "N4"))
    else:
        rows.append(rows[0])
    _write_jsonl(classifications_path, rows)
    with pytest.raises(PackagingError):
        build_dictionary(
            lexemes_path, classifications_path, registry, vocabulary_registry, lock, tmp_path / "out",
            revision="2026.09.15", created_at="2026-09-15T00:00:00Z",
        )


def test_build_fails_before_replacing_outputs_when_manifest_metadata_is_invalid(tmp_path: Path) -> None:
    prior = _build(tmp_path, "out")
    original = {path.name: path.read_bytes() for path in (prior.zip_path, prior.manifest_path, prior.sha256s_path)}
    with pytest.raises(PackagingError, match="manifest"):
        lexemes, classifications, registry, vocabulary_registry, lock = _inputs(tmp_path)
        build_dictionary(
            lexemes, classifications, registry, vocabulary_registry, lock, tmp_path / "out",
            revision="invalid", created_at="2026-09-15T00:00:00Z",
        )
    assert {path.name: path.read_bytes() for path in (prior.zip_path, prior.manifest_path, prior.sha256s_path)} == original


def test_build_rejects_unregistered_evidence_and_registry_lock_digest_drift(tmp_path: Path) -> None:
    lexemes, classifications, registry, vocabulary_registry, lock = _inputs(tmp_path)
    vocabulary_registry.write_bytes(canonical_json_bytes({"version": 1, "sources": [{
        "id": "source-a", "license": {"redistributable": True, "attribution": "Source A"},
    }]}))
    with pytest.raises(PackagingError, match="unregistered source"):
        build_dictionary(
            lexemes, classifications, registry, vocabulary_registry, lock, tmp_path / "out",
            revision="2026.09.15", created_at="2026-09-15T00:00:00Z",
        )
    _, _, registry, vocabulary_registry, lock = _inputs(tmp_path)
    locked = json.loads(lock.read_text())
    locked["artifact"]["sha256"] = "a" * 64
    lock.write_bytes(canonical_json_bytes(locked))
    with pytest.raises(PackagingError, match="do not agree"):
        build_dictionary(
            lexemes, classifications, registry, vocabulary_registry, lock, tmp_path / "out",
            revision="2026.09.15", created_at="2026-09-15T00:00:00Z",
        )


def test_build_fails_closed_when_any_registered_source_is_not_redistributable(tmp_path: Path) -> None:
    lexemes, classifications, registry, vocabulary_registry, lock = _inputs(tmp_path)
    registry.write_bytes(canonical_json_bytes({
        "version": 1,
        "sources": [{"id": "blocked", "license": {"status": "unknown", "redistributable": False}}],
    }))
    with pytest.raises(PackagingError, match="redistribution"):
        build_dictionary(
            lexemes, classifications, registry, vocabulary_registry, lock, tmp_path / "out",
            revision="2026.09.15", created_at="2026-09-15T00:00:00Z",
        )
