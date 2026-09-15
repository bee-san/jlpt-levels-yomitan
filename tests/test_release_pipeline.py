from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from jlpt_levels.release import (
    ReleaseError,
    build_input_lock,
    compare_classifications,
    detect_source_changes,
    select_revision,
    verify_input_lock,
)


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_input_lock_binds_every_consumed_file_and_detects_drift(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write(root / "config/sources.json", b'{"version":1}\n')
    _write(root / "config/vocabulary-sources.json", b'{"version":1}\n')
    _write(root / "data/sources/jitendex.lock.json", b'{"schemaVersion":1}\n')

    lock = build_input_lock(root, [
        "config/sources.json",
        "config/vocabulary-sources.json",
        "data/sources/jitendex.lock.json",
    ])
    verify_input_lock(root, lock)
    assert [item["path"] for item in lock["files"]] == sorted(item["path"] for item in lock["files"])
    assert lock["files"][0]["sha256"] == hashlib.sha256((root / lock["files"][0]["path"]).read_bytes()).hexdigest()

    _write(root / "config/sources.json", b'{"version":2}\n')
    with pytest.raises(ReleaseError, match="digest mismatch"):
        verify_input_lock(root, lock)


def test_input_lock_rejects_noncanonical_and_duplicate_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write(root / "config/sources.json", b"{}\n")
    with pytest.raises(ReleaseError, match="canonical relative path"):
        build_input_lock(root, ["config/../config/sources.json"])
    with pytest.raises(ReleaseError, match="duplicate"):
        build_input_lock(root, ["config/sources.json", "config/sources.json"])


def test_detect_source_changes_is_semantic_and_fail_closed() -> None:
    previous = {
        "jitendex": {"revision": "1", "sha256": "a" * 64},
        "vocabulary": {"revision": "2", "sha256": "b" * 64},
    }
    current = json.loads(json.dumps(previous))
    assert detect_source_changes(previous, current) == []
    current["jitendex"]["revision"] = "3"
    assert detect_source_changes(previous, current) == ["jitendex"]
    with pytest.raises(ReleaseError, match="source identities"):
        detect_source_changes(previous, {"jitendex": previous["jitendex"]})


def test_semantic_diff_requires_reasons_for_every_changed_existing_lexeme() -> None:
    old = [
        {"lexemeId": "sha256:" + "a" * 64, "level": "N4", "method": "direct"},
        {"lexemeId": "sha256:" + "b" * 64, "level": "N3", "method": "inferred"},
    ]
    new = [
        {"lexemeId": "sha256:" + "a" * 64, "level": "N3", "method": "direct"},
        {"lexemeId": "sha256:" + "b" * 64, "level": "N3", "method": "adjudicated"},
        {"lexemeId": "sha256:" + "c" * 64, "level": "N5", "method": "direct"},
    ]
    with pytest.raises(ReleaseError, match="unexplained"):
        compare_classifications(old, new, {})
    report = compare_classifications(old, new, {
        "sha256:" + "a" * 64: "approved source revision changed the direct assertion",
        "sha256:" + "b" * 64: "versioned inference policy abstained after retraining",
    })
    assert report["counts"] == {"added": 1, "removed": 0, "changed": 2, "unchanged": 0}
    assert report["changes"][0]["lexemeId"] == "sha256:" + "a" * 64


def test_revision_selection_is_global_monotonic_and_refuses_clock_rollback() -> None:
    assert select_revision("2026.09.15", []) == "2026.09.15.1"
    assert select_revision("2026.09.15", ["v2026.09.15.1", "v2026.09.15.3"]) == "2026.09.15.4"
    with pytest.raises(ReleaseError, match="later than resolved date"):
        select_revision("2026.09.15", ["v2026.09.16.1"])
    with pytest.raises(ReleaseError, match="invalid release tag"):
        select_revision("2026.09.15", ["latest"])


def test_workflows_have_read_only_build_and_isolated_write_job() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/update.yml").read_text(encoding="utf-8")
    assert "schedule:" in workflow and "workflow_dispatch:" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "permissions:\n      contents: read" in workflow
    assert "permissions:\n      contents: write" in workflow
    assert "needs: build" in workflow
    assert "environment: release" in workflow
    assert "gh release create" in workflow
    assert "--draft" in workflow and "--verify-tag" in workflow
    assert "check_public_release.py" in workflow
    assert "persist-credentials: false" in workflow
    assert "if: needs.build.outputs.changed == 'true'" in workflow
    assert "make release-candidate" in workflow
    assert "npm --prefix \"$RUNNER_TEMP/yomitan\" run build:libs" in workflow
    assert "YOMITAN_ROOT" in workflow
    assert "JLPT_LEVELS_USER_AGENT:" in workflow
    assert "candidate/source-identities.json candidate/classifications.jsonl candidate/classification-diff.json" in workflow
    assert "first_release=true" in workflow
    release = (root / "Makefile").read_text(encoding="utf-8").split("release-candidate:", 1)[1]
    assert "build_source_identities.py build/source-identities.json" in release
    assert "final-classifications.jsonl build/classifications.jsonl" in release
    assert "cache-hit" not in workflow


def test_release_candidate_includes_real_yomitan_import_gate() -> None:
    root = Path(__file__).parents[1]
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    release = makefile.split("release-candidate:", 1)[1]
    assert 'test -n "$(YOMITAN_ROOT)"' in release
    assert '$(MAKE) verify-yomitan-import YOMITAN_ROOT="$(YOMITAN_ROOT)"' in release


def test_workflow_yaml_parses(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    script = "import pathlib, yaml; [yaml.safe_load(p.read_text()) for p in pathlib.Path('.github/workflows').glob('*.yml')]"
    result = subprocess.run(["python", "-c", script], cwd=root, text=True, capture_output=True)
    if result.returncode and "No module named 'yaml'" in result.stderr:
        pytest.skip("PyYAML is not a project dependency; syntax is checked in CI with actionlint")
    assert result.returncode == 0, result.stderr
