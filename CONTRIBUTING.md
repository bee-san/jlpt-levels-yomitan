# Contributing

All changes must preserve the contracts in `docs/architecture.md` and pass `make check`.

## Setup

```sh
python -m venv .venv
. .venv/bin/activate
make bootstrap
make check
```

## Data and source changes

1. Register a source before acquiring it. Pin an immutable revision and SHA-256 digest.
2. Record license evidence. `redistributable` must be literal `true` before source content may enter a public artifact; unknown or reported-only permission fails closed.
3. Keep raw downloaded bytes out of Git unless their license explicitly permits redistribution. Commit lawful references, digests, normalized evidence, and derived labels only as allowed.
4. Never label N0 as official or use it for unknown/unassigned items; it means evidence-supported difficulty beyond N1. Never turn inference or adjudication into direct evidence.
5. Explain classification changes and regenerate deterministic audit artifacts.

Schema changes require a positive fixture, a deliberately invalid fixture proving the new boundary, documentation, and a version bump of the affected `$id`.
