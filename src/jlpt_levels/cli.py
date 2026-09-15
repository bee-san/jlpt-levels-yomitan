from __future__ import annotations

import argparse
from pathlib import Path

from .contracts import SCHEMA_DIR, errors, load_json, validate_examples, validator
from .identity import canonical_json_bytes, lexeme_id


def _validate_contracts(_: argparse.Namespace) -> int:
    schemas = sorted(SCHEMA_DIR.glob("*.schema.json"))
    for path in schemas:
        validator(path.name)
    checked, failures = validate_examples()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"OK: {len(schemas)} schemas and {checked} positive/negative example cases")
    return 0


def _validate(args: argparse.Namespace) -> int:
    found = errors(args.schema, load_json(Path(args.document)))
    if found:
        for item in found:
            print(item)
        return 1
    print("OK")
    return 0


def _canonicalize(args: argparse.Namespace) -> int:
    document = load_json(Path(args.input))
    Path(args.output).write_bytes(canonical_json_bytes(document))
    return 0


def _lexeme_id(args: argparse.Namespace) -> int:
    print(lexeme_id(args.term, args.reading))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="jlpt-levels")
    commands = result.add_subparsers(dest="command", required=True)
    contracts = commands.add_parser("validate-contracts", help="validate schemas and all declared examples")
    contracts.set_defaults(func=_validate_contracts)
    validate = commands.add_parser("validate", help="validate one JSON document")
    validate.add_argument("schema", choices=sorted(path.name for path in SCHEMA_DIR.glob("*.schema.json")))
    validate.add_argument("document")
    validate.set_defaults(func=_validate)
    canonicalize = commands.add_parser("canonicalize", help="write deterministic canonical JSON")
    canonicalize.add_argument("input")
    canonicalize.add_argument("output")
    canonicalize.set_defaults(func=_canonicalize)
    identity = commands.add_parser("lexeme-id", help="derive identity from exact term and reading")
    identity.add_argument("term")
    identity.add_argument("reading")
    identity.set_defaults(func=_lexeme_id)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)
