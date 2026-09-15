from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .identity import canonical_json_bytes

POLICY_NAME = "kanji-linguistic-fallback"
POLICY_VERSION = "1.0.0"
LEVELS = ("N5", "N4", "N3", "N2", "N1")
_LEVEL_ORDER = {level: index for index, level in enumerate(LEVELS)}


class FallbackError(ValueError):
    pass


def _bucket(value: int | None, boundaries: tuple[int, ...]) -> str:
    if value is None:
        return "missing"
    for boundary in boundaries:
        if value <= boundary:
            return f"le-{boundary}"
    return f"gt-{boundaries[-1]}"


def _is_kana(character: str) -> bool:
    codepoint = ord(character)
    return 0x3040 <= codepoint <= 0x30FF


def _validate_row(row: dict, *, training: bool) -> None:
    for field in ("lexemeId", "term", "reading", "jitendexUpstreamIds", "features"):
        if field not in row:
            raise FallbackError(f"row lacks {field}")
    if not isinstance(row["jitendexUpstreamIds"], list) or not row["jitendexUpstreamIds"]:
        raise FallbackError("jitendexUpstreamIds must be a non-empty array")
    if training and row.get("directLevel") not in LEVELS:
        raise FallbackError("direct training labels must be N5-N1")
    features = row["features"]
    if not isinstance(features, dict):
        raise FallbackError("features must be an object")
    for component in features.get("componentKanji", []):
        if not isinstance(component, dict) or not component.get("sources"):
            raise FallbackError("component kanji evidence requires sources")
        if component.get("jlptLevel") is not None and component["jlptLevel"] not in LEVELS:
            raise FallbackError("component kanji level must be N5-N1 or null")


def _tokens(row: dict) -> tuple[str, ...]:
    features = row["features"]
    term = row["term"]
    reading = row["reading"]
    components = features.get("componentKanji", [])
    tokens: list[str] = []
    levels = [item["jlptLevel"] for item in components if item.get("jlptLevel") in LEVELS]
    if levels:
        tokens.append("kanji-max=" + max(levels, key=_LEVEL_ORDER.__getitem__))
        tokens.extend("kanji-level=" + level for level in sorted(set(levels), key=_LEVEL_ORDER.__getitem__))
    grades = [item.get("schoolGrade") for item in components if isinstance(item.get("schoolGrade"), int)]
    frequencies = [item.get("frequencyRank") for item in components if isinstance(item.get("frequencyRank"), int)]
    tokens.append("grade-max=" + _bucket(max(grades) if grades else None, (2, 6, 8, 10)))
    tokens.append("kanji-frequency=" + _bucket(max(frequencies) if frequencies else None, (250, 1000, 2500)))
    tokens.append("commonness=" + _bucket(features.get("commonnessRank"), (500, 2000, 10000)))
    tokens.append("length=" + _bucket(len(term), (1, 2, 4, 8)))
    tokens.append("reading-length=" + _bucket(len(reading), (2, 4, 8, 16)))
    kana_count = sum(_is_kana(character) for character in term)
    tokens.append("orthographic-kana-ratio=" + str(round(kana_count / len(term), 1)))
    tokens.extend("morphology=" + item for item in sorted(set(features.get("morphology", []))))
    tokens.extend("orthography=" + item for item in sorted(set(features.get("orthography", []))))
    tokens.extend("sense=" + item for item in sorted(set(features.get("senseTags", []))))
    return tuple(sorted(set(tokens)))


def _substantive_support(row: dict) -> bool:
    features = row["features"]
    return bool(
        features.get("componentKanji")
        or features.get("commonnessRank") is not None
        or features.get("morphology")
        or features.get("orthography")
        or features.get("senseTags")
    )


def _feature_summary(row: dict, tokens: tuple[str, ...]) -> dict:
    components = row["features"].get("componentKanji", [])
    levels = [item["jlptLevel"] for item in components if item.get("jlptLevel") in LEVELS]
    result = {
        "featureTokens": list(tokens),
        "kanaOnly": all(_is_kana(character) for character in row["term"]),
    }
    if levels:
        result["maximumComponentKanjiLevel"] = max(levels, key=_LEVEL_ORDER.__getitem__)
    signals = row["features"].get("postN1DifficultySignals", [])
    if signals:
        result["postN1DifficultySignals"] = list(signals)
    return result


@dataclass(frozen=True)
class FallbackModel:
    class_counts: dict[str, int]
    token_counts: dict[str, dict[str, int]]
    vocabulary: tuple[str, ...]
    min_token_count: int
    confidence_threshold: float

    def predict(self, row: dict) -> dict:
        _validate_row(row, training=False)
        tokens = _tokens(row)
        summary = _feature_summary(row, tokens)
        base = {
            "lexemeId": row["lexemeId"],
            "policy": {"name": POLICY_NAME, "version": POLICY_VERSION},
            "features": summary,
        }
        if not _substantive_support(row):
            return {**base, "level": None, "confidence": 0.0, "abstain": True, "reason": "insufficient-feature-support"}
        known = [token for token in tokens if token in self.vocabulary]
        if not known:
            return {**base, "level": None, "confidence": 0.0, "abstain": True, "reason": "out-of-domain-features"}
        total_rows = sum(self.class_counts.values())
        scores: dict[str, float] = {}
        for level in LEVELS:
            class_rows = self.class_counts.get(level, 0)
            prior = (class_rows + 1) / (total_rows + len(LEVELS))
            score = math.log(prior)
            counts = self.token_counts.get(level, {})
            denominator = sum(counts.values()) + 2 * len(self.vocabulary)
            for token in known:
                score += math.log((counts.get(token, 0) + 2) / denominator)
            scores[level] = score
        peak = max(scores.values())
        probabilities = {level: math.exp(score - peak) for level, score in scores.items()}
        denominator = sum(probabilities.values())
        probabilities = {level: value / denominator for level, value in probabilities.items()}
        level = max(LEVELS, key=lambda item: (probabilities[item], -_LEVEL_ORDER[item]))
        confidence = probabilities[level]
        signals = row["features"].get("postN1DifficultySignals", [])
        if level == "N1" and len(set(signals)) >= 2 and confidence >= self.confidence_threshold:
            level = "N0"
        if confidence < self.confidence_threshold:
            return {**base, "level": None, "confidence": round(confidence, 6), "abstain": True, "reason": "below-confidence-threshold"}
        return {**base, "level": level, "confidence": round(confidence, 6), "abstain": False}

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "policy": {"name": POLICY_NAME, "version": POLICY_VERSION},
            "parameters": {
                "confidenceThreshold": self.confidence_threshold,
                "minTokenCount": self.min_token_count,
                "smoothingAlpha": 2,
            },
            "classCounts": self.class_counts,
            "tokenCounts": self.token_counts,
            "vocabulary": list(self.vocabulary),
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(self.to_dict()))

    @classmethod
    def read(cls, path: Path) -> "FallbackModel":
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("policy") != {"name": POLICY_NAME, "version": POLICY_VERSION}:
            raise FallbackError("model policy identity is unsupported")
        parameters = value["parameters"]
        return cls(
            class_counts={key: int(item) for key, item in value["classCounts"].items()},
            token_counts={key: {token: int(count) for token, count in counts.items()} for key, counts in value["tokenCounts"].items()},
            vocabulary=tuple(value["vocabulary"]),
            min_token_count=int(parameters["minTokenCount"]),
            confidence_threshold=float(parameters["confidenceThreshold"]),
        )


def fit_classifier(
    rows: Iterable[dict], *, min_token_count: int = 2, confidence_threshold: float = 0.62
) -> FallbackModel:
    if min_token_count < 1:
        raise FallbackError("min_token_count must be positive")
    checked = list(rows)
    if not checked:
        raise FallbackError("training corpus is empty")
    token_frequency: Counter[str] = Counter()
    row_tokens: list[tuple[dict, tuple[str, ...]]] = []
    for row in checked:
        _validate_row(row, training=True)
        tokens = _tokens(row)
        token_frequency.update(tokens)
        row_tokens.append((row, tokens))
    vocabulary = tuple(sorted(token for token, count in token_frequency.items() if count >= min_token_count))
    if not vocabulary:
        raise FallbackError("no feature tokens meet min_token_count")
    allowed = set(vocabulary)
    class_counts: Counter[str] = Counter()
    token_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row, tokens in row_tokens:
        level = row["directLevel"]
        class_counts[level] += 1
        token_counts[level].update(token for token in tokens if token in allowed)
    return FallbackModel(
        class_counts={level: class_counts[level] for level in LEVELS},
        token_counts={level: dict(sorted(token_counts[level].items())) for level in LEVELS},
        vocabulary=vocabulary,
        min_token_count=min_token_count,
        confidence_threshold=confidence_threshold,
    )


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise FallbackError(f"{path}:{line_number}: invalid JSON") from error
            if not isinstance(value, dict):
                raise FallbackError(f"{path}:{line_number}: row must be an object")
            records.append(value)
    return records


def train_files(
    training_path: Path, model_path: Path, report_path: Path, *, holdout_fraction: float = 0.2,
    split_salt: str = "v1", min_token_count: int = 2, confidence_threshold: float = 0.62,
) -> dict:
    rows = _read_jsonl(training_path)
    report = evaluate_grouped_holdout(
        rows, holdout_fraction=holdout_fraction, split_salt=split_salt,
        min_token_count=min_token_count, confidence_threshold=confidence_threshold,
    )
    model = fit_classifier(rows, min_token_count=min_token_count, confidence_threshold=confidence_threshold)
    model.write(model_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_json_bytes(report))
    return report


def predict_files(model_path: Path, residual_path: Path, inferred_path: Path, adjudication_path: Path) -> dict:
    model = FallbackModel.read(model_path)
    rows = _read_jsonl(residual_path)
    inferred_path.parent.mkdir(parents=True, exist_ok=True)
    adjudication_path.parent.mkdir(parents=True, exist_ok=True)
    inferred_count = 0
    adjudication_count = 0
    with inferred_path.open("wb") as inferred, adjudication_path.open("wb") as adjudication:
        for row in rows:
            result = model.predict(row)
            if result["abstain"]:
                adjudication.write(canonical_json_bytes({
                    "features": row["features"],
                    "inference": result,
                    "lexemeId": row["lexemeId"],
                    "method": "adjudication-required",
                    "reading": row["reading"],
                    "term": row["term"],
                }))
                adjudication_count += 1
            else:
                inferred.write(canonical_json_bytes({
                    "confidence": result["confidence"],
                    "conflict": False,
                    "evidence": [],
                    "features": result["features"],
                    "level": result["level"],
                    "lexemeId": row["lexemeId"],
                    "method": "inferred",
                    "policy": result["policy"],
                }))
                inferred_count += 1
    return {"input": len(rows), "inferred": inferred_count, "adjudicationRequired": adjudication_count}


def _component_assignments(rows: list[dict]) -> list[str]:
    parents: dict[str, str] = {}

    def root(item: str) -> str:
        parents.setdefault(item, item)
        if parents[item] != item:
            parents[item] = root(parents[item])
        return parents[item]

    def union(left: str, right: str) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            first, second = sorted((left_root, right_root))
            parents[second] = first

    for row in rows:
        identities = sorted(set(row["jitendexUpstreamIds"]))
        for identity in identities[1:]:
            union(identities[0], identity)
    return [root(sorted(set(row["jitendexUpstreamIds"]))[0]) for row in rows]


def evaluate_grouped_holdout(
    rows: Iterable[dict], *, holdout_fraction: float = 0.2, split_salt: str = "v1", min_token_count: int = 2,
    confidence_threshold: float = 0.62,
) -> dict:
    checked = list(rows)
    if not 0 < holdout_fraction < 1:
        raise FallbackError("holdout_fraction must be between zero and one")
    for row in checked:
        _validate_row(row, training=True)
    assignments = _component_assignments(checked)
    groups = sorted(set(assignments))
    if len(groups) < 2:
        raise FallbackError("grouped holdout requires at least two disconnected identity groups")
    holdout_groups = {
        group for group in groups
        if int.from_bytes(hashlib.sha256(f"{split_salt}\0{group}".encode()).digest()[:8], "big") / 2**64 < holdout_fraction
    }
    if not holdout_groups or holdout_groups == set(groups):
        count = max(1, min(len(groups) - 1, round(len(groups) * holdout_fraction)))
        holdout_groups = set(sorted(groups, key=lambda group: hashlib.sha256(f"{split_salt}\0{group}".encode()).digest())[:count])
    train = [row for row, group in zip(checked, assignments, strict=True) if group not in holdout_groups]
    holdout = [row for row, group in zip(checked, assignments, strict=True) if group in holdout_groups]
    model = fit_classifier(train, min_token_count=min_token_count, confidence_threshold=confidence_threshold)
    confusion = {actual: {predicted: 0 for predicted in (*LEVELS, "ABSTAIN")} for actual in LEVELS}
    predicted = 0
    abstained = 0
    for row in holdout:
        result = model.predict(row)
        label = result["level"] or "ABSTAIN"
        confusion[row["directLevel"]][label] += 1
        if result["abstain"]:
            abstained += 1
        else:
            predicted += 1
    train_groups = sorted(set(groups) - holdout_groups)
    held_groups = sorted(holdout_groups)
    train_upstream = {identity for row in train for identity in row["jitendexUpstreamIds"]}
    held_upstream = {identity for row in holdout for identity in row["jitendexUpstreamIds"]}
    return {
        "schemaVersion": 1,
        "policy": {"name": POLICY_NAME, "version": POLICY_VERSION},
        "split": {
            "salt": split_salt,
            "holdoutFraction": holdout_fraction,
            "trainGroups": train_groups,
            "holdoutGroups": held_groups,
            "leakageGroups": sorted(set(train_groups) & set(held_groups)),
            "leakageUpstreamIds": sorted(train_upstream & held_upstream),
        },
        "counts": {
            "directRows": len(checked), "trainRows": len(train), "holdoutRows": len(holdout),
            "predicted": predicted, "abstained": abstained,
        },
        "abstentionRate": round(abstained / len(holdout), 6),
        "confusion": confusion,
    }
