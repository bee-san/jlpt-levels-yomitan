# Direct evidence resolution

`jlpt-levels resolve-direct` joins the complete evidence records back to the
matcher edges and writes deterministic classification JSONL plus a reviewable
audit JSON document.

The `direct-evidence-resolution` 1.0.0 policy does not vote by row count.
Exact `(term, reading)` evidence outranks conservative normalized evidence. At
the strongest tier available for a lexeme, every asserted level must agree or
the lexeme remains an explicit unresolved conflict for inference or isolated
adjudication. Lower-tier disagreement is retained, sets `conflict: true`, and
reduces confidence, but cannot overrule exact identity. Duplicate rows from one
source never count as independent corroboration.

Calibrated confidence is 0.90 for one exact source and 0.97 for two or more
independent exact sources; normalized evidence uses 0.75 and 0.85. Conflicting
weaker evidence subtracts 0.05. These are policy calibration values, not
empirical probabilities or claims of official JLPT status.

The audit records every vote with its match kind and full pinned provenance,
every selected evidence ID, all unresolved conflicts, and coverage by level,
source, method, and match kind. Lexemes without direct votes remain counted and
must proceed to deterministic inference and, where needed, item-isolated Luna
adjudication. They are never assigned N0 merely for lacking sourced evidence.
