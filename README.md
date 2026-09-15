# JLPT Levels for Yomitan

A reproducible Yomitan term-metadata dictionary assigning every normalized Jitendex `(written form, reading)` lexeme to N5, N4, N3, N2, N1, or N0.

N0 is the project-defined “harder than N1” band, not an official JLPT level and never a placeholder for unknown or unassigned items. Every lexeme receives a best-estimate N5–N0 band. Direct source evidence, conflicts, reproducible inference, isolated residual adjudication, confidence, and licensing are retained in machine-readable audit data.

## Status

Architecture and contracts are frozen; acquisition and classification are not yet implemented. `config/sources.json` therefore fails closed with Jitendex redistribution marked unknown. No dictionary artifact is claimed yet.

## Developer quick start

```sh
python -m venv .venv
. .venv/bin/activate
make bootstrap
make check
jlpt-levels --help
```

Key interfaces:

- `schemas/`: versioned lexical, classification, source, artifact, and strict Yomitan-bank contracts.
- `examples/manifest.json`: positive and deliberately invalid contract fixtures.
- `config/sources.json`: source registry; public inclusion requires verified redistribution.
- `docs/architecture.md`: pipeline, identity, N0 semantics, conflicts, deterministic artifacts, and Yomitan encoding.
- `docs/source-policy.md`: acquisition and licensing policy.

Software is MIT-licensed. Source data and generated data are governed independently by their recorded source licenses; the MIT license does not grant redistribution rights to third-party data.
