# Project contract: JLPT Levels for Yomitan

## Goal
Create and publish a reproducible, self-updating Yomitan term-frequency/metadata dictionary assigning every lexical entry covered by the current Jitendex build to exactly one band: N5, N4, N3, N2, N1, or N0.

## Truthfulness
- N5–N1 assignments must be backed by attributable vocabulary-list evidence wherever available.
- N0 is a project-defined post-N1 difficulty band: it means the best available evidence supports “harder than N1,” not unknown, unassigned, or merely absent from N5–N1 lists. It is not an official JLPT level.
- Where word-level evidence is absent, use a documented conservative inference based on component kanji levels, kana/commonness, readings, senses, and other reproducible features. If uncertainty remains, adjudicate each lexeme or tiny related batch in a fresh Bedrock Luna context with strict JSON. Every lexeme still receives a best-estimate N5–N0 band; uncertainty belongs in method, confidence, and provenance, never in the N0 label. Do not present inferred or adjudicated labels as official.
- Preserve provenance, confidence, method, source timestamps, and conflicts in machine-readable audit data.
- Cover every normalized Jitendex lexeme key (written form + reading), including kana-only and multi-reading entries. No silent drops.

## Artifact
- A Yomitan-compatible frequency/term-meta dictionary ZIP with N5–N0 encoded as stable sortable values and useful display labels.
- Deterministic source, tests, audit reports, checksums, and release assets.
- A public GitHub repository under the authenticated account, subject to a fail-closed license audit; do not redistribute source content whose terms forbid it.

## Updating
- Scheduled GitHub Actions checks upstream Jitendex and approved JLPT sources, rebuilds deterministically, validates, reports diffs/regressions, and publishes immutable versioned releases only after all gates pass.
- Pin source identities/checksums and retain raw evidence or lawful references sufficient to reproduce each classification.

## Quality bar
- Exact Jitendex census coverage, schema validation, real Yomitan import compatibility, deterministic rebuilds, no unexplained level regressions, and independent review.
- Online-source acquisition must be robust, respectful, cached, rate-limited, and license-aware.
- For ambiguous residual items, spend cheap-model tokens freely: isolate each item or tiny related batch in a fresh Luna context, require strict JSON, and aggregate reproducibly rather than reviewing the whole corpus in one decaying context.
