#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemExit(f"{path}:{number}: invalid JSON") from error
            if not isinstance(value, dict):
                raise SystemExit(f"{path}:{number}: row is not an object")
            yield value


def script(character: str) -> str:
    name = unicodedata.name(character, "")
    if "CJK UNIFIED IDEOGRAPH" in name or "CJK COMPATIBILITY IDEOGRAPH" in name:
        return "kanji"
    if "HIRAGANA" in name or "KATAKANA" in name:
        return "kana"
    if character.isascii() and character.isalpha():
        return "latin"
    if character.isdigit():
        return "digit"
    return "other"


def features(term: str, reading: str) -> dict:
    term_scripts = sorted({script(character) for character in term})
    reading_scripts = sorted({script(character) for character in reading})
    return {
        "componentKanji": [],
        "commonnessRank": None,
        "morphology": [],
        "orthography": sorted([
            *(f"term-{item}" for item in term_scripts),
            *(f"reading-{item}" for item in reading_scripts),
        ]),
        "senseTags": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic fallback training and residual rows")
    parser.add_argument("--lexemes", type=Path, default=ROOT / "data/derived/jitendex.lexemes.jsonl")
    parser.add_argument("--direct", type=Path, default=ROOT / "data/derived/direct-classifications.jsonl")
    parser.add_argument("--direct-audit", type=Path, default=ROOT / "data/audit/direct-evidence-resolution.json")
    parser.add_argument("--training", type=Path, default=ROOT / "data/derived/fallback-training.jsonl")
    parser.add_argument("--residual", type=Path, default=ROOT / "data/derived/fallback-residual.jsonl")
    args = parser.parse_args()

    direct = {row["lexemeId"]: row for row in read_jsonl(args.direct)}
    audit = json.loads(args.direct_audit.read_text(encoding="utf-8"))
    conflicts = {row["lexemeId"] for row in audit.get("unresolvedConflicts", [])}
    args.training.parent.mkdir(parents=True, exist_ok=True)
    counts = {"lexemes": 0, "training": 0, "residual": 0, "conflicts": len(conflicts)}
    seen: set[str] = set()
    with args.training.open("wb") as training, args.residual.open("wb") as residual:
        for lexeme in read_jsonl(args.lexemes):
            identity = lexeme["lexemeId"]
            if identity in seen:
                raise SystemExit(f"duplicate lexemeId: {identity}")
            seen.add(identity)
            row = {
                "features": features(lexeme["term"], lexeme["reading"]),
                "jitendexUpstreamIds": lexeme["jitendex"]["upstreamIds"],
                "lexemeId": identity,
                "reading": lexeme["reading"],
                "term": lexeme["term"],
            }
            counts["lexemes"] += 1
            if identity in direct:
                training.write(canonical({**row, "directLevel": direct[identity]["level"]}))
                counts["training"] += 1
            else:
                residual.write(canonical(row))
                counts["residual"] += 1
    if set(direct) - seen:
        raise SystemExit("direct classifications contain non-census lexemes")
    if counts["training"] != len(direct) or counts["training"] + counts["residual"] != counts["lexemes"]:
        raise SystemExit("fallback input partition is incomplete")
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
