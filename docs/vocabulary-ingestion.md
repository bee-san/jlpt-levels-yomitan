# Vocabulary evidence ingestion

The approved-source registry is `config/vocabulary-sources.json`. It currently contains the audited English Wiktionary JLPT Appendix adapter; adding an adapter without first adding an approved, pinned source is forbidden. These community lists are direct attributable evidence, not official JLPT specifications.

`python -m jlpt_levels ingest-vocabulary` fetches all five pinned revisions in one serial MediaWiki Action API request, applies a descriptive User-Agent, enforces a byte limit, retries transient failures with `Retry-After`/bounded backoff, atomically caches exact response bytes by request URL, and emits canonical UTF-8 JSONL. `--offline` refuses cache misses. The parser fails closed on omitted/extra revisions, title drift, malformed rows, or any stated-count mismatch.

Each evidence row retains the spelling and reading separately, including kana-only rows (term repeats reading), plus source row handle, pinned revision URL, exact page-wikitext SHA-256, capture timestamp, license, asserted level, and a deterministic evidence ID. Meanings and frequency are deliberately excluded: neither is needed for level evidence and retaining creative glosses would enlarge the CC BY-SA-derived surface.

Outputs:

- `data/evidence/vocabulary.jsonl`: canonical records sorted by `(term, reading, level, sourceRecord)`.
- `data/evidence/vocabulary-report.json`: source/level counts, exact snapshots, unique lexeme count, and bounded conflict samples.

Run live acquisition explicitly with a contactable User-Agent:

```sh
JLPT_LEVELS_USER_AGENT='JLPTLevelsYomitan/0.1 (https://github.com/OWNER/REPO; EMAIL)' make ingest-vocabulary
make ingest-vocabulary-offline
```

Raw cached responses are local build inputs and ignored by Git. Public reuse of the derived records must retain English Wiktionary attribution and CC BY-SA 4.0 terms.
