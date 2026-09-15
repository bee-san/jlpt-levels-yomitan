from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import errors
from .identity import canonical_json_bytes

LEVEL_VALUE = {"N5": 1, "N4": 2, "N3": 3, "N2": 4, "N1": 5, "N0": 6}
LEVELS = tuple(LEVEL_VALUE)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
TITLE = "JLPT Levels for Jitendex"


class PackagingError(ValueError):
    pass


@dataclass(frozen=True)
class PackageResult:
    zip_path: Path
    manifest_path: Path
    sha256s_path: Path
    zip_sha256: str


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PackagingError(f"cannot read JSON from {path}: {error}") from error


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            for number, raw in enumerate(stream, 1):
                if not raw.strip():
                    raise PackagingError(f"{path}:{number}: blank JSONL row")
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise PackagingError(f"{path}:{number}: expected an object")
                rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PackagingError(f"cannot read JSONL from {path}: {error}") from error
    return rows


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_source_licenses(registries: list[dict[str, Any]]) -> tuple[str, set[str]]:
    attributions: list[str] = []
    source_ids: set[str] = set()
    for registry in registries:
        sources = registry.get("sources")
        if not isinstance(sources, list) or not sources:
            raise PackagingError("every source registry must contain at least one source")
        for source in sources:
            if not isinstance(source, dict):
                raise PackagingError("source registry source must be an object")
            source_id = source.get("id")
            if not isinstance(source_id, str) or not source_id:
                raise PackagingError("source registry source is missing an ID")
            if source_id in source_ids:
                raise PackagingError(f"duplicate registered source {source_id!r}")
            source_ids.add(source_id)
            license_info = source.get("license")
            if not isinstance(license_info, dict) or license_info.get("redistributable") is not True:
                raise PackagingError(f"source {source_id!r} is not cleared for redistribution")
            attribution = license_info.get("attribution")
            if isinstance(attribution, str) and attribution.strip():
                attributions.append(attribution.strip())
    return "\n".join(attributions), source_ids


def _artifact_digest(lock: dict[str, Any]) -> str:
    artifact = lock.get("artifact")
    digest = artifact.get("sha256") if isinstance(artifact, dict) else None
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise PackagingError("Jitendex lock is missing a canonical artifact SHA-256")
    return digest


def _validated_rows(
    lexemes_path: Path,
    classifications_path: Path,
    expected_jitendex_sha256: str,
    registered_evidence_sources: set[str],
) -> tuple[list[list[Any]], Counter[str], int]:
    lexemes = _load_jsonl(lexemes_path)
    classifications = _load_jsonl(classifications_path)
    by_id: dict[str, dict[str, Any]] = {}
    for classification in classifications:
        found = errors("classification.schema.json", classification)
        if found:
            raise PackagingError("invalid classification: " + "; ".join(found))
        lexeme_id = classification["lexemeId"]
        for evidence in classification["evidence"]:
            source_id = evidence["sourceId"]
            if source_id not in registered_evidence_sources:
                raise PackagingError(f"classification evidence references unregistered source {source_id!r}")
        if lexeme_id in by_id:
            raise PackagingError(f"duplicate classification for {lexeme_id}")
        by_id[lexeme_id] = classification

    seen: set[str] = set()
    rows: list[list[Any]] = []
    level_counts: Counter[str] = Counter()
    conflicts = 0
    for lexeme in lexemes:
        found = errors("lexeme.schema.json", lexeme)
        if found:
            raise PackagingError("invalid lexeme: " + "; ".join(found))
        lexeme_id = lexeme["lexemeId"]
        if lexeme_id in seen:
            raise PackagingError(f"duplicate inventory lexeme {lexeme_id}")
        seen.add(lexeme_id)
        source_sha = lexeme["jitendex"]["dictionarySha256"]
        if source_sha != expected_jitendex_sha256:
            raise PackagingError(f"lexeme {lexeme_id} does not match the locked Jitendex artifact")
        classification = by_id.get(lexeme_id)
        if classification is None:
            raise PackagingError(f"missing classification for {lexeme_id}")
        level = classification["level"]
        rows.append([
            lexeme["term"],
            "freq",
            {
                "reading": lexeme["reading"],
                "frequency": {"value": LEVEL_VALUE[level], "displayValue": level},
            },
        ])
        level_counts[level] += 1
        conflicts += int(classification["conflict"])
    extra = sorted(set(by_id) - seen)
    if extra:
        raise PackagingError(f"classifications contain {len(extra)} lexeme IDs absent from the inventory")
    if not rows:
        raise PackagingError("refusing to package an empty lexeme inventory")
    rows.sort(key=lambda row: (row[0], row[2]["reading"]))
    return rows, level_counts, conflicts


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in members:
            archive.writestr(_zip_info(name), payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return result.getvalue()


def build_dictionary(
    lexemes_path: Path,
    classifications_path: Path,
    source_registry_path: Path,
    vocabulary_registry_path: Path,
    jitendex_lock_path: Path,
    output_dir: Path,
    *,
    revision: str,
    created_at: str,
    bank_size: int = 10_000,
) -> PackageResult:
    if bank_size < 1:
        raise PackagingError("bank size must be positive")
    registry = _load_json(source_registry_path)
    vocabulary_registry = _load_json(vocabulary_registry_path)
    lock = _load_json(jitendex_lock_path)
    if not isinstance(registry, dict) or not isinstance(vocabulary_registry, dict) or not isinstance(lock, dict):
        raise PackagingError("source registries and Jitendex lock must be objects")
    attribution, registered_sources = _validate_source_licenses([registry, vocabulary_registry])
    jitendex_digest = _artifact_digest(lock)
    jitendex_sources = [source for source in registry["sources"] if source.get("id") == "jitendex"]
    registry_digest = jitendex_sources[0].get("acquisition", {}).get("sha256") if len(jitendex_sources) == 1 else None
    if registry_digest != jitendex_digest:
        raise PackagingError("Jitendex source registry and artifact lock SHA-256 do not agree")
    rows, level_counts, conflicts = _validated_rows(
        lexemes_path, classifications_path, jitendex_digest, registered_sources
    )

    index = {
        "title": TITLE,
        "revision": revision,
        "format": 3,
        "sequenced": False,
        "frequencyMode": "rank-based",
        "author": "JLPT Levels for Yomitan contributors",
        "description": "Lexeme-specific JLPT difficulty bands for Jitendex. N0 is harder than N1; it never means unknown or unassigned.",
        "attribution": attribution,
        "sourceLanguage": "ja",
    }
    members: list[tuple[str, bytes]] = [("index.json", canonical_json_bytes(index))]
    for number, start in enumerate(range(0, len(rows), bank_size), 1):
        name = f"term_meta_bank_{number}.json"
        members.append((name, canonical_json_bytes(rows[start:start + bank_size])))

    zip_payload = _zip_bytes(members)
    files = [
        {"path": name, "sha256": _sha256(payload), "bytes": len(payload)}
        for name, payload in members
    ]
    manifest = {
        "schemaVersion": 1,
        "revision": revision,
        "createdAt": created_at,
        "sourceRegistrySha256": _sha256(source_registry_path.read_bytes()),
        "vocabularyRegistrySha256": _sha256(vocabulary_registry_path.read_bytes()),
        "lexemesSha256": _sha256(lexemes_path.read_bytes()),
        "classificationsSha256": _sha256(classifications_path.read_bytes()),
        "jitendexSha256": jitendex_digest,
        "classifier": {"name": "complete-classification-pipeline", "version": "1.0.0"},
        "counts": {
            "lexemes": len(rows),
            "classifications": len(rows),
            "conflicts": conflicts,
            "levels": {level: level_counts[level] for level in LEVELS},
        },
        "files": files,
    }
    found = errors("artifact-manifest.schema.json", manifest)
    if found:
        raise PackagingError("invalid artifact manifest: " + "; ".join(found))

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "jlpt-levels-yomitan.zip"
    manifest_path = output_dir / "artifact-manifest.json"
    sha256s_path = output_dir / "SHA256SUMS"
    zip_digest = _sha256(zip_payload)
    outputs = {
        zip_path: zip_payload,
        manifest_path: canonical_json_bytes(manifest),
        sha256s_path: f"{zip_digest}  {zip_path.name}\n".encode(),
    }
    temporary: list[tuple[Path, Path]] = []
    try:
        for path, payload in outputs.items():
            candidate = path.with_name(f".{path.name}.tmp")
            candidate.write_bytes(payload)
            temporary.append((candidate, path))
        for candidate, path in temporary:
            candidate.replace(path)
    finally:
        for candidate, _ in temporary:
            candidate.unlink(missing_ok=True)
    return PackageResult(zip_path, manifest_path, sha256s_path, zip_digest)
