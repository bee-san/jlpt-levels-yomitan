# Schema provenance

The Yomitan target was researched against `yomidevs/yomitan` commit `d34832d756e05dc00945e5b7d7ebc80963299a7a` (retrieved 2026-09-15):

- `ext/data/schemas/dictionary-term-meta-bank-v3-schema.json`
- `ext/data/schemas/dictionary-index-schema.json`
- `docs/making-yomitan-dictionaries.md`

The term-meta v3 schema permits a frequency datum with `reading` and a `frequency` object containing numeric `value` and optional string `displayValue`. The index schema permits `frequencyMode` values `rank-based` and `occurrence-based`. This project chooses reading-qualified objects and `rank-based`; its project schema is intentionally stricter than upstream. Exact upstream schema bytes and `SHA256SUMS` are vendored under `schemas/vendor/yomitan/d34832d756e05dc00945e5b7d7ebc80963299a7a/`.

Jitendex repository identity is `https://github.com/Jitendex/Jitendex`; its currently advertised software license is AGPL-3.0. This fact does not establish licensing of every upstream data component. A later acquisition task must pin and audit the exact downloadable dictionary and its bundled attribution before redistribution.
