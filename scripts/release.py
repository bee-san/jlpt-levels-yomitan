#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jlpt_levels.release import (  # noqa: E402
    ReleaseError,
    build_input_lock,
    compare_classifications,
    detect_source_changes,
    select_revision,
    verify_input_lock,
    write_canonical,
)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed release helper")
    sub = parser.add_subparsers(dest="command", required=True)

    lock = sub.add_parser("lock-inputs")
    lock.add_argument("root", type=Path)
    lock.add_argument("output", type=Path)
    lock.add_argument("paths", nargs="+")

    verify = sub.add_parser("verify-inputs")
    verify.add_argument("root", type=Path)
    verify.add_argument("lock", type=Path)

    sources = sub.add_parser("source-diff")
    sources.add_argument("previous", type=Path)
    sources.add_argument("current", type=Path)
    sources.add_argument("output", type=Path)

    classifications = sub.add_parser("classification-diff")
    classifications.add_argument("previous", type=Path)
    classifications.add_argument("current", type=Path)
    classifications.add_argument("explanations", type=Path)
    classifications.add_argument("output", type=Path)

    revision = sub.add_parser("revision")
    revision.add_argument("resolved_date")
    revision.add_argument("tags", nargs="*")

    args = parser.parse_args()
    try:
        if args.command == "lock-inputs":
            write_canonical(args.output, build_input_lock(args.root, args.paths))
        elif args.command == "verify-inputs":
            verify_input_lock(args.root, _json(args.lock))
        elif args.command == "source-diff":
            changed = detect_source_changes(_json(args.previous), _json(args.current))
            write_canonical(args.output, {"schemaVersion": 1, "changedSources": changed})
        elif args.command == "classification-diff":
            write_canonical(
                args.output,
                compare_classifications(
                    _jsonl(args.previous),
                    _jsonl(args.current),
                    _json(args.explanations),
                ),
            )
        else:
            print(select_revision(args.resolved_date, args.tags))
    except (OSError, json.JSONDecodeError, ReleaseError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
