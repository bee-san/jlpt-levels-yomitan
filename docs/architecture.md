# Architecture and frozen contracts

## Pipeline

The pipeline is a sequence of immutable, canonical-JSON stages:

1. `acquire`: fetch only registered sources, enforce byte/time limits, cache exact bytes, and verify pinned SHA-256.
2. `inventory`: derive every Jitendex `(term, reading)` lexeme from a pinned dictionary ZIP. No lexical source row is silently dropped.
3. `evidence`: normalize attributable source assertions without copying unlicensed prose.
4. `classify`: resolve direct evidence first, retain disagreements, then run versioned conservative inference where no direct label exists; send only unresolved residuals to isolated Bedrock Luna adjudication.
5. `audit`: require exactly one classification per inventory lexeme and emit coverage, conflicts, methods, confidence, and source/license reports.
6. `package`: emit sorted Yomitan `term_meta_bank_N.json`, `index.json`, audit JSON, and checksums from one frozen run manifest.

Each stage validates its input and output. Canonical JSON uses UTF-8, LF, sorted object keys, compact separators, and one terminal newline. Arrays have contract-defined sort keys. ZIP members use a fixed timestamp and mode. A release is identified by the SHA-256 of the ZIP, never by a mutable path alone.

## Lexical identity

`lexemeId` is `sha256:` plus lowercase SHA-256 of canonical JSON `[term,reading]`. `term` is the exact Jitendex lookup expression after its own normalization; `reading` is the exact Jitendex reading. Empty reading is forbidden: kana-only entries repeat the term as reading. Multi-reading entries are distinct lexemes. Source-local IDs and Jitendex sequence numbers are provenance, not identity.

## Classification

Every lexeme has one `level` in `N5..N0` and one `method`:

- `direct`: at least one attributable vocabulary source asserts the selected N5–N1 level.
- `inferred`: no direct assertion exists; a named, versioned policy produced the best-estimate N5–N0 level from recorded features.
- `adjudicated`: reproducible inference remained uncertain; an item-isolated or tiny-batch Bedrock Luna run returned strict JSON, with exact input/output digests and model/prompt provenance retained.

N0 means the evidence supports difficulty beyond N1. It is not official and never means unknown, unassigned, or merely absent from an N5–N1 source. Every N0 record must carry at least one concrete `features.postN1DifficultySignals` item. Every lexeme receives a best-estimate band; uncertainty is expressed by `method`, `confidence`, recorded features, and adjudication provenance rather than by selecting N0.

Confidence is a calibrated decimal in `[0,1]`, not a source truth score. Direct conflicts are never erased: all assertions remain in `evidence`, `conflict=true`, and resolution records the deterministic policy and selected assertion IDs. Inference and adjudication may not override direct evidence. Each adjudication uses a fresh context, a batch of at most three tightly related lexemes, strict schema-validated JSON, and pinned provider/model/prompt identity; parse failures remain failed work rather than becoming N0.

## Yomitan encoding

The public dictionary is format 3, `frequencyMode: rank-based`. Each lexeme emits:

```json
["食べる","freq",{"reading":"たべる","frequency":{"value":5,"displayValue":"N5"}}]
```

Sortable values are `N5=5`, `N4=4`, `N3=3`, `N2=2`, `N1=1`, `N0=0`. This is an ordinal band, not corpus frequency. The reading-qualified object is mandatory so written forms with multiple readings do not collide. Bank filenames are `term_meta_bank_1.json`, etc., at ZIP root. Requirements are pinned to Yomitan schema commit `d34832d756e05dc00945e5b7d7ebc80963299a7a`; upstream schema bytes and digest must be vendored before release validation.

## Public-source policy

Registry records distinguish `licenseEvidence` from a license claim. Public redistribution requires `license.redistributable is true`, an SPDX expression or explicit custom terms, a stable evidence URL/path, and a captured evidence digest. `false`, missing, reported permission, or unknown excludes source content from public artifacts. Metadata facts may be regenerated from lawful references only where legally allowed; excluded source prose is never copied. Software is MIT-licensed; data remains under each source's license and must be attributed separately.
