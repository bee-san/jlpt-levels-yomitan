from __future__ import annotations

import argparse
import os
from pathlib import Path

from .contracts import DATA_DIR, SCHEMA_DIR, errors, load_json, validate_examples, validator
from .identity import canonical_json_bytes, lexeme_id
from .jitendex import acquire, build_census
from .matching import match_files
from .resolution import resolve_files
from .sources.common import CachedFetcher
from .sources.wiktionary import WiktionaryJlptAdapter


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


def _acquire_jitendex(args: argparse.Namespace) -> int:
    print(acquire(Path(args.lock), Path(args.cache_dir)))
    return 0


def _census_jitendex(args: argparse.Namespace) -> int:
    census = build_census(
        Path(args.archive), Path(args.lock), Path(args.lexemes), Path(args.census)
    )
    print(
        f"OK: {census['counts']['rawRows']} rows -> "
        f"{census['counts']['normalizedLexemes']} normalized lexemes"
    )
    return 0


def _ingest_vocabulary(args: argparse.Namespace) -> int:
    registry = load_json(DATA_DIR / "config" / "vocabulary-sources.json")
    sources = registry.get("sources", [])
    if len(sources) != 1 or sources[0].get("adapter") != "wiktionary-jlpt":
        raise ValueError("every approved vocabulary source must have an implemented adapter")
    config = sources[0]
    if config.get("license", {}).get("redistributable") is not True:
        raise ValueError("source redistribution is not explicitly approved")
    user_agent = args.user_agent or os.environ.get("JLPT_LEVELS_USER_AGENT")
    if not user_agent:
        raise ValueError("set --user-agent or JLPT_LEVELS_USER_AGENT to a contactable descriptive value")
    fetcher = CachedFetcher(Path(args.cache_dir), user_agent, config["minimumDelayMs"])
    adapter = WiktionaryJlptAdapter(config, fetcher)
    adapter.run(Path(args.output), Path(args.report), offline=args.offline)
    return 0


def _match_vocabulary(args: argparse.Namespace) -> int:
    report = match_files(
        Path(args.lexemes), Path(args.evidence), Path(args.matches), Path(args.report)
    )
    print("OK: " + ", ".join(f"{name}={count}" for name, count in report["counts"].items()))
    return 0


def _resolve_direct(args: argparse.Namespace) -> int:
    audit = resolve_files(
        Path(args.lexemes),
        Path(args.evidence),
        Path(args.matches),
        Path(args.classifications),
        Path(args.audit),
    )
    coverage = audit["coverage"]["lexemes"]
    print(
        f"OK: resolved={coverage['resolvedDirect']}, "
        f"conflicts={coverage['unresolvedDirectConflict']}, "
        f"without-direct-votes={coverage['withoutDirectVotes']}"
    )
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
    acquire_parser = commands.add_parser("acquire-jitendex", help="fetch the exact locked Jitendex archive")
    acquire_parser.add_argument("--lock", default="data/sources/jitendex.lock.json")
    acquire_parser.add_argument("--cache-dir", default="data/cache/jitendex")
    acquire_parser.set_defaults(func=_acquire_jitendex)
    census = commands.add_parser("census-jitendex", help="extract the complete locked Jitendex lexeme census")
    census.add_argument("archive")
    census.add_argument("--lock", default="data/sources/jitendex.lock.json")
    census.add_argument("--lexemes", default="data/derived/jitendex.lexemes.jsonl")
    census.add_argument("--census", default="data/derived/jitendex.census.json")
    census.set_defaults(func=_census_jitendex)
    ingest = commands.add_parser("ingest-vocabulary", help="acquire approved vocabulary evidence")
    ingest.add_argument("--cache-dir", default=".cache/vocabulary")
    ingest.add_argument("--output", default="data/evidence/vocabulary.jsonl")
    ingest.add_argument("--report", default="data/evidence/vocabulary-report.json")
    ingest.add_argument("--user-agent")
    ingest.add_argument("--offline", action="store_true")
    ingest.set_defaults(func=_ingest_vocabulary)
    match = commands.add_parser("match-vocabulary", help="conservatively join evidence to Jitendex lexemes")
    match.add_argument("--lexemes", default="data/derived/jitendex.lexemes.jsonl")
    match.add_argument("--evidence", default="data/evidence/vocabulary.jsonl")
    match.add_argument("--matches", default="data/derived/vocabulary-matches.jsonl")
    match.add_argument("--report", default="data/derived/vocabulary-match-report.json")
    match.set_defaults(func=_match_vocabulary)
    resolve = commands.add_parser("resolve-direct", help="resolve attributable direct evidence conservatively")
    resolve.add_argument("--lexemes", default="data/derived/jitendex.lexemes.jsonl")
    resolve.add_argument("--evidence", default="data/evidence/vocabulary.jsonl")
    resolve.add_argument("--matches", default="data/derived/vocabulary-matches.jsonl")
    resolve.add_argument("--classifications", default="data/derived/direct-classifications.jsonl")
    resolve.add_argument("--audit", default="data/audit/direct-evidence-resolution.json")
    resolve.set_defaults(func=_resolve_direct)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)

