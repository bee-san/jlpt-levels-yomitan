from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .identity import lexeme_id

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT if (ROOT / "schemas").is_dir() else Path(__file__).resolve().parent / "data"
SCHEMA_DIR = DATA_DIR / "schemas"
EXAMPLE_DIR = DATA_DIR / "examples"
VENDORED_YOMITAN_DIR = SCHEMA_DIR / "vendor" / "yomitan" / "d34832d756e05dc00945e5b7d7ebc80963299a7a"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def validator(schema_name: str) -> Draft202012Validator:
    schema = load_json(SCHEMA_DIR / schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _semantic_errors(schema_name: str, document: Any) -> list[str]:
    found: list[str] = []
    if schema_name == "lexeme.schema.json" and isinstance(document, dict):
        term, reading = document.get("term"), document.get("reading")
        if isinstance(term, str) and isinstance(reading, str) and term and reading:
            if document.get("lexemeId") != lexeme_id(term, reading):
                found.append("/lexemeId: does not match canonical [term,reading]")
    elif schema_name == "classification.schema.json" and isinstance(document, dict):
        evidence = document.get("evidence", [])
        asserted = {item["assertedLevel"] for item in evidence if isinstance(item, dict) and isinstance(item.get("assertedLevel"), str)}
        evidence_ids = {item["evidenceId"] for item in evidence if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)}
        selected = {item for item in document.get("policy", {}).get("selectedEvidenceIds", []) if isinstance(item, str)}
        if document.get("method") == "direct" and document.get("level") not in asserted:
            found.append("/level: direct level must be asserted by evidence")
        if not selected.issubset(evidence_ids):
            found.append("/policy/selectedEvidenceIds: contains an unknown evidence ID")
        if document.get("conflict") != (len(asserted) > 1):
            found.append("/conflict: must equal whether evidence asserts multiple levels")
    elif schema_name == "artifact-manifest.schema.json" and isinstance(document, dict):
        counts = document.get("counts", {})
        levels = counts.get("levels", {})
        if levels and sum(levels.values()) != counts.get("classifications"):
            found.append("/counts/levels: sum must equal classifications")
        if counts.get("classifications") != counts.get("lexemes"):
            found.append("/counts: classifications must equal lexemes")
        paths = [item.get("path") for item in document.get("files", []) if isinstance(item, dict)]
        if paths != sorted(set(paths)):
            found.append("/files: paths must be unique and sorted")
    return found


def errors(schema_name: str, document: Any) -> list[str]:
    found = validator(schema_name).iter_errors(document)
    structural = [f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in sorted(found, key=lambda e: list(e.absolute_path))]
    return structural + _semantic_errors(schema_name, document)


def validate_examples() -> tuple[int, list[str]]:
    manifest = load_json(EXAMPLE_DIR / "manifest.json")
    checked = 0
    failures: list[str] = []
    for case in manifest["cases"]:
        checked += 1
        found = errors(case["schema"], load_json(EXAMPLE_DIR / case["file"]))
        expected = case["valid"]
        if expected and found:
            failures.append(f"{case['file']}: expected valid; " + "; ".join(found))
        if not expected and not found:
            failures.append(f"{case['file']}: expected rejection but passed")
    return checked, failures
