from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from jlpt_levels.contracts import DATA_DIR, errors, load_json
from jlpt_levels.sources.common import AcquisitionError, CachedFetcher, sha256_bytes
from jlpt_levels.sources.wiktionary import WiktionaryJlptAdapter

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = load_json(DATA_DIR / "config" / "vocabulary-sources.json")["sources"][0]


def adapter(tmp_path: Path, fixture: dict | None = None) -> WiktionaryJlptAdapter:
    config = copy.deepcopy(CONFIG)
    payload = fixture if fixture is not None else load_json(FIXTURES / "wiktionary-response.json")
    by_revision = {page["revisions"][0]["revid"]: page["revisions"][0]["slots"]["main"]["content"] for page in payload["query"]["pages"]}
    for page in config["pages"].values():
        page["sha256"] = sha256_bytes(by_revision[page["revision"]].encode())
    return WiktionaryJlptAdapter(config, CachedFetcher(tmp_path, "JLPTLevelsYomitan/Test (test@example.invalid)", sleep=lambda _: None))


def test_fixture_normalizes_all_levels_without_collapsing_identity(tmp_path: Path) -> None:
    records, snapshots = adapter(tmp_path).parse(load_json(FIXTURES / "wiktionary-response.json"))
    assert len(records) == len(snapshots) == 5
    assert {item["assertedLevel"] for item in records} == {"N5", "N4", "N3", "N2", "N1"}
    assert all(errors("vocabulary-evidence.schema.json", item) == [] for item in records)
    assert len({item["evidenceId"] for item in records}) == 5
    assert all(item["term"] and item["reading"] for item in records)
    assert all("Meaning" not in item and "frequency" not in item for item in records)


def test_fixture_output_and_report_are_deterministic(tmp_path: Path) -> None:
    parsed = load_json(FIXTURES / "wiktionary-response.json")
    source = adapter(tmp_path)
    first, snapshots = source.parse(parsed)
    second, snapshots_again = source.parse(copy.deepcopy(parsed))
    assert first == second
    assert snapshots == snapshots_again
    report = source.report(first, snapshots)
    assert report["countsByLevel"] == {"N5": 1, "N4": 1, "N3": 1, "N2": 1, "N1": 1}
    assert report["recordCount"] == report["uniqueLexemeCount"] == 5
    assert report["conflictCount"] == 0


@pytest.mark.parametrize("mutation", ["missing-page", "wrong-title", "bad-row", "count-drift", "duplicate-revision", "snapshot-drift"])
def test_malformed_inputs_fail_closed(tmp_path: Path, mutation: str) -> None:
    payload = load_json(FIXTURES / "wiktionary-response.json")
    if mutation == "missing-page":
        payload["query"]["pages"].pop()
    elif mutation == "wrong-title":
        payload["query"]["pages"][0]["title"] = "Appendix:JLPT/Wrong"
    elif mutation == "bad-row":
        revision = payload["query"]["pages"][0]["revisions"][0]
        revision["slots"]["main"]["content"] = revision["slots"]["main"]["content"].replace(" || ", " | ", 1)
    elif mutation == "count-drift":
        revision = payload["query"]["pages"][0]["revisions"][0]
        revision["slots"]["main"]["content"] = revision["slots"]["main"]["content"].replace("total of 1", "total of 2")
    elif mutation == "duplicate-revision":
        payload["query"]["pages"][1]["revisions"][0]["revid"] = payload["query"]["pages"][0]["revisions"][0]["revid"]
    else:
        revision = payload["query"]["pages"][0]["revisions"][0]
        revision["slots"]["main"]["content"] += "\n"
    with pytest.raises(AcquisitionError):
        adapter(tmp_path).parse(payload)


def test_kana_only_rows_repeat_reading_as_term(tmp_path: Path) -> None:
    payload = load_json(FIXTURES / "wiktionary-response.json")
    revision = payload["query"]["pages"][0]["revisions"][0]
    content = revision["slots"]["main"]["content"]
    revision["slots"]["main"]["content"] = content.replace(next(line for line in content.splitlines() if line.startswith("|{{l|ja|")), "| || {{l|ja|かな}} || meaning || N/A")
    records, _ = adapter(tmp_path, payload).parse(payload)
    assert any(item["term"] == item["reading"] == "かな" for item in records)


def test_conflicts_are_counted_and_sampled(tmp_path: Path) -> None:
    payload = load_json(FIXTURES / "wiktionary-response.json")
    pages = payload["query"]["pages"]
    first_row = next(line for line in pages[0]["revisions"][0]["slots"]["main"]["content"].splitlines() if line.startswith("|{{l|ja|"))
    content = pages[1]["revisions"][0]["slots"]["main"]["content"]
    old_row = next(line for line in content.splitlines() if line.startswith("|{{l|ja|"))
    pages[1]["revisions"][0]["slots"]["main"]["content"] = content.replace(old_row, first_row)
    source = adapter(tmp_path, payload)
    records, snapshots = source.parse(payload)
    report = source.report(records, snapshots)
    assert report["conflictCount"] == 1
    assert report["conflictSamples"][0]["levels"] == ["N5", "N4"]


def test_cached_fetcher_reuses_exact_bytes_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://example.invalid/source"
    cache = tmp_path / (sha256_bytes(url.encode()) + ".bin")
    cache.write_bytes(b"exact bytes")
    fetcher = CachedFetcher(tmp_path, "JLPTLevelsYomitan/Test (test@example.invalid)")
    assert fetcher.get(url, max_bytes=100, offline=True) == (b"exact bytes", True)
    cache.write_bytes(b"x" * 101)
    with pytest.raises(AcquisitionError, match="exceeds"):
        fetcher.get(url, max_bytes=100, offline=True)
    cache.unlink()
    with pytest.raises(AcquisitionError, match="cache miss"):
        fetcher.get(url, max_bytes=100, offline=True)


def test_registry_is_explicitly_licensed_and_every_adapter_is_implemented() -> None:
    registry = load_json(DATA_DIR / "config" / "vocabulary-sources.json")
    assert registry["sources"]
    assert {source["adapter"] for source in registry["sources"]} == {"wiktionary-jlpt"}
    for source in registry["sources"]:
        assert source["license"]["redistributable"] is True
        assert source["license"]["spdx"] == "CC-BY-SA-4.0"
        assert source["officialJlpt"] is False
