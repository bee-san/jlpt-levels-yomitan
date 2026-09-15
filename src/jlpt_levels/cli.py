from __future__ import annotations

import argparse
import os
from pathlib import Path

from .adjudication import BedrockBackend, run_queue
from .contracts import DATA_DIR, SCHEMA_DIR, errors, load_json, validate_examples, validator
from .fallback import predict_files, train_files
from .finalize import finalize_files
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
        Path(args.lexemes), Path(args.evidence), Path(args.matches),
        Path(args.classifications), Path(args.audit),
    )
    coverage = audit["coverage"]["lexemes"]
    print(
        f"OK: resolved={coverage['resolvedDirect']}, "
        f"conflicts={coverage['unresolvedDirectConflict']}, "
        f"without-direct-votes={coverage['withoutDirectVotes']}"
    )
    return 0


def _train_fallback(args: argparse.Namespace) -> int:
    report = train_files(
        Path(args.training), Path(args.model), Path(args.report),
        holdout_fraction=args.holdout_fraction, split_salt=args.split_salt,
        min_token_count=args.min_token_count, confidence_threshold=args.confidence_threshold,
    )
    print(
        f"OK: train={report['counts']['trainRows']}, holdout={report['counts']['holdoutRows']}, "
        f"abstained={report['counts']['abstained']}"
    )
    return 0


def _infer_fallback(args: argparse.Namespace) -> int:
    counts = predict_files(
        Path(args.model), Path(args.residual), Path(args.inferred), Path(args.adjudication_required)
    )
    print("OK: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return 0


def _adjudicate_residuals(args: argparse.Namespace) -> int:
    report = run_queue(
        Path(args.queue), Path(args.output), Path(args.pending), Path(args.report),
        Path(args.cache_dir), BedrockBackend(args.region), concurrency=args.concurrency,
        retries=args.retries, max_tokens=args.max_tokens,
        input_price_per_million=args.input_price_per_million,
        output_price_per_million=args.output_price_per_million,
    )
    print("OK: " + ", ".join(f"{key}={value}" for key, value in report["counts"].items()))
    return 0 if report["counts"]["pending"] == 0 else 2


def _finalize(args: argparse.Namespace) -> int:
    reports = finalize_files(
        Path(args.lexemes), Path(args.direct), Path(args.inferred), Path(args.adjudicated),
        Path(args.direct_audit), Path(args.output), Path(args.reports_dir),
        baseline_path=Path(args.baseline) if args.baseline else None,
        change_explanations_path=Path(args.change_explanations) if args.change_explanations else None,
    )
    coverage = reports["coverage"]
    print(
        f"OK: classifications={coverage['classifications']}, "
        + ", ".join(f"{method}={count}" for method, count in coverage["byMethod"].items())
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
    train = commands.add_parser("train-fallback", help="calibrate the kanji and linguistic fallback")
    train.add_argument("--training", default="data/derived/fallback-training.jsonl")
    train.add_argument("--model", default="data/derived/fallback-model.json")
    train.add_argument("--report", default="data/derived/fallback-holdout-report.json")
    train.add_argument("--holdout-fraction", type=float, default=0.2)
    train.add_argument("--split-salt", default="v1")
    train.add_argument("--min-token-count", type=int, default=2)
    train.add_argument("--confidence-threshold", type=float, default=0.62)
    train.set_defaults(func=_train_fallback)
    infer = commands.add_parser("infer-fallback", help="classify residuals and route abstentions")
    infer.add_argument("--model", default="data/derived/fallback-model.json")
    infer.add_argument("--residual", default="data/derived/fallback-residual.jsonl")
    infer.add_argument("--inferred", default="data/derived/fallback-inferred.jsonl")
    infer.add_argument("--adjudication-required", default="data/derived/fallback-adjudication-required.jsonl")
    infer.set_defaults(func=_infer_fallback)
    adjudicate = commands.add_parser("adjudicate-residuals", help="run isolated Bedrock Luna adjudications")
    adjudicate.add_argument("--queue", default="data/derived/fallback-adjudication-required.jsonl")
    adjudicate.add_argument("--output", default="data/derived/adjudicated-classifications.jsonl")
    adjudicate.add_argument("--pending", default="data/derived/adjudication-pending.jsonl")
    adjudicate.add_argument("--report", default="data/audit/adjudication-report.json")
    adjudicate.add_argument("--cache-dir", default="data/cache/adjudication")
    adjudicate.add_argument("--region", default="us-east-1")
    adjudicate.add_argument("--concurrency", type=int, default=8)
    adjudicate.add_argument("--retries", type=int, default=3)
    adjudicate.add_argument("--max-tokens", type=int, default=700)
    adjudicate.add_argument("--input-price-per-million", type=float)
    adjudicate.add_argument("--output-price-per-million", type=float)
    adjudicate.set_defaults(func=_adjudicate_residuals)
    finalize = commands.add_parser("finalize", help="merge classification stages and prove exact census coverage")
    finalize.add_argument("--lexemes", default="data/derived/jitendex.lexemes.jsonl")
    finalize.add_argument("--direct", default="data/derived/direct-classifications.jsonl")
    finalize.add_argument("--inferred", default="data/derived/fallback-inferred.jsonl")
    finalize.add_argument("--adjudicated", default="data/derived/adjudicated-classifications.jsonl")
    finalize.add_argument("--direct-audit", default="data/audit/direct-evidence-resolution.json")
    finalize.add_argument("--output", default="data/derived/final-classifications.jsonl")
    finalize.add_argument("--reports-dir", default="data/audit/final")
    finalize.add_argument("--baseline")
    finalize.add_argument("--change-explanations", help="JSON object mapping every intentional baseline change to a reason")
    finalize.set_defaults(func=_finalize)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)

