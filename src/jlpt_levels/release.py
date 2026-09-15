from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .identity import canonical_json_bytes

SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_DATE_RE = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}")
TAG_RE = re.compile(r"v([0-9]{4}\.[0-9]{2}\.[0-9]{2})\.([1-9][0-9]*)")


class ReleaseError(ValueError):
    pass


def _canonical_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise ReleaseError(f"not a canonical relative path: {value!r}")
    return path


def _digest(path: Path) -> tuple[str, int]:
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def build_input_lock(root: Path, paths: Sequence[str]) -> dict[str, Any]:
    canonical = [_canonical_path(value).as_posix() for value in paths]
    if len(set(canonical)) != len(canonical):
        raise ReleaseError("duplicate input path")
    files: list[dict[str, Any]] = []
    for value in sorted(canonical):
        path = root / value
        if not path.is_file() or path.is_symlink():
            raise ReleaseError(f"input is not a regular file: {value}")
        digest, size = _digest(path)
        files.append({"path": value, "sha256": digest, "bytes": size})
    if not files:
        raise ReleaseError("input lock cannot be empty")
    return {"schemaVersion": 1, "files": files}


def verify_input_lock(root: Path, lock: Mapping[str, Any]) -> None:
    if set(lock) != {"schemaVersion", "files"} or lock.get("schemaVersion") != 1:
        raise ReleaseError("unsupported input lock")
    files = lock.get("files")
    if not isinstance(files, list) or not files:
        raise ReleaseError("input lock files must be a non-empty array")
    names: list[str] = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "bytes"}:
            raise ReleaseError("invalid input lock file record")
        name = _canonical_path(item["path"]).as_posix()
        names.append(name)
        expected = item["sha256"]
        expected_size = item["bytes"]
        if not isinstance(expected, str) or SHA256_RE.fullmatch(expected) is None:
            raise ReleaseError(f"invalid digest for {name}")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
            raise ReleaseError(f"invalid byte count for {name}")
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ReleaseError(f"locked input is not a regular file: {name}")
        actual, actual_size = _digest(path)
        if actual != expected or actual_size != expected_size:
            raise ReleaseError(f"digest mismatch for locked input: {name}")
    if names != sorted(names) or len(names) != len(set(names)):
        raise ReleaseError("input lock paths must be sorted and unique")


def _source_identity(value: Any, source_id: str) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"revision", "sha256"}:
        raise ReleaseError(f"invalid source identity for {source_id}")
    revision, digest = value["revision"], value["sha256"]
    if not isinstance(revision, str) or not revision.strip():
        raise ReleaseError(f"invalid source revision for {source_id}")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise ReleaseError(f"invalid source digest for {source_id}")
    return revision, digest


def detect_source_changes(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    if not previous or set(previous) != set(current):
        raise ReleaseError("source identities differ between baseline and candidate")
    changed: list[str] = []
    for source_id in sorted(previous):
        if _source_identity(previous[source_id], source_id) != _source_identity(current[source_id], source_id):
            changed.append(source_id)
    return changed


def _classification_index(rows: Iterable[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        lexeme_id = row.get("lexemeId")
        if not isinstance(lexeme_id, str) or not lexeme_id.startswith("sha256:"):
            raise ReleaseError(f"invalid {label} classification identity")
        if lexeme_id in result:
            raise ReleaseError(f"duplicate {label} classification: {lexeme_id}")
        result[lexeme_id] = row
    return result


def compare_classifications(
    previous: Iterable[Mapping[str, Any]],
    current: Iterable[Mapping[str, Any]],
    explanations: Mapping[str, str],
) -> dict[str, Any]:
    old = _classification_index(previous, "baseline")
    new = _classification_index(current, "candidate")
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed: list[dict[str, Any]] = []
    unchanged = 0
    for lexeme_id in sorted(set(old) & set(new)):
        before = {key: old[lexeme_id].get(key) for key in ("level", "method")}
        after = {key: new[lexeme_id].get(key) for key in ("level", "method")}
        if before == after:
            unchanged += 1
        else:
            reason = explanations.get(lexeme_id)
            if not isinstance(reason, str) or not reason.strip():
                raise ReleaseError(f"unexplained classification change: {lexeme_id}")
            changed.append({"lexemeId": lexeme_id, "before": before, "after": after, "reason": reason.strip()})
    stale = sorted(set(explanations) - {item["lexemeId"] for item in changed})
    if stale:
        raise ReleaseError(f"stale classification change explanation: {stale[0]}")
    return {
        "schemaVersion": 1,
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed), "unchanged": unchanged},
        "addedLexemeIds": added,
        "removedLexemeIds": removed,
        "changes": changed,
    }


def select_revision(resolved_date: str, existing_tags: Sequence[str]) -> str:
    if REVISION_DATE_RE.fullmatch(resolved_date) is None:
        raise ReleaseError("resolved date must be YYYY.MM.DD")
    matching: list[int] = []
    for tag in existing_tags:
        found = TAG_RE.fullmatch(tag)
        if found is None:
            raise ReleaseError(f"invalid release tag: {tag}")
        date, serial = found.groups()
        if date > resolved_date:
            raise ReleaseError(f"existing tag date {date} is later than resolved date {resolved_date}")
        if date == resolved_date:
            matching.append(int(serial))
    serial = max(matching, default=0) + 1
    return f"{resolved_date}.{serial}"


def write_canonical(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
