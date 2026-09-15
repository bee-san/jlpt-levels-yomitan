from __future__ import annotations

import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

import pytest

from jlpt_levels.jitendex import JitendexError, acquire, build_census, load_lock

LOCK = Path("data/sources/jitendex.lock.json")
FIXTURE = Path("tests/fixtures/jitendex/adversarial.json")


def _fixture_zip(path: Path, rows: list[list], *, bank_names: tuple[str, ...] = ("term_bank_1.json",)) -> tuple[Path, Path]:
    attribution = "test attribution"
    index = {"title": "Fixture", "revision": "fixture.1", "format": 3, "attribution": attribution}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.json", json.dumps(index, ensure_ascii=False))
        for name in bank_names:
            archive.writestr(name, json.dumps(rows, ensure_ascii=False))
        archive.writestr("tag_bank_1.json", "[]")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lock = {
        "schemaVersion": 1,
        "release": {"tag": "fixture.1"},
        "artifact": {
            "name": path.name,
            "url": "https://github.com/example/repo/releases/download/fixture.1/jitendex.zip",
            "bytes": path.stat().st_size,
            "sha256": digest,
            "githubDigest": f"sha256:{digest}",
        },
        "dictionary": {"title": "Fixture", "revision": "fixture.1", "format": 3},
        "license": {
            "status": "verified",
            "redistributable": True,
            "archiveAttributionSha256": hashlib.sha256(attribution.encode()).hexdigest(),
        },
    }
    lock_path = path.with_suffix(".lock.json")
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return path, lock_path


def test_production_lock_is_immutable_and_affirmatively_licensed() -> None:
    lock = load_lock(LOCK)
    assert lock["release"]["immutable"] is True
    assert lock["artifact"]["githubDigest"] == f"sha256:{lock['artifact']['sha256']}"
    assert lock["artifact"]["url"].endswith(
        f"/releases/download/{lock['release']['tag']}/{lock['artifact']['name']}"
    )
    assert lock["license"]["redistributable"] is True


def test_acquire_uses_verified_content_addressed_cache(tmp_path: Path) -> None:
    rows = [json.loads(FIXTURE.read_text())["cases"][0]["row"]]
    source, lock_path = _fixture_zip(tmp_path / "source.zip", rows)
    lock = load_lock(lock_path)
    lock["artifact"]["url"] = source.as_uri()
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    cached = acquire(lock_path, tmp_path / "cache")
    assert cached.name == f"{lock['artifact']['sha256']}.zip"
    assert cached.read_bytes() == source.read_bytes()
    cached.write_bytes(b"corrupt")
    with pytest.raises(JitendexError, match="size differs"):
        acquire(lock_path, tmp_path / "cache")


def test_acquire_accepts_only_github_release_storage_redirects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [json.loads(FIXTURE.read_text())["cases"][0]["row"]]
    source, lock_path = _fixture_zip(tmp_path / "source.zip", rows)

    class FileResponse:
        def __init__(self, url: str) -> None:
            self.url = url
            self.stream = None

        def __enter__(self):
            self.stream = source.open("rb")
            return self

        def __exit__(self, *args):
            assert self.stream is not None
            self.stream.close()

        def read(self, size: int = -1) -> bytes:
            assert self.stream is not None
            return self.stream.read(size)

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: FileResponse(
        "https://release-assets.githubusercontent.com/github-production-release-asset/1/object?token=temporary"
    ))
    assert acquire(lock_path, tmp_path / "accepted").read_bytes() == source.read_bytes()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: FileResponse(
        "https://example.invalid/replaced.zip"
    ))
    with pytest.raises(JitendexError, match="outside GitHub release asset storage"):
        acquire(lock_path, tmp_path / "rejected")


def test_adversarial_census_preserves_variants_readings_and_duplicate_provenance(tmp_path: Path) -> None:
    rows = [case["row"] for case in json.loads(FIXTURE.read_text())["cases"]]
    archive, lock = _fixture_zip(tmp_path / "fixture.zip", rows)
    lexemes = tmp_path / "lexemes.jsonl"
    census_path = tmp_path / "census.json"
    census = build_census(archive, lock, lexemes, census_path)
    records = [json.loads(line) for line in lexemes.read_text().splitlines()]
    assert census["counts"] == {
        "termBanks": 1,
        "rawRows": 5,
        "normalizedLexemes": 4,
        "duplicateRowsCollapsed": 1,
        "sourceEmptyReadingsNormalizedToTerm": 2,
        "termEqualsReading": 1,
        "distinctAbsoluteSequences": 3,
        "multiplicity": {"1": 3, "2": 1},
    }
    assert {(record["term"], record["reading"]) for record in records} == {
        ("する", "する"), ("爲る", "する"), ("開く", "あく"), ("開く", "ひらく")
    }
    suru = next(record for record in records if record["term"] == "する")
    assert len(suru["jitendex"]["occurrences"]) == 2
    assert suru["jitendex"]["upstreamIds"] == [
        "jitendex:sequence:1157170", "jitendex:sequence:9999999"
    ]
    assert json.loads(census_path.read_text()) == census


def test_format_drift_and_missing_banks_fail_closed(tmp_path: Path) -> None:
    row = json.loads(FIXTURE.read_text())["cases"][0]["row"]
    archive, lock = _fixture_zip(tmp_path / "gap.zip", [row], bank_names=("term_bank_2.json",))
    with pytest.raises(JitendexError, match="not contiguous"):
        build_census(archive, lock, tmp_path / "a.jsonl", tmp_path / "a.json")

    malformed = row[:-1]
    archive, lock = _fixture_zip(tmp_path / "drift.zip", [malformed])
    with pytest.raises(JitendexError, match="not a v3 term row"):
        build_census(archive, lock, tmp_path / "b.jsonl", tmp_path / "b.json")


def test_census_is_byte_deterministic(tmp_path: Path) -> None:
    rows = [case["row"] for case in json.loads(FIXTURE.read_text())["cases"]]
    archive, lock = _fixture_zip(tmp_path / "fixture.zip", rows)
    first_lexemes, first_census = tmp_path / "first.jsonl", tmp_path / "first.json"
    second_lexemes, second_census = tmp_path / "second.jsonl", tmp_path / "second.json"
    build_census(archive, lock, first_lexemes, first_census)
    build_census(archive, lock, second_lexemes, second_census)
    assert first_lexemes.read_bytes() == second_lexemes.read_bytes()
    assert first_census.read_bytes() == second_census.read_bytes()
