# Kanji and linguistic fallback classifier

Policy identity: `kanji-linguistic-fallback` version `1.0.0`.

This stage handles lexemes that have no adequate word-level N5–N1 assertion. Its inputs are generated records, not bundled third-party datasets. Each component-kanji datum must retain at least one source identifier; records without attributable component evidence fail closed. The feature producer is responsible for recording the immutable source snapshot and lawful-use decision upstream.

## Input contract

Training JSONL contains one directly labeled record per lexeme. `directLevel` is N5–N1 only. N0 is never a training synonym for missing evidence. Residual JSONL uses the same shape without `directLevel`:

```json
{"lexemeId":"sha256:…","term":"齟齬","reading":"そご","jitendexUpstreamIds":["jitendex:sequence:…"],"directLevel":"N1","features":{"componentKanji":[{"character":"齟","jlptLevel":"N1","schoolGrade":8,"frequencyRank":2300,"sources":["kanji-snapshot-id"]}],"commonnessRank":9000,"morphology":["noun"],"orthography":["kanji"],"senseTags":[]}}
```

The deterministic tokenization uses component-kanji JLPT bands, school grade and frequency buckets; whole-word commonness; term and reading length; kana ratio; and morphology, orthography, and sense tags. Missing fields are represented explicitly. Feature values are categorical or bucketed to avoid pretending that incomparable source ranks are additive.

## Model and guardrails

The implementation is a smoothed categorical Naive Bayes model. It is intentionally inspectable: the canonical model JSON records class counts, vocabulary, per-level token counts, smoothing, minimum token support, confidence threshold, and policy identity.

Component kanji are evidence, never a hard assignment. A difficult character can raise the model's support for a difficult band, but commonness, morphology, reading and orthographic evidence can outweigh it. N0 is emitted only when the ordinary prediction is N1 with sufficient calibrated confidence and the residual record carries at least two explicit `postN1DifficultySignals`; absence or uncertainty can never produce N0.

Predictions below the configured confidence threshold, without substantive evidence, or entirely outside the fitted vocabulary abstain. `infer-fallback` writes abstentions to a separate `adjudication-required.jsonl` queue. Release builds use a zero confidence threshold because the product contract requires a best estimate for every lexeme; the emitted confidence preserves uncertainty instead of changing the label to N0. Any item that remains out of domain or lacks even reproducible orthographic support still fails into the item-isolated Bedrock Luna queue.

## Calibration without leakage

`train-fallback` holds out complete Jitendex upstream-identity groups. Every spelling/reading row sharing the same group is wholly in training or holdout, preventing lexical variants from crossing the boundary. Group assignment is a stable SHA-256 function of the checked-in split salt. The report records both group lists, an explicit leakage intersection, counts, abstention rate, and a full N5–N1 by predicted-level/ABSTAIN confusion matrix.

The final model is then fitted on all directly labeled rows; the untouched grouped holdout measures the policy before that refit. Re-running with identical canonical training bytes and parameters produces identical model and report bytes.

## Commands

```sh
PYTHONPATH=src python -m jlpt_levels train-fallback \
  --training data/derived/fallback-training.jsonl
PYTHONPATH=src python -m jlpt_levels infer-fallback \
  --residual data/derived/fallback-residual.jsonl
```

The checked-in classifier does not manufacture source data and does not ship source prose. A later feature-builder must bind every input feature to pinned lawful snapshots before a production classification can be claimed.
