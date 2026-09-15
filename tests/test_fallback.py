from __future__ import annotations

import json
from pathlib import Path

import pytest

from jlpt_levels.fallback import (
    FallbackError,
    POLICY_NAME,
    POLICY_VERSION,
    evaluate_grouped_holdout,
    fit_classifier,
    predict_files,
    train_files,
)


def _row(
    term: str,
    reading: str,
    level: str | None,
    group: str,
    *,
    kanji_level: str | None = None,
    commonness_rank: int | None = None,
    morphology: tuple[str, ...] = (),
) -> dict:
    component = []
    if kanji_level is not None:
        component.append(
            {
                "character": term[0],
                "jlptLevel": kanji_level,
                "schoolGrade": 8 if kanji_level == "N1" else 2,
                "frequencyRank": 2200 if kanji_level == "N1" else 200,
                "sources": ["fixture-kanji"],
            }
        )
    result = {
        "lexemeId": f"sha256:{len(term):064x}",
        "term": term,
        "reading": reading,
        "jitendexUpstreamIds": [group],
        "features": {
            "componentKanji": component,
            "commonnessRank": commonness_rank,
            "morphology": list(morphology),
            "orthography": ["kana-only"] if not component else ["kanji"],
            "senseTags": [],
        },
    }
    if level is not None:
        result["directLevel"] = level
    return result


def test_classifier_uses_combined_features_and_abstains_out_of_domain() -> None:
    rows = [
        _row("学校", "がっこう", "N5", "seq:1", kanji_level="N5", commonness_rank=100, morphology=("noun",)),
        _row("毎日", "まいにち", "N5", "seq:2", kanji_level="N5", commonness_rank=120, morphology=("noun",)),
        _row("朦朧", "もうろう", "N1", "seq:3", kanji_level="N1", commonness_rank=9000, morphology=("noun",)),
        _row("齟齬", "そご", "N1", "seq:4", kanji_level="N1", commonness_rank=11000, morphology=("noun",)),
    ]
    model = fit_classifier(rows, min_token_count=1, confidence_threshold=0.70)

    easy = model.predict(_row("校庭", "こうてい", None, "seq:5", kanji_level="N5", commonness_rank=150, morphology=("noun",)))
    hard = model.predict(_row("齟齬", "そご", None, "seq:6", kanji_level="N1", commonness_rank=10000, morphology=("noun",)))
    unknown = model.predict(_row("かな", "かな", None, "seq:7"))

    assert easy["level"] == "N5"
    assert hard["level"] == "N1"
    assert easy["policy"] == {"name": POLICY_NAME, "version": POLICY_VERSION}
    assert hard["features"]["maximumComponentKanjiLevel"] == "N1"
    assert unknown["level"] is None
    assert unknown["abstain"] is True
    assert unknown["reason"] == "insufficient-feature-support"


def test_advanced_kanji_is_evidence_not_a_hard_assignment() -> None:
    rows = [
        _row("易一", "やさしい", "N5", "seq:1", kanji_level="N1", commonness_rank=50, morphology=("common-exception",)),
        _row("易二", "やさしい", "N5", "seq:2", kanji_level="N1", commonness_rank=60, morphology=("common-exception",)),
        _row("難一", "むずかしい", "N1", "seq:3", kanji_level="N1", commonness_rank=9000, morphology=("rare",)),
        _row("難二", "むずかしい", "N1", "seq:4", kanji_level="N1", commonness_rank=10000, morphology=("rare",)),
    ]
    model = fit_classifier(rows, min_token_count=1, confidence_threshold=0.60)
    prediction = model.predict(
        _row("易三", "やさしい", None, "seq:5", kanji_level="N1", commonness_rank=55, morphology=("common-exception",))
    )
    assert prediction["level"] == "N5"
    assert prediction["features"]["maximumComponentKanjiLevel"] == "N1"


def test_grouped_holdout_is_deterministic_disjoint_and_reports_confusion() -> None:
    rows = []
    for index in range(1, 61):
        level = "N5" if index % 2 else "N1"
        rows.append(
            _row(
                f"語{index}",
                f"ご{index}",
                level,
                f"seq:{index // 2}",
                kanji_level=level,
                commonness_rank=100 if level == "N5" else 9000,
            )
        )
    first = evaluate_grouped_holdout(rows, holdout_fraction=0.25, split_salt="fixture", min_token_count=1)
    second = evaluate_grouped_holdout(rows, holdout_fraction=0.25, split_salt="fixture", min_token_count=1)

    assert first == second
    assert set(first["split"]["trainGroups"]).isdisjoint(first["split"]["holdoutGroups"])
    assert first["split"]["leakageGroups"] == []
    assert first["split"]["leakageUpstreamIds"] == []
    assert first["counts"]["directRows"] == 60
    assert first["counts"]["holdoutRows"] > 0
    assert first["counts"]["predicted"] + first["counts"]["abstained"] == first["counts"]["holdoutRows"]
    assert set(first["confusion"]) == {"N5", "N4", "N3", "N2", "N1"}
    assert first["policy"] == {"name": POLICY_NAME, "version": POLICY_VERSION}


def test_overlapping_identity_sets_remain_in_one_holdout_component() -> None:
    rows = [
        _row("甲", "こう", "N5", "seq:a", kanji_level="N5", commonness_rank=100),
        _row("乙", "おつ", "N5", "seq:b", kanji_level="N5", commonness_rank=100),
        _row("丙", "へい", "N1", "seq:c", kanji_level="N1", commonness_rank=9000),
        _row("丁", "てい", "N1", "seq:d", kanji_level="N1", commonness_rank=9000),
    ]
    rows[0]["jitendexUpstreamIds"] = ["seq:a", "seq:b"]
    rows[1]["jitendexUpstreamIds"] = ["seq:b", "seq:c"]
    report = evaluate_grouped_holdout(rows, holdout_fraction=0.5, split_salt="components", min_token_count=1)
    assert report["split"]["leakageUpstreamIds"] == []


def test_training_rejects_n0_labels_and_unattributed_kanji_features() -> None:
    with pytest.raises(FallbackError, match="direct training labels must be N5-N1"):
        fit_classifier([_row("語", "ご", "N0", "seq:1")])
    bad = _row("語", "ご", "N5", "seq:1", kanji_level="N5")
    bad["features"]["componentKanji"][0]["sources"] = []
    with pytest.raises(FallbackError, match="component kanji evidence requires sources"):
        fit_classifier([bad])


def test_model_round_trip_is_canonical_and_prediction_identical(tmp_path: Path) -> None:
    rows = [
        _row("学校", "がっこう", "N5", "seq:1", kanji_level="N5", commonness_rank=100),
        _row("齟齬", "そご", "N1", "seq:2", kanji_level="N1", commonness_rank=10000),
    ]
    model = fit_classifier(rows, min_token_count=1, confidence_threshold=0.5)
    path = tmp_path / "model.json"
    model.write(path)
    restored = type(model).read(path)
    target = _row("校", "こう", None, "seq:3", kanji_level="N5", commonness_rank=120)
    assert restored.predict(target) == model.predict(target)
    assert path.read_bytes().endswith(b"\n")
    assert json.loads(path.read_text())["policy"]["version"] == POLICY_VERSION


def test_file_pipeline_trains_evaluates_and_routes_abstentions(tmp_path: Path) -> None:
    rows = [
        _row("学校", "がっこう", "N5", "seq:1", kanji_level="N5", commonness_rank=100),
        _row("毎日", "まいにち", "N5", "seq:2", kanji_level="N5", commonness_rank=120),
        _row("齟齬", "そご", "N1", "seq:3", kanji_level="N1", commonness_rank=10000),
        _row("朦朧", "もうろう", "N1", "seq:4", kanji_level="N1", commonness_rank=9000),
    ]
    training = tmp_path / "training.jsonl"
    training.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    model_path, report_path = tmp_path / "model.json", tmp_path / "report.json"
    report = train_files(training, model_path, report_path, holdout_fraction=0.25, min_token_count=1)
    assert json.loads(report_path.read_text()) == report

    residual = tmp_path / "residual.jsonl"
    residual.write_text(
        json.dumps(_row("かな", "かな", None, "seq:5"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    inferred, adjudication = tmp_path / "inferred.jsonl", tmp_path / "adjudication.jsonl"
    counts = predict_files(model_path, residual, inferred, adjudication)
    assert counts == {"input": 1, "inferred": 0, "adjudicationRequired": 1}
    assert inferred.read_text() == ""
    routed = json.loads(adjudication.read_text())
    assert routed["method"] == "adjudication-required"
    assert routed["inference"]["reason"] == "insufficient-feature-support"
