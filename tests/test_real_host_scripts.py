from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


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


def test_yomitan_import_probe_executes_real_importer_when_configured(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    yomitan_root_value = os.environ.get("YOMITAN_ROOT")
    if not yomitan_root_value:
        pytest.skip("YOMITAN_ROOT is required for the real importer integration test")
    yomitan_root = Path(yomitan_root_value)
    assert (yomitan_root / "ext/lib/resvg-wasm.js").is_file(), "run npm run build:libs in YOMITAN_ROOT"
    build = subprocess.run(
        [sys.executable, str(root / "scripts/build_probe_dictionary.py"), str(tmp_path / "probe")],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert build.returncode == 0, build.stderr
    output = json.loads(build.stdout)
    probe = subprocess.run(
        [
            "node",
            str(root / "scripts/yomitan_import_probe.mjs"),
            str(yomitan_root),
            output["zip"],
            output["expected"],
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert probe.returncode == 0, probe.stderr
    result = json.loads(probe.stdout)
    assert result["importErrors"] == 0
    assert {(item["displayValue"], item["value"]) for item in result["probes"]} == {
        ("N5", 1), ("N1", 5), ("N0", 6),
    }
