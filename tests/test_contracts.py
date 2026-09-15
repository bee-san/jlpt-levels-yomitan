from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jsonschema import Draft7Validator

from jlpt_levels.contracts import DATA_DIR, EXAMPLE_DIR, VENDORED_YOMITAN_DIR, errors, load_json, validate_examples


def test_declared_positive_and_negative_examples() -> None:
    checked, failures = validate_examples()
    assert checked >= 16
    assert failures == []


@pytest.mark.parametrize(
    ("level", "method", "evidence_count", "features", "valid"),
    [
        ("N5", "direct", 1, False, True),
        ("N0", "direct", 1, False, False),
        ("N1", "inferred", 0, True, True),
        ("N1", "inferred", 1, True, False),
        ("N0", "inferred", 0, True, True),
        ("N2", "adjudicated", 0, True, False),
    ],
)
def test_method_level_boundaries(level: str, method: str, evidence_count: int, features: bool, valid: bool) -> None:
    document = load_json(EXAMPLE_DIR / "classification.valid-direct-conflict.json")
    document.update(level=level, method=method)
    document["evidence"] = document["evidence"][:evidence_count]
    if method == "direct" and document["evidence"]:
        document["evidence"][0]["assertedLevel"] = level
        document["policy"]["selectedEvidenceIds"] = [document["evidence"][0]["evidenceId"]]
    else:
        document["policy"].pop("selectedEvidenceIds", None)
    document["conflict"] = len({item["assertedLevel"] for item in document["evidence"]}) > 1
    if features:
        document["features"] = {"kanaOnly": False}
        if level == "N0":
            document["features"]["postN1DifficultySignals"] = ["test-signal"]
    else:
        document.pop("features", None)
    assert (errors("classification.schema.json", document) == []) is valid


def test_adjudication_is_isolated_pinned_and_bounded() -> None:
    document = load_json(EXAMPLE_DIR / "classification.valid-adjudicated.json")
    assert errors("classification.schema.json", document) == []
    document["adjudication"]["batchSize"] = 4
    assert errors("classification.schema.json", document)


def test_n0_requires_recorded_post_n1_evidence() -> None:
    document = load_json(EXAMPLE_DIR / "classification.valid-n0.json")
    document["features"].pop("postN1DifficultySignals")
    assert errors("classification.schema.json", document)
    document["features"]["postN1DifficultySignals"] = []
    assert errors("classification.schema.json", document)


def test_method_specific_provenance_cannot_leak_between_paths() -> None:
    direct = load_json(EXAMPLE_DIR / "classification.valid-direct-conflict.json")
    direct["policy"].pop("selectedEvidenceIds")
    assert errors("classification.schema.json", direct)

    inferred = load_json(EXAMPLE_DIR / "classification.valid-inferred.json")
    inferred["adjudication"] = load_json(EXAMPLE_DIR / "classification.valid-adjudicated.json")["adjudication"]
    assert errors("classification.schema.json", inferred)

    adjudicated = load_json(EXAMPLE_DIR / "classification.valid-adjudicated.json")
    adjudicated["policy"]["selectedEvidenceIds"] = []
    assert errors("classification.schema.json", adjudicated)


def test_adjudication_provenance_is_mandatory() -> None:
    document = load_json(EXAMPLE_DIR / "classification.valid-adjudicated.json")
    document.pop("adjudication")
    assert errors("classification.schema.json", document)


def test_semantic_cross_field_invariants() -> None:
    direct = load_json(EXAMPLE_DIR / "classification.valid-direct-conflict.json")
    direct["level"] = "N1"
    assert "/level: direct level must be asserted by evidence" in errors("classification.schema.json", direct)
    direct = load_json(EXAMPLE_DIR / "classification.valid-direct-conflict.json")
    direct["policy"]["selectedEvidenceIds"] = ["evidence:" + "0" * 64]
    assert any("unknown evidence ID" in item for item in errors("classification.schema.json", direct))

    manifest = load_json(EXAMPLE_DIR / "artifact-manifest.valid.json")
    manifest["counts"]["levels"]["N0"] = 0
    assert any("sum must equal" in item for item in errors("artifact-manifest.schema.json", manifest))


def test_canonical_json_is_stable(tmp_path: Path) -> None:
    from jlpt_levels.cli import main

    source = tmp_path / "source.json"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    source.write_text('{"日本語": 2, "a": [3, 1]}\n', encoding="utf-8")
    assert main(["canonicalize", str(source), str(first)]) == 0
    assert main(["canonicalize", str(first), str(second)]) == 0
    assert first.read_bytes() == second.read_bytes() == b'{"a":[3,1],"\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e":2}\n'


def test_lexeme_identity_is_exact_and_stable() -> None:
    from jlpt_levels.identity import lexeme_id

    assert lexeme_id("する", "する") == lexeme_id("する", "する")
    assert lexeme_id("する", "為る") != lexeme_id("する", "する")
    with pytest.raises(ValueError):
        lexeme_id("する", "")


def test_level_encoding_is_bijective() -> None:
    for value, level in enumerate(reversed(["N5", "N4", "N3", "N2", "N1", "N0"])):
        bank = [["語", "freq", {"reading": "ご", "frequency": {"value": value, "displayValue": level}}]]
        assert errors("yomitan-term-meta-bank.schema.json", bank) == []


def test_vendored_yomitan_schema_hashes_and_compatibility() -> None:
    expected = {}
    for line in (VENDORED_YOMITAN_DIR / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest
    assert expected
    for name, digest in expected.items():
        assert hashlib.sha256((VENDORED_YOMITAN_DIR / name).read_bytes()).hexdigest() == digest

    upstream = Draft7Validator(load_json(VENDORED_YOMITAN_DIR / "dictionary-term-meta-bank-v3-schema.json"))
    bank = load_json(EXAMPLE_DIR / "yomitan-term-meta-bank.valid.json")
    assert list(upstream.iter_errors(bank)) == []


def test_registry_fails_closed() -> None:
    registry = load_json(DATA_DIR / "config" / "sources.json")
    assert registry["sources"]
    for source in registry["sources"]:
        if source["license"]["status"] != "verified":
            assert source["license"]["redistributable"] is False
