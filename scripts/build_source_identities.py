#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Write immutable source identities consumed by the release diff")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    lock_path = ROOT / "data/sources/jitendex.lock.json"
    registry_path = ROOT / "config/vocabulary-sources.json"
    report_path = ROOT / "data/evidence/vocabulary-report.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    artifact = lock["artifact"]
    source = registry["sources"][0]
    snapshots = report.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise SystemExit("vocabulary report lacks snapshots")
    payload = {
        "jitendex": {
            "revision": lock["release"]["tag"],
            "sha256": artifact["sha256"],
        },
        source["id"]: {
            "revision": ",".join(str(page["revision"]) for page in source["pages"].values()),
            "sha256": hashlib.sha256(json.dumps(snapshots, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())