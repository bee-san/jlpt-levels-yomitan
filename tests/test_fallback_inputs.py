from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_builder_partitions_census_and_does_not_invent_features(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    first = {
        "lexemeId": "sha256:" + "a" * 64,
        "term": "学校",
        "reading": "がっこう",
        "jitendex": {"upstreamIds": ["jitendex:sequence:1"]},
    }
    second = {
        "lexemeId": "sha256:" + "b" * 64,
        "term": "カフェ2.5",
        "reading": "カフェにてんご",
        "jitendex": {"upstreamIds": ["jitendex:sequence:2"]},
    }
    direct = {"lexemeId": first["lexemeId"], "level": "N5"}
    lexemes = tmp_path / "lexemes.jsonl"
    classifications = tmp_path / "direct.jsonl"
    audit = tmp_path / "audit.json"
    training = tmp_path / "training.jsonl"
    residual = tmp_path / "residual.jsonl"
    _write(lexemes, [first, second])
    _write(classifications, [direct])
    audit.write_text('{"unresolvedConflicts":[]}\n', encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/build_fallback_inputs.py"),
            "--lexemes", str(lexemes),
            "--direct", str(classifications),
            "--direct-audit", str(audit),
            "--training", str(training),
            "--residual", str(residual),
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"conflicts": 0, "lexemes": 2, "residual": 1, "training": 1}
    trained = json.loads(training.read_text(encoding="utf-8"))
    pending = json.loads(residual.read_text(encoding="utf-8"))
    assert trained["directLevel"] == "N5"
    assert pending["features"] == {
        "commonnessRank": None,
        "componentKanji": [],
        "morphology": [],
        "orthography": ["reading-kana", "term-digit", "term-kana", "term-other"],
        "senseTags": [],
    }
