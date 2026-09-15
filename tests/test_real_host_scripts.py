from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_probe_builder_is_deterministic_and_covers_n5_n1_n0(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    outputs = []
    for name in ("one", "two"):
        result = subprocess.run(
            [sys.executable, str(root / "scripts/build_probe_dictionary.py"), str(tmp_path / name)],
            cwd=root,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(json.loads(result.stdout))
    assert Path(outputs[0]["zip"]).read_bytes() == Path(outputs[1]["zip"]).read_bytes()
    expected = json.loads(Path(outputs[0]["expected"]).read_text(encoding="utf-8"))
    assert {(item["displayValue"], item["value"]) for item in expected["probes"]} == {
        ("N5", 1), ("N1", 5), ("N0", 6),
    }


def test_yomitan_import_probe_has_valid_javascript_syntax() -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        ["node", "--check", str(root / "scripts/yomitan_import_probe.mjs")],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
