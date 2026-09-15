from __future__ import annotations

import json
from pathlib import Path

from jlpt_levels.adjudication import MODEL, AdjudicationError, adjudicate_item, build_prompt, run_queue


class FakeBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def invoke(self, prompt: str, *, max_tokens: int):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return {"text": json.dumps(response, ensure_ascii=False), "usage": {"inputTokens": 101, "outputTokens": 17, "totalTokens": 118}, "requestId": "test"}


def item():
    return {"lexemeId": "lx_test", "term": "語彙", "reading": "ごい", "evidenceReferences": ["jmdict:1"], "features": {"frequencyRank": 123}}


def decision(label="N2", abstain=False):
    return {"label": label, "confidence": 0.8, "rationale": "bounded evidence", "evidenceReferences": ["jmdict:1"], "abstain": abstain}


def test_prompt_is_deterministic_and_isolated():
    first, digest = build_prompt({**item(), "secret": "must-not-cross-boundary"})
    second, second_digest = build_prompt(item())
    assert first == second
    assert digest == second_digest
    assert "secret" not in first
    assert MODEL in first
    assert "N0 is strictly harder than N1" in first


def test_retry_validate_cache_and_provenance(tmp_path: Path):
    backend = FakeBackend([RuntimeError("throttled"), decision()])
    found, metadata = adjudicate_item(item(), backend, tmp_path, sleep=lambda _: None)
    assert found is not None
    assert found["label"] == "N2"
    assert metadata["attempt"] == 2
    assert metadata["usage"]["inputTokens"] == 101
    cached, cached_metadata = adjudicate_item(item(), FakeBackend([]), tmp_path)
    assert cached == found
    assert cached_metadata["cached"] is True


def test_rejects_unknown_reference_and_unsubstantiated_n0(tmp_path: Path):
    unknown = decision()
    unknown["evidenceReferences"] = ["invented"]
    found, metadata = adjudicate_item(item(), FakeBackend([unknown]), tmp_path, retries=1)
    assert found is None
    assert metadata["attempts"][0]["errorType"] == "AdjudicationError"
    n0 = decision("N0")
    n0["evidenceReferences"] = []
    found, _ = adjudicate_item(item(), FakeBackend([n0]), tmp_path / "other", retries=1)
    assert found is None


def test_run_queue_is_one_item_per_request_and_resumable(tmp_path: Path):
    queue = tmp_path / "queue.jsonl"
    rows = [item(), {**item(), "lexemeId": "lx_second", "term": "臍を噛む", "reading": "ほぞをかむ"}]
    queue.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    backend = FakeBackend([decision(), decision("N1", abstain=True)])
    output, pending, report = tmp_path / "out.jsonl", tmp_path / "pending.jsonl", tmp_path / "report.json"
    result = run_queue(queue, output, pending, report, tmp_path / "cache", backend, concurrency=1, input_price_per_million=0.2, output_price_per_million=1.2)
    assert backend.calls == 2
    assert result["counts"] == {"input": 2, "completed": 1, "pending": 1, "failures": 0, "abstentions": 1, "requests": 2, "cacheHits": 0}
    assert result["tokens"]["inputTokens"] == 202
    assert abs(result["costUsd"] - (202 * 0.2 + 34 * 1.2) / 1_000_000) < 1e-12
    produced = json.loads(output.read_text())
    assert produced["level"] == "N2"
    assert produced["method"] == "adjudicated"
    assert produced["adjudication"]["model"] == MODEL
    assert json.loads(pending.read_text())["modelAbstained"] is True


def test_duplicate_queue_identity_fails_closed(tmp_path: Path):
    queue = tmp_path / "queue.jsonl"
    queue.write_text(json.dumps(item()) + "\n" + json.dumps(item()) + "\n")
    try:
        run_queue(queue, tmp_path / "o", tmp_path / "p", tmp_path / "r", tmp_path / "c", FakeBackend([]))
    except AdjudicationError as error:
        assert "duplicate" in str(error)
    else:
        raise AssertionError("duplicate queue unexpectedly accepted")
