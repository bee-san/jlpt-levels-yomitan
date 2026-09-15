# Lexical evidence matching

`match-vocabulary` joins evidence to the exact pinned Jitendex lexeme census and writes two deterministic artifacts:

- `data/derived/vocabulary-matches.jsonl`: accepted evidence-to-lexeme edges;
- `data/derived/vocabulary-match-report.json`: disjoint `exactMatch`, `normalizedMatch`, `ambiguous`, and `unmatched` sets with counts.

Every evidence record has exactly one outcome. Duplicate evidence identities, malformed JSONL, forged lexeme identities, and duplicate lexemes fail closed. Iteration marks without a valid local expansion remain literal rather than being guessed.

## Conservative identity rules

Exact `(term, reading)` is preferred. Normalized matching applies Unicode NFC, katakana-to-hiragana folding, and expansion of Japanese iteration marks. It does not delete punctuation, spaces, okurigana, or characters and it does not guess readings.

Orthographic variants are expanded only when Jitendex itself places them under a shared absolute sequence identity and their normalized readings agree. This supports source-declared kana/kanji and okurigana variants without treating spelling similarity as evidence. Candidates with the same normalized surface but disconnected Jitendex identities are `ambiguous`; no label edge is emitted. Different readings of a homograph remain different lexemes.

An unmatched report is expected input to later inference/adjudication. It is never interpreted as N0: N0 remains the evidence-backed post-N1 band defined in `PROJECT_SPEC.md`.
