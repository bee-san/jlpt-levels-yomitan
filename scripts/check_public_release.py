#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args: str) -> str:
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_public_release.py TAG CANDIDATE_DIR")
    tag, candidate = sys.argv[1], Path(sys.argv[2])
    repository = os.environ["GITHUB_REPOSITORY"]
    release = json.loads(run("gh", "api", f"repos/{repository}/releases/tags/{tag}"))
    if release.get("draft") or release.get("prerelease"):
        raise SystemExit("release is not public and final")
    assets = {item["name"]: item for item in release["assets"]}
    expected = {
        "jlpt-levels-yomitan.zip",
        "SHA256SUMS",
        "artifact-manifest.json",
        "source-identities.json",
        "classifications.jsonl",
        "classification-diff.json",
    }
    if set(assets) != expected:
        raise SystemExit(f"public asset inventory mismatch: {sorted(assets)}")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name in sorted(expected):
            subprocess.run(
                ["gh", "api", assets[name]["url"], "-H", "Accept: application/octet-stream"],
                check=True,
                stdout=(root / name).open("wb"),
            )
            if digest(root / name) != digest(candidate / name):
                raise SystemExit(f"public bytes differ for {name}")
        checksum = (root / "SHA256SUMS").read_text(encoding="utf-8").split()
        if checksum != [digest(root / "jlpt-levels-yomitan.zip"), "jlpt-levels-yomitan.zip"]:
            raise SystemExit("public checksum does not verify")


if __name__ == "__main__":
    main()
