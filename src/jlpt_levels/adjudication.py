from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from jsonschema import Draft202012Validator

from .identity import canonical_json_bytes

PROVIDER = "bedrock"
MODEL = "global.openai.gpt-5.6-luna"
POLICY_NAME = "isolated-residual-adjudication"
PROMPT_VERSION = "1.0.0"
LEVELS = ("N5", "N4", "N3", "N2", "N1", "N0")

RUBRIC = """Assign one best-estimate difficulty band to this Japanese lexeme.
N5 is beginner and N1 is advanced JLPT vocabulary. N0 is strictly harder than N1,
not unknown, absent, or low confidence. Sourced assertions are authoritative and
must not be overridden. Use only the supplied evidence; do not invent facts.
Return exactly one JSON object matching the requested schema. Set abstain=true only
when malformed or contradictory input makes a responsible best estimate impossible."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "confidence", "rationale", "evidenceReferences", "abstain"],
    "properties": {
        "label": {"enum": list(LEVELS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 1000},
        "evidenceReferences": {
            "type": "array", "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
        "abstain": {"type": "boolean"},
    },
}
_VALIDATOR = Draft202012Validator(OUTPUT_SCHEMA)
_ALLOWED_ITEM_FIELDS = {
    "lexemeId", "term", "reading", "features", "inference", "legalEvidence",
    "evidenceReferences", "senses", "jitendexUpstreamIds",
}


class AdjudicationError(ValueError):
    pass


class Backend(Protocol):
    def invoke(self, prompt: str, *, max_tokens: int) -> dict[str, Any]: ...


@dataclass(frozen=True)
class BedrockBackend:
    region: str = "us-east-1"

    def invoke(self, prompt: str, *, max_tokens: int) -> dict[str, Any]:
        import boto3

        from botocore.config import Config

        client = boto3.client(
            "bedrock-runtime", region_name=self.region,
            config=Config(connect_timeout=15, read_timeout=600, retries={"max_attempts": 1}),
        )
        response = client.converse(
            modelId=MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        texts = [part["text"] for part in response["output"]["message"]["content"] if "text" in part]
        return {
            "text": "".join(texts),
            "usage": response.get("usage", {}),
            "requestId": response.get("ResponseMetadata", {}).get("RequestId"),
        }


def _clean_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise AdjudicationError("queue row must be an object")
    required = ("lexemeId", "term", "reading")
    if any(not isinstance(item.get(key), str) or not item[key] for key in required):
        raise AdjudicationError("queue row requires non-empty lexemeId, term, and reading")
    cleaned = {key: item[key] for key in sorted(_ALLOWED_ITEM_FIELDS & item.keys())}
    encoded = canonical_json_bytes(cleaned)
    if len(encoded) > 64_000:
        raise AdjudicationError("bounded adjudication input exceeds 64000 bytes")
    return cleaned


def build_prompt(item: dict[str, Any]) -> tuple[str, str]:
    cleaned = _clean_item(item)
    envelope = {
        "model": MODEL,
        "outputSchema": OUTPUT_SCHEMA,
        "promptVersion": PROMPT_VERSION,
        "rubric": RUBRIC,
        "item": cleaned,
    }
    input_bytes = canonical_json_bytes(envelope)
    digest = hashlib.sha256(input_bytes).hexdigest()
    return input_bytes.decode("utf-8"), digest


def _parse(text: str, allowed_references: set[str]) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise AdjudicationError("model output is not one JSON value") from error
    failures = sorted(_VALIDATOR.iter_errors(value), key=lambda error: list(error.absolute_path))
    if failures:
        raise AdjudicationError("model output schema failure: " + failures[0].message)
    unknown = set(value["evidenceReferences"]) - allowed_references
    if unknown:
        raise AdjudicationError("model cited evidence references absent from its input")
    if value["label"] == "N0" and not value["evidenceReferences"]:
        raise AdjudicationError("N0 requires a concrete supplied evidence reference")
    return value


def _references(item: dict[str, Any]) -> set[str]:
    result = set()
    for ref in item.get("evidenceReferences", []):
        if isinstance(ref, str):
            result.add(ref)
    for evidence in item.get("legalEvidence", []):
        if isinstance(evidence, dict) and isinstance(evidence.get("reference"), str):
            result.add(evidence["reference"])
    return result


def _cache_path(cache_dir: Path, digest: str) -> Path:
    return cache_dir / MODEL.replace("/", "_") / f"{digest}.json"


def adjudicate_item(
    item: dict[str, Any], backend: Backend, cache_dir: Path, *, retries: int = 3,
    max_tokens: int = 700, sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    prompt, digest = build_prompt(item)
    path = _cache_path(cache_dir, digest)
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        decision = _parse(cached["rawOutput"], _references(item))
        return decision, {**cached, "cached": True, "inputSha256": digest}
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, retries + 1):
        try:
            response = backend.invoke(prompt, max_tokens=max_tokens)
            decision = _parse(response["text"], _references(item))
            usage = response.get("usage", {})
            record = {
                "schemaVersion": 1, "provider": PROVIDER, "model": MODEL,
                "promptVersion": PROMPT_VERSION, "inputSha256": digest,
                "outputSha256": hashlib.sha256(response["text"].encode()).hexdigest(),
                "rawOutput": response["text"], "decision": decision,
                "usage": {
                    "inputTokens": int(usage.get("inputTokens", 0)),
                    "outputTokens": int(usage.get("outputTokens", 0)),
                    "totalTokens": int(usage.get("totalTokens", 0)),
                    "cacheReadInputTokens": int(usage.get("cacheReadInputTokens", 0)),
                    "cacheWriteInputTokens": int(usage.get("cacheWriteInputTokens", 0)),
                },
                "requestId": response.get("requestId"),
                "runAt": dt.datetime.now(dt.timezone.utc).isoformat(), "attempt": attempt,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(canonical_json_bytes(record))
            temporary.replace(path)
            return decision, {**record, "cached": False}
        except Exception as error:
            attempts.append({"attempt": attempt, "errorType": type(error).__name__, "message": str(error)})
            if attempt < retries:
                sleep(min(8.0, 0.5 * 2 ** (attempt - 1)) + random.random() * 0.1)
    return None, {"inputSha256": digest, "cached": False, "attempts": attempts}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise AdjudicationError(f"{path}:{number}: invalid JSON") from error
    ids = [row.get("lexemeId") for row in rows]
    if len(ids) != len(set(ids)):
        raise AdjudicationError("queue contains duplicate lexemeId values")
    return rows


def run_queue(
    queue_path: Path, output_path: Path, pending_path: Path, report_path: Path,
    cache_dir: Path, backend: Backend, *, concurrency: int = 8, retries: int = 3,
    max_tokens: int = 700, input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
) -> dict[str, Any]:
    if not 1 <= concurrency <= 64 or not 1 <= retries <= 10:
        raise AdjudicationError("concurrency must be 1-64 and retries 1-10")
    rows = _read_jsonl(queue_path)
    results: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(adjudicate_item, row, backend, cache_dir, retries=retries, max_tokens=max_tokens): row
            for row in rows
        }
        for future in concurrent.futures.as_completed(futures):
            row = futures[future]
            try:
                results[row["lexemeId"]] = future.result()
            except Exception as error:
                results[row["lexemeId"]] = (None, {"attempts": [{"errorType": type(error).__name__, "message": str(error)}]})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    usage = {key: 0 for key in ("inputTokens", "outputTokens", "totalTokens", "cacheReadInputTokens", "cacheWriteInputTokens")}
    requests = failures = cache_hits = abstentions = 0
    failure_types: dict[str, int] = {}
    with output_path.open("wb") as output, pending_path.open("wb") as pending:
        for row in rows:
            decision, metadata = results[row["lexemeId"]]
            if metadata.get("cached"):
                cache_hits += 1
            else:
                requests += int(metadata.get("attempt", len(metadata.get("attempts", []))))
            for key in usage:
                usage[key] += int(metadata.get("usage", {}).get(key, 0))
            if decision is None or decision["abstain"]:
                failures += decision is None
                abstentions += decision is not None and decision["abstain"]
                pending.write(canonical_json_bytes({**row, "lastFailure": metadata.get("attempts", []), "modelAbstained": bool(decision and decision["abstain"])}))
                for attempt in metadata.get("attempts", []):
                    name = attempt.get("errorType", "unknown")
                    failure_types[name] = failure_types.get(name, 0) + 1
                continue
            features = dict(row.get("features", {}))
            if decision["label"] == "N0":
                features.setdefault("postN1DifficultySignals", list(decision["evidenceReferences"]))
            output.write(canonical_json_bytes({
                "lexemeId": row["lexemeId"], "level": decision["label"],
                "method": "adjudicated", "confidence": decision["confidence"],
                "conflict": False, "policy": {"name": POLICY_NAME, "version": PROMPT_VERSION},
                "evidence": [], "features": features,
                "adjudication": {
                    "provider": PROVIDER, "model": MODEL, "promptVersion": PROMPT_VERSION,
                    "inputSha256": metadata["inputSha256"], "outputSha256": metadata["outputSha256"],
                    "batchSize": 1, "runAt": metadata["runAt"],
                },
            }))
    cost = None
    if input_price_per_million is not None and output_price_per_million is not None:
        cost = round((usage["inputTokens"] * input_price_per_million + usage["outputTokens"] * output_price_per_million) / 1_000_000, 12)
    report = {
        "schemaVersion": 1, "provider": PROVIDER, "model": MODEL, "promptVersion": PROMPT_VERSION,
        "counts": {"input": len(rows), "completed": len(rows) - failures - abstentions, "pending": failures + abstentions,
                   "failures": int(failures), "abstentions": int(abstentions), "requests": requests, "cacheHits": cache_hits},
        "tokens": usage, "costUsd": cost,
        "pricing": {"inputPerMillionUsd": input_price_per_million, "outputPerMillionUsd": output_price_per_million},
        "failureTypes": dict(sorted(failure_types.items())),
        "queueSha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_json_bytes(report))
    return report
