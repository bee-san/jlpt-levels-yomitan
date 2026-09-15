from __future__ import annotations

import html
import json
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import AcquisitionError, CachedFetcher, canonical_bytes, sha256_bytes, write_jsonl

_LEVELS = ("N5", "N4", "N3", "N2", "N1")
_LINK = re.compile(r"^\{\{l\|ja\|([^{}|]+)(?:\|[^{}]*)?\}\}$")
_COUNT = re.compile(r"There (?:a total|are a total) of ([0-9,]+) words\.")


@dataclass(frozen=True)
class PageSpec:
    level: str
    title: str
    revision: int


class WiktionaryJlptAdapter:
    source_id = "enwiktionary-jlpt-appendices"

    def __init__(self, config: dict[str, Any], fetcher: CachedFetcher) -> None:
        self.config = config
        self.fetcher = fetcher
        self.page_configs = config["pages"]
        self.pages = tuple(PageSpec(level, item["title"], item["revision"]) for level, item in sorted(self.page_configs.items(), reverse=True))
        if tuple(page.level for page in self.pages) != _LEVELS:
            raise ValueError("pages must define exactly N5 through N1")
        if len({page.title for page in self.pages}) != 5 or len({page.revision for page in self.pages}) != 5:
            raise ValueError("page titles and revisions must be unique")

    def api_url(self) -> str:
        query = urllib.parse.urlencode({
            "action": "query", "format": "json", "formatversion": "2", "prop": "revisions",
            "rvprop": "ids|timestamp|content", "rvslots": "main",
            "revids": "|".join(str(page.revision) for page in self.pages),
        })
        return self.config["apiUrl"] + "?" + query

    def acquire(self, *, offline: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raw, cache_hit = self.fetcher.get(self.api_url(), max_bytes=self.config["maxBytes"], offline=offline)
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AcquisitionError("Wiktionary response is not valid UTF-8 JSON") from error
        records, snapshots = self.parse(payload)
        report = self.report(records, snapshots)
        report["acquisition"] = {"cacheHit": cache_hit, "responseSha256": sha256_bytes(raw)}
        return records, report

    def parse(self, payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("query", {}).get("pages"), list):
            raise AcquisitionError("missing query.pages")
        expected = {page.revision: page for page in self.pages}
        seen: set[int] = set()
        records: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        for result in payload["query"]["pages"]:
            revisions = result.get("revisions") if isinstance(result, dict) else None
            if not isinstance(revisions, list) or len(revisions) != 1:
                raise AcquisitionError("each page must have exactly one revision")
            revision = revisions[0]
            revision_id = revision.get("revid")
            if revision_id not in expected or revision_id in seen:
                raise AcquisitionError("unexpected or duplicate revision")
            spec = expected[revision_id]
            if result.get("title") != spec.title:
                raise AcquisitionError("revision title does not match pinned title")
            timestamp = revision.get("timestamp")
            content = revision.get("slots", {}).get("main", {}).get("content")
            if not isinstance(timestamp, str) or not isinstance(content, str):
                raise AcquisitionError("revision metadata/content is incomplete")
            snapshot_sha = sha256_bytes(content.encode("utf-8"))
            if snapshot_sha != self.page_configs[spec.level]["sha256"]:
                raise AcquisitionError(f"{spec.title}: snapshot SHA-256 does not match registry")
            page_records = self.parse_wikitext(content, spec, timestamp, snapshot_sha)
            records.extend(page_records)
            snapshots.append({"level": spec.level, "revision": revision_id, "sha256": snapshot_sha, "timestamp": timestamp, "title": spec.title})
            seen.add(revision_id)
        if seen != set(expected):
            raise AcquisitionError("response omitted pinned revisions")
        records.sort(key=lambda item: (item["term"], item["reading"], item["assertedLevel"], item["sourceRecord"]))
        snapshots.sort(key=lambda item: item["level"], reverse=True)
        return records, snapshots

    def parse_wikitext(self, text: str, spec: PageSpec, timestamp: str, snapshot_sha: str) -> list[dict[str, Any]]:
        claimed = _COUNT.search(text)
        if claimed is None:
            raise AcquisitionError(f"{spec.title}: missing stated row count")
        expected_count = int(claimed.group(1).replace(",", ""))
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.startswith("|") or line.startswith(("|-", "{|", "|}")):
                continue
            cells = [cell.strip() for cell in line[1:].split("||")]
            if len(cells) != 4:
                raise AcquisitionError(f"{spec.title}:{line_number}: expected four table cells")
            if cells[0] == "Kanji" or cells[0].startswith("-"):
                continue
            term = self._link_value(cells[0]) if cells[0] else self._link_value(cells[1])
            reading = self._link_value(cells[1])
            if not term or not reading:
                raise AcquisitionError(f"{spec.title}:{line_number}: invalid term or reading template")
            source_record = f"{spec.title}#revision-{spec.revision}-row-{line_number}"
            identity = {"assertedLevel": spec.level, "reading": reading, "sourceId": self.source_id, "sourceRecord": source_record, "term": term}
            records.append({
                **identity,
                "capturedAt": timestamp,
                "evidenceId": "evidence:" + sha256_bytes(canonical_bytes(identity).rstrip(b"\n")),
                "license": self.config["license"]["spdx"],
                "snapshotSha256": snapshot_sha,
                "sourceUrl": f"https://en.wiktionary.org/w/index.php?title={urllib.parse.quote(spec.title)}&oldid={spec.revision}",
            })
        if len(records) != expected_count:
            raise AcquisitionError(f"{spec.title}: stated {expected_count} rows but parsed {len(records)}")
        return records

    @staticmethod
    def _link_value(cell: str) -> str:
        match = _LINK.fullmatch(cell)
        return html.unescape(match.group(1)).strip() if match else ""

    def report(self, records: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        levels = Counter(record["assertedLevel"] for record in records)
        assertions: dict[tuple[str, str], set[str]] = defaultdict(set)
        for record in records:
            assertions[(record["term"], record["reading"])].add(record["assertedLevel"])
        conflicts = [{"term": term, "reading": reading, "levels": sorted(found, reverse=True)} for (term, reading), found in sorted(assertions.items()) if len(found) > 1]
        return {
            "conflictCount": len(conflicts), "conflictSamples": conflicts[:20],
            "countsByLevel": {level: levels[level] for level in _LEVELS},
            "recordCount": len(records), "snapshots": snapshots, "sourceId": self.source_id,
            "uniqueLexemeCount": len(assertions),
        }

    def run(self, output: Path, report_path: Path, *, offline: bool = False) -> None:
        records, report = self.acquire(offline=offline)
        write_jsonl(output, records)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(canonical_bytes(report))
