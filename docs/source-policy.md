# Source acceptance policy

A source is eligible for research only after registration. Acquisition must identify a stable publisher, retrieval URL, update policy, immutable snapshot identity, expected media type, limits, and attribution.

A source is eligible for a public build only when the registry independently records verifiable redistribution terms. The build predicate is identity-based: `license.redistributable is True`. Missing flags and strings such as `"true"` are invalid. A license page digest proves what was reviewed; it does not convert restrictive terms into permission.

Evidence records contain the smallest lawful factual assertion: source ID, source record locator, level, capture time, snapshot digest, and optional lawful quote. Quotes are omitted unless redistribution is affirmatively allowed. Robots policy and rate limits are respected but are not substitutes for copyright permission.

Registry review must be repeated when license evidence, publisher identity, acquisition endpoint, or content digest changes. Previously accepted bytes remain pinned; a changed source cannot silently replace them.
