#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jlpt_levels.identity import canonical_json_bytes, lexeme_id  # noqa: E402
from jlpt_levels.package import build_dictionary  # noqa: E402


LEVELS = (("初級", "しょきゅう", "N5"), ("上級", "じょうきゅう", "N1"), ("超級", "ちょうきゅう", "N0"))


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_probe_dictionary.py OUTPUT_DIR")
    output = Path(sys.argv[1])
    inputs = output / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    lexemes = []
    classifications = []
    for term, reading, level in LEVELS:
        identity = lexeme_id(term, reading)
        lexemes.append({
            "lexemeId": identity,
            "term": term,
            "reading": reading,
            "jitendex": {
                "dictionarySha256": "b" * 64,
                "occurrences": [{"bank": "term_bank_1.json", "row": len(lexemes), "sequence": len(lexemes) + 1}],
                "upstreamIds": [f"jitendex:sequence:{len(lexemes) + 1}"],
            },
        })
        features: dict[str, object] = {"maximumComponentKanjiLevel": level}
        if level == "N0":
            features["postN1DifficultySignals"] = ["probe-post-n1"]
        classifications.append({
            "lexemeId": identity,
            "level": level,
            "method": "inferred",
            "confidence": 0.75,
            "conflict": False,
            "policy": {"name": "conservative-lexeme-inference", "version": "1.0.0"},
            "evidence": [],
            "features": features,
        })
    paths = {
        "lexemes": inputs / "lexemes.jsonl",
        "classifications": inputs / "classifications.jsonl",
        "sources": inputs / "sources.json",
        "vocabulary": inputs / "vocabulary-sources.json",
        "lock": inputs / "jitendex.lock.json",
    }
    paths["lexemes"].write_bytes(b"".join(canonical_json_bytes(row) for row in reversed(lexemes)))
    paths["classifications"].write_bytes(b"".join(canonical_json_bytes(row) for row in classifications))
    paths["sources"].write_bytes(canonical_json_bytes({"version": 1, "sources": [{
        "id": "jitendex", "acquisition": {"sha256": "b" * 64},
        "license": {"status": "verified", "redistributable": True, "attribution": "Jitendex probe"},
    }]}))
    paths["vocabulary"].write_bytes(canonical_json_bytes({"version": 1, "sources": [{
        "id": "probe-vocabulary",
        "license": {"redistributable": True, "attribution": "Synthetic probe vocabulary"},
    }]}))
    paths["lock"].write_bytes(canonical_json_bytes({"artifact": {"sha256": "b" * 64}, "release": {"tag": "probe"}}))
    result = build_dictionary(
        paths["lexemes"], paths["classifications"], paths["sources"], paths["vocabulary"], paths["lock"], output,
        revision="2026.09.15.1", created_at="2026-09-15T00:00:00Z", bank_size=2,
    )
    expected = {
        "title": "JLPT Levels for Jitendex",
        "probes": [
            {"term": term, "reading": reading, "value": ("N5", "N4", "N3", "N2", "N1", "N0").index(level) + 1, "displayValue": level}
            for term, reading, level in LEVELS
        ],
    }
    (output / "probe-expected.json").write_bytes(canonical_json_bytes(expected))
    print(json.dumps({"zip": str(result.zip_path), "expected": str(output / "probe-expected.json"), "sha256": result.zip_sha256}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
