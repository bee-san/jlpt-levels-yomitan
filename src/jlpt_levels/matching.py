from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .identity import canonical_json_bytes, lexeme_id


class MatchingError(ValueError):
    pass


_VOICED = {
    "か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
    "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
    "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど",
    "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ",
}


def _hiragana(text: str) -> str:
    result: list[str] = []
    for character in text:
        codepoint = ord(character)
        if 0x30A1 <= codepoint <= 0x30F6:
            result.append(chr(codepoint - 0x60))
        else:
            result.append(character)
    return "".join(result)


def normalize_text(text: str) -> str:
    """Apply only identity-preserving Japanese script normalization."""
    if not isinstance(text, str) or not text:
        raise MatchingError("matching text must be non-empty")
    source = _hiragana(unicodedata.normalize("NFC", text))
    result: list[str] = []
    for character in source:
        if character in {"々", "〻", "ゝ"}:
            if not result:
                result.append(character)
            else:
                result.append(result[-1])
        elif character == "ゞ":
            if not result or result[-1] not in _VOICED:
                result.append(character)
            else:
                result.append(_VOICED[result[-1]])
        else:
            result.append(character)
    return "".join(result)


def normalized_key(term: str, reading: str) -> tuple[str, str]:
    return normalize_text(term), normalize_text(reading)


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise MatchingError(f"{path}:{line_number}: invalid JSON") from error
            if not isinstance(record, dict):
                raise MatchingError(f"{path}:{line_number}: record must be an object")
            records.append(record)
    return records


def _validate_lexemes(lexemes: Iterable[dict]) -> list[dict]:
    checked: list[dict] = []
    ids: set[str] = set()
    for record in lexemes:
        try:
            term, reading = record["term"], record["reading"]
            record_id = record["lexemeId"]
            upstream = record["jitendex"]["upstreamIds"]
        except (KeyError, TypeError) as error:
            raise MatchingError("malformed lexeme record") from error
        if record_id != lexeme_id(term, reading):
            raise MatchingError(f"lexeme identity mismatch: {record_id}")
        if record_id in ids:
            raise MatchingError(f"duplicate lexeme identity: {record_id}")
        if not isinstance(upstream, list) or not upstream or any(not isinstance(item, str) for item in upstream):
            raise MatchingError(f"invalid upstream identities: {record_id}")
        ids.add(record_id)
        normalized_key(term, reading)
        checked.append(record)
    return checked


def match_records(lexemes: Iterable[dict], evidence: Iterable[dict]) -> tuple[list[dict], dict]:
    lexeme_rows = _validate_lexemes(lexemes)
    exact: dict[tuple[str, str], list[dict]] = defaultdict(list)
    normalized: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_sequence: dict[str, list[dict]] = defaultdict(list)
    for lexeme in lexeme_rows:
        exact[(lexeme["term"], lexeme["reading"])].append(lexeme)
        normalized[normalized_key(lexeme["term"], lexeme["reading"])].append(lexeme)
        for upstream_id in lexeme["jitendex"]["upstreamIds"]:
            by_sequence[upstream_id].append(lexeme)

    matched: list[dict] = []
    categories: dict[str, list[dict]] = {
        "exact-match": [], "normalized-match": [], "ambiguous": [], "unmatched": []
    }
    evidence_ids: set[str] = set()
    for item in evidence:
        try:
            evidence_id = item["evidenceId"]
            term, reading = item["term"], item["reading"]
        except (KeyError, TypeError) as error:
            raise MatchingError("malformed evidence record") from error
        if not isinstance(evidence_id, str) or evidence_id in evidence_ids:
            raise MatchingError(f"duplicate or invalid evidence identity: {evidence_id!r}")
        evidence_ids.add(evidence_id)
        try:
            key = normalized_key(term, reading)
        except MatchingError as error:
            categories["unmatched"].append({"evidenceId": evidence_id, "reason": str(error), "term": term, "reading": reading})
            continue

        seeds = exact.get((term, reading), [])
        category = "exact-match"
        if not seeds:
            seeds = normalized.get(key, [])
            category = "normalized-match"
        if not seeds:
            categories["unmatched"].append({"evidenceId": evidence_id, "reason": "no exact or conservative normalized lexeme", "term": term, "reading": reading})
            continue

        components = {tuple(seed["jitendex"]["upstreamIds"]) for seed in seeds}
        all_sequences = {sequence for seed in seeds for sequence in seed["jitendex"]["upstreamIds"]}
        if len(components) > 1 and not _connected(seeds):
            categories["ambiguous"].append({
                "candidateLexemeIds": sorted(seed["lexemeId"] for seed in seeds),
                "evidenceId": evidence_id,
                "reason": "normalized form reaches unrelated Jitendex entries",
                "term": term,
                "reading": reading,
            })
            continue

        targets: dict[str, dict] = {seed["lexemeId"]: seed for seed in seeds}
        for sequence in all_sequences:
            for candidate in by_sequence[sequence]:
                if normalize_text(candidate["reading"]) == key[1]:
                    targets[candidate["lexemeId"]] = candidate
        result = {
            "evidenceId": evidence_id,
            "matchKind": category,
            "targetLexemeIds": sorted(targets),
        }
        matched.append(result)
        categories[category].append(result)

    matched.sort(key=lambda item: item["evidenceId"])
    report = {
        "schemaVersion": 1,
        "counts": {name: len(categories[name]) for name in categories},
        "exactMatch": sorted(categories["exact-match"], key=lambda item: item["evidenceId"]),
        "normalizedMatch": sorted(categories["normalized-match"], key=lambda item: item["evidenceId"]),
        "ambiguous": sorted(categories["ambiguous"], key=lambda item: item["evidenceId"]),
        "unmatched": sorted(categories["unmatched"], key=lambda item: item["evidenceId"]),
    }
    if sum(report["counts"].values()) != len(evidence_ids):
        raise AssertionError("matching report lost evidence records")
    return matched, report


def _connected(records: list[dict]) -> bool:
    remaining = list(records)
    seen_sequences = set(remaining.pop()["jitendex"]["upstreamIds"])
    changed = True
    while changed:
        changed = False
        for record in remaining[:]:
            sequences = set(record["jitendex"]["upstreamIds"])
            if seen_sequences & sequences:
                seen_sequences.update(sequences)
                remaining.remove(record)
                changed = True
    return not remaining


def match_files(lexemes_path: Path, evidence_path: Path, matches_path: Path, report_path: Path) -> dict:
    matches, report = match_records(_read_jsonl(lexemes_path), _read_jsonl(evidence_path))
    matches_path.parent.mkdir(parents=True, exist_ok=True)
    with matches_path.open("wb") as output:
        for record in matches:
            output.write(canonical_json_bytes(record))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_json_bytes(report))
    return report
