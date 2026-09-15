#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

EXPECTED = {"jlpt-levels-yomitan.zip", "SHA256SUMS", "artifact-manifest.json", "source-identities.json", "classifications.jsonl", "classification-diff.json"}


def fail(message: str) -> None:
    raise SystemExit(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_handoff(directory: Path) -> None:
    names = {path.name for path in directory.iterdir() if path.is_file()}
    if names != EXPECTED:
        fail(f"candidate inventory mismatch: {sorted(names)}")
    zip_path = directory / "jlpt-levels-yomitan.zip"
    checksum = (directory / "SHA256SUMS").read_text(encoding="utf-8").split()
    if checksum != [digest(zip_path), zip_path.name]:
        fail("candidate checksum mismatch")
    manifest = json.loads((directory / "artifact-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or manifest.get("counts", {}).get("lexemes", 0) < 1:
        fail("invalid or empty candidate manifest")
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not names or names[0] != "index.json":
            fail("invalid archive inventory")
        for item in manifest["files"]:
            payload = archive.read(item["path"])
            if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
                fail(f"manifest mismatch for {item['path']}")


def compare(baseline: Path, candidate: Path) -> None:
    diff = json.loads((candidate / "classification-diff.json").read_text(encoding="utf-8"))
    counts = diff["counts"]
    before = sum(1 for line in (baseline / "classifications.jsonl").read_text().splitlines() if line.strip())
    after = sum(1 for line in (candidate / "classifications.jsonl").read_text().splitlines() if line.strip())
    if before and after < max(1, int(before * 0.90)):
        fail(f"unexpected corpus collapse: {before} -> {after}")
    if counts["removed"] and counts["removed"] > max(10, int(before * 0.01)):
        fail(f"unexpected removed-classification spike: {counts['removed']}")
    if counts["changed"] != len(diff["changes"]):
        fail("classification diff count mismatch")


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--handoff":
        verify_handoff(Path(args[1]))
    elif len(args) == 2:
        compare(Path(args[0]), Path(args[1]))
    else:
        fail("usage: check_release_candidate.py BASELINE CANDIDATE | --handoff DIRECTORY")


if __name__ == "__main__":
    main()
