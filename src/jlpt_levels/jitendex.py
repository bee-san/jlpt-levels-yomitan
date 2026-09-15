from __future__ import annotations

import hashlib
import json
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator

from .identity import canonical_json_bytes, lexeme_id

BANK_RE = re.compile(r"term_bank_([1-9][0-9]*)\.json")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
MAX_MEMBERS = 1000
MAX_EXPANDED_BYTES = 2_000_000_000
MAX_MEMBER_BYTES = 100_000_000


class JitendexError(ValueError):
    pass


def load_lock(path: Path) -> dict:
    lock = json.loads(path.read_text(encoding="utf-8"))
    required = {"schemaVersion", "release", "artifact", "dictionary", "license"}
    if set(lock) != required or lock["schemaVersion"] != 1:
        raise JitendexError("unsupported Jitendex lock shape")
    artifact = lock["artifact"]
    if not SHA256_RE.fullmatch(artifact.get("sha256", "")):
        raise JitendexError("invalid pinned artifact SHA-256")
    if not isinstance(artifact.get("bytes"), int) or artifact["bytes"] <= 0:
        raise JitendexError("invalid pinned artifact size")
    url = artifact.get("url", "")
    if url.startswith("https://github.com/"):
        if "/releases/download/" not in url or "/latest/" in url:
            raise JitendexError("artifact URL is not immutable")
    elif not url.startswith("file://"):
        raise JitendexError("artifact URL must be an immutable GitHub HTTPS URL")
    if lock["license"].get("redistributable") is not True:
        raise JitendexError("Jitendex redistribution is not affirmatively verified")
    return lock


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def acquire(lock_path: Path, cache_dir: Path) -> Path:
    lock = load_lock(lock_path)
    artifact = lock["artifact"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{artifact['sha256']}.zip"
    if target.exists():
        _verify_file(target, artifact)
        return target
    partial = target.with_suffix(".zip.partial")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(artifact["url"], headers={"User-Agent": "jlpt-levels-yomitan/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            if artifact["url"].startswith("https://") and response.url != artifact["url"]:
                redirected_host = urllib.parse.urlsplit(response.url).hostname
                if redirected_host not in {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
                    raise JitendexError("download redirected outside GitHub release asset storage")
            shutil.copyfileobj(response, output, length=1024 * 1024)
            if output.tell() > artifact["bytes"]:
                raise JitendexError("download exceeds pinned size")
        _verify_file(partial, artifact)
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return target


def _verify_file(path: Path, artifact: dict) -> None:
    if path.stat().st_size != artifact["bytes"]:
        raise JitendexError("artifact size differs from lock")
    if sha256_file(path) != artifact["sha256"]:
        raise JitendexError("artifact SHA-256 differs from lock")


def _archive_inventory(archive: zipfile.ZipFile) -> list[str]:
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise JitendexError("archive has too many members")
    names: list[str] = []
    expanded = 0
    for info in infos:
        path = PurePosixPath(info.filename)
        if info.filename in names:
            raise JitendexError(f"duplicate archive member: {info.filename}")
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise JitendexError(f"unsafe archive member: {info.filename}")
        if info.flag_bits & 1:
            raise JitendexError(f"encrypted archive member: {info.filename}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise JitendexError(f"oversized archive member: {info.filename}")
        expanded += info.file_size
        names.append(info.filename)
    if expanded > MAX_EXPANDED_BYTES:
        raise JitendexError("archive expands beyond safety limit")
    return names


def _banks(names: list[str]) -> list[str]:
    numbered = sorted((int(match.group(1)), name) for name in names if (match := BANK_RE.fullmatch(name)))
    if not numbered:
        raise JitendexError("archive contains no term banks")
    expected = list(range(1, numbered[-1][0] + 1))
    actual = [number for number, _ in numbered]
    if actual != expected:
        raise JitendexError("term bank numbering is not contiguous from 1")
    suspicious = [name for name in names if name.startswith("term_bank_") and not BANK_RE.fullmatch(name)]
    if suspicious:
        raise JitendexError(f"unrecognized term bank names: {suspicious[:3]}")
    return [name for _, name in numbered]


def _json_member(archive: zipfile.ZipFile, name: str) -> object:
    try:
        return json.loads(archive.read(name).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JitendexError(f"invalid JSON member {name}: {error}") from error


def _validate_index(index: object, lock: dict) -> dict:
    if not isinstance(index, dict):
        raise JitendexError("index.json must be an object")
    expected = lock["dictionary"]
    for field in ("title", "revision", "format"):
        if index.get(field) != expected[field]:
            raise JitendexError(f"index.json {field} differs from lock")
    attribution = index.get("attribution")
    if not isinstance(attribution, str):
        raise JitendexError("index.json lacks attribution")
    digest = hashlib.sha256(attribution.encode("utf-8")).hexdigest()
    if digest != lock["license"]["archiveAttributionSha256"]:
        raise JitendexError("archive attribution differs from reviewed text")
    return index


def iter_rows(path: Path, lock: dict) -> Iterator[tuple[str, int, list]]:
    _verify_file(path, lock["artifact"])
    with zipfile.ZipFile(path) as archive:
        names = _archive_inventory(archive)
        _validate_index(_json_member(archive, "index.json"), lock)
        for bank in _banks(names):
            rows = _json_member(archive, bank)
            if not isinstance(rows, list):
                raise JitendexError(f"{bank} must contain an array")
            for row_number, row in enumerate(rows):
                if not isinstance(row, list) or len(row) != 8:
                    raise JitendexError(f"{bank} row {row_number} is not a v3 term row")
                term, reading, sequence = row[0], row[1], row[6]
                if not isinstance(term, str) or not term:
                    raise JitendexError(f"{bank} row {row_number} has no term")
                if not isinstance(reading, str):
                    raise JitendexError(f"{bank} row {row_number} reading is not text")
                if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence == 0:
                    raise JitendexError(f"{bank} row {row_number} has invalid sequence")
                yield bank, row_number, row


def build_census(archive_path: Path, lock_path: Path, lexemes_path: Path, census_path: Path) -> dict:
    lock = load_lock(lock_path)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    raw_rows = 0
    empty_readings = 0
    bank_counts: Counter[str] = Counter()
    sequence_ids: set[int] = set()
    for bank, row_number, row in iter_rows(archive_path, lock):
        raw_rows += 1
        bank_counts[bank] += 1
        term, source_reading, sequence = row[0], row[1], row[6]
        reading = source_reading or term
        empty_readings += source_reading == ""
        sequence_ids.add(abs(sequence))
        grouped[(term, reading)].append({"bank": bank, "row": row_number, "sequence": sequence})
    lexemes_path.parent.mkdir(parents=True, exist_ok=True)
    multiplicity: Counter[int] = Counter()
    kana_only = 0
    with lexemes_path.open("wb") as output:
        for term, reading in sorted(grouped, key=lambda key: (key[0], key[1])):
            occurrences = sorted(
                grouped[(term, reading)],
                key=lambda item: (int(item["bank"][10:-5]), item["row"]),
            )
            multiplicity[len(occurrences)] += 1
            kana_only += term == reading
            upstream_ids = sorted({f"jitendex:sequence:{abs(item['sequence'])}" for item in occurrences})
            record = {
                "jitendex": {
                    "dictionarySha256": lock["artifact"]["sha256"],
                    "occurrences": occurrences,
                    "upstreamIds": upstream_ids,
                },
                "lexemeId": lexeme_id(term, reading),
                "reading": reading,
                "term": term,
            }
            output.write(canonical_json_bytes(record))
    census = {
        "schemaVersion": 1,
        "source": {
            "artifactSha256": lock["artifact"]["sha256"],
            "release": lock["release"]["tag"],
            "revision": lock["dictionary"]["revision"],
        },
        "counts": {
            "termBanks": len(bank_counts),
            "rawRows": raw_rows,
            "normalizedLexemes": len(grouped),
            "duplicateRowsCollapsed": raw_rows - len(grouped),
            "sourceEmptyReadingsNormalizedToTerm": empty_readings,
            "termEqualsReading": kana_only,
            "distinctAbsoluteSequences": len(sequence_ids),
            "multiplicity": {str(key): multiplicity[key] for key in sorted(multiplicity)},
        },
        "normalization": {
            "key": ["term", "reading"],
            "emptyReading": "term",
            "duplicates": "collapsed-with-all-occurrences-preserved",
            "sequenceIdentity": "absolute signed sequence",
        },
        "archiveMembers": {
            "termBankPattern": "term_bank_[1-9][0-9]*.json",
            "termBanksIncluded": len(bank_counts),
            "nonTermBanksExcludedFromLexemes": len(_archive_member_names(archive_path)) - len(bank_counts),
        },
        "bankRows": {
            key: bank_counts[key]
            for key in sorted(bank_counts, key=lambda name: int(name[10:-5]))
        },
        "lexemesSha256": sha256_file(lexemes_path),
    }
    census_path.parent.mkdir(parents=True, exist_ok=True)
    census_path.write_bytes(canonical_json_bytes(census))
    return census


def _archive_member_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return _archive_inventory(archive)
