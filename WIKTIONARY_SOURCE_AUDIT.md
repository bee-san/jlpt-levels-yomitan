# Wiktionary as a JLPT vocabulary-level source

Audit timestamp: 2026-09-15T17:12:47Z (UTC)

## Verdict

**Usable as a secondary, community-maintained candidate list; not an official or authoritative post-2010 JLPT specification.** English Wiktionary exposes five directly machine-readable Appendix pages (N1–N5), not a JLPT category hierarchy. The pages report 7,370 rows in total, with spelling, reading, English meaning, and an optional frequency rank. Because Wiktionary text is CC BY-SA 4.0/GFDL and the table includes creative English definitions, redistribution should be treated as CC BY-SA content with attribution and ShareAlike obligations. A registry may safely record Wiktionary as an optional/review source, but should not silently present its levels as official JLPT assignments.

## Exact source pages and structure

Landing page:

- https://en.wiktionary.org/wiki/Appendix:JLPT
- Permanent revision audited: https://en.wiktionary.org/w/index.php?title=Appendix:JLPT&oldid=87890832

The landing page says verbatim:

> “Vocabulary for Japanese Language Proficiency Test - 日本語能力試験 (にほんごのうりょくしけん, Nihongo Nōryoku Shiken)”

It links directly to:

| Level | Live page | Audited revision | Page's stated count | Last revision returned by API at audit time |
|---|---|---|---:|---|
| N5 | https://en.wiktionary.org/wiki/Appendix:JLPT/N5 | https://en.wiktionary.org/w/index.php?title=Appendix:JLPT/N5&oldid=85459359 | 667 | `2025-07-04T20:41:08Z` |
| N4 | https://en.wiktionary.org/wiki/Appendix:JLPT/N4 | https://en.wiktionary.org/w/index.php?title=Appendix:JLPT/N4&oldid=83724552 | 573 | `2025-01-25T09:53:56Z` |
| N3 | https://en.wiktionary.org/wiki/Appendix:JLPT/N3 | https://en.wiktionary.org/w/index.php?title=Appendix:JLPT/N3&oldid=84079087 | 1,677 | `2025-03-02T15:40:08Z` |
| N2 | https://en.wiktionary.org/wiki/Appendix:JLPT/N2 | https://en.wiktionary.org/w/index.php?title=Appendix:JLPT/N2&oldid=88447965 | 1,635 | `2025-12-09T09:10:03Z` |
| N1 | https://en.wiktionary.org/wiki/Appendix:JLPT/N1 | https://en.wiktionary.org/w/index.php?title=Appendix:JLPT/N1&oldid=84094074 | 2,818 | `2025-03-03T17:56:41Z` |
| **Total** | | | **7,370** | |

Each level page begins with the same structural description (N5 quoted here verbatim):

> “This appendix is broken into sections corresponding to the ten columns of the gojūon kana ordering system. There a total of 667 words. The frequency of the word is compiled from here.”

The wikitext tables have four fields, verbatim header:

> “Kanji” / “Reading” / “Meaning” / “Frequency”

The level pages are in the **Appendix namespace (`ns=100`)**. They are not organized as `Category:JLPT N5`, etc. At audit time the Action API returned only generic categories such as `Category:Basic word lists by language`, `Category:Japanese appendices`, and `Category:Japanese language` (and category results were not consistently attached to all five pages). Therefore, enumerate the five known Appendix titles; do not build ingestion around category traversal.

## Live Action API recipe

Official Action API endpoint:

- https://en.wiktionary.org/w/api.php
- Module documentation: https://www.mediawiki.org/wiki/API:Revisions
- Continuation documentation: https://www.mediawiki.org/wiki/API:Continue

Fetch all five pages' current raw wikitext plus revision metadata in one request:

```bash
curl --compressed \
  -H 'User-Agent: JLPTLevelsYomitan/1.0 (https://github.com/OWNER/REPO; CONTACT_EMAIL)' \
  --get 'https://en.wiktionary.org/w/api.php' \
  --data-urlencode 'action=query' \
  --data-urlencode 'format=json' \
  --data-urlencode 'formatversion=2' \
  --data-urlencode 'prop=revisions' \
  --data-urlencode 'rvprop=ids|timestamp|content' \
  --data-urlencode 'rvslots=main' \
  --data-urlencode 'titles=Appendix:JLPT/N1|Appendix:JLPT/N2|Appendix:JLPT/N3|Appendix:JLPT/N4|Appendix:JLPT/N5'
```

Parse each `query.pages[].revisions[0].slots.main.content` as MediaWiki table wikitext. Preserve the page title, `revid`, timestamp, source URL, and extracted spelling/reading. Meanings and frequency are optional derived content, not needed for level assignment.

If categories are nevertheless queried, the official Categorymembers docs say:

> “List all pages in a given category.”

and:

> “cmcontinue When more results are available, use this to continue.”

and:

> “cmlimit The maximum number of pages to return. Type: integer or max The value must be between 1 and 500. Default: 10”

Official URL: https://www.mediawiki.org/wiki/API:Categorymembers

## Bulk dump recipe

Official English Wiktionary dump locations:

- Project index: https://dumps.wikimedia.org/enwiktionary/
- Current alias: https://dumps.wikimedia.org/enwiktionary/latest/
- Current-revision content for all pages: https://dumps.wikimedia.org/enwiktionary/latest/enwiktionary-latest-pages-meta-current.xml.bz2
- Subject-page multistream dump: https://dumps.wikimedia.org/enwiktionary/latest/enwiktionary-latest-pages-articles-multistream.xml.bz2
- Category link SQL (not sufficient by itself for these Appendix lists): https://dumps.wikimedia.org/enwiktionary/latest/enwiktionary-latest-categorylinks.sql.gz
- Official dump inventory documentation: https://meta.wikimedia.org/wiki/Data_dumps/What%27s_available_for_download

The inventory defines the relevant files verbatim:

> “stub-meta-current: all pages, current revision only.”

> “Pages: Page metadata, revision metadata, including complete page content. pages-articles: `<wikiname>-YYYYMMDD-pages-articles.xml.bz2` pages-meta-current: `<wikiname>-YYYYMMDD-pages-meta-current.xml.bz2` pages-meta-history: `<wikiname>-YYYYMMDD-pages-meta-history.xml.bz2`”

For robustness, use `pages-meta-current`, stream the bzip2 XML, select namespace 100 and exactly the five titles, then parse each revision's `<text>`. Record the date embedded in the resolved filename rather than the mutable `latest` URL. Verify the checksum published in the same dump directory. For only five pages, the batched Action API call is substantially simpler and fresher.

At this audit, the dump index exposed a `20260901` run and `latest` files dated in September 2026. Dumps are snapshots and can lag live edits; the Action API gives current revisions.

## Coverage and quality caveats

1. **Not an official current JLPT vocabulary list.** The official JLPT FAQ explains why no post-2010 vocabulary specification is published:

   > “Therefore, we decided that publishing "Test Content Specifications" containing a list of vocabulary, kanji and grammar items was not necessarily appropriate.”

   Official URL: https://www.jlpt.jp/e/faq/

2. **Community-curated and mutable.** Wiktionary pages can change independently and do not state a provenance for each level assignment. Pin revision IDs for reproducible builds and treat changes as reviewable source updates.
3. **Finite stated coverage, not completeness.** The pages themselves claim 667/573/1,677/1,635/2,818 words. There is no official post-2010 list against which “complete” can be established.
4. **Row semantics are not normalized lexemes.** Rows can have blank kanji, multiple spellings for one reading, orthographic variants, and `N/A` frequency. Meanings may include many senses of the linked headword, including senses unrelated to the intended JLPT reading. Use `(written_form, reading, level)` as the source record; normalize/deduplicate downstream and do not infer level from the English gloss.
5. **Frequency is separate metadata.** The page explicitly says it is compiled from Wiktionary's “5000 Most Frequent Words” page; `N/A` occurs widely. It is not evidence for JLPT level.
6. **Recency is uneven.** The audited level-page revisions range from January to December 2025 even though this audit was performed in September 2026. “Live” availability does not imply actively maintained level assignments.

## License and redistribution obligations

Wiktionary's copyright page:

- https://en.wiktionary.org/wiki/Wiktionary:Copyrights

states verbatim:

> “The original texts of Wiktionary entries are dual-licensed to the public under both the Creative Commons Attribution-ShareAlike 4.0 International License (CC-BY-SA) and the GNU Free Documentation License (GFDL).”

> “Permission is granted to copy, distribute and/or modify the text of all Wiktionary entries under the terms of the Creative Commons Attribution-ShareAlike 4.0 International License, and the GNU Free Documentation License, Version 1.1 or any later version published by the Free Software Foundation; with no Invariant Sections, with no Front-Cover Texts, and with no Back-Cover Texts.”

Wikimedia's Terms of Use clarify that reusers may use either license and how attribution can be supplied:

- https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use

> “Reusers may comply with either license or both.”

> “When you reuse or redistribute a text page developed by the Wikimedia community, you agree to attribute the authors in any of the following fashions: Through hyperlink (where possible) or URL to the page or pages that you are reusing (since each page has a history page that lists all contributors, authors and editors); Through hyperlink (where possible) or URL to an alternative, stable online copy that is freely accessible, which conforms with the license, and which provides credit to the authors in a manner equivalent to the credit given on the Project Website; or Through a list of all authors...”

CC's official 4.0 deed states:

- https://creativecommons.org/licenses/by-sa/4.0/

> “Attribution — You must give appropriate credit, provide a link to the license, and indicate if changes were made.”

> “ShareAlike — If you remix, transform, or build upon the material, you must distribute your contributions under the same license as the original.”

**Practical packaging recommendation (not legal advice):** license the extracted Wiktionary-derived dataset under CC BY-SA 4.0; include (a) “Derived from English Wiktionary,” (b) links to each reused Appendix page or pinned revision, (c) https://creativecommons.org/licenses/by-sa/4.0/, (d) the extraction/build date and revision IDs, and (e) a statement describing normalization, filtering, deduplication, or other changes. Keep unrelated project code under its own license and clearly identify the CC BY-SA-covered data artifact. If only bare facts were independently extracted, copyright analysis can be more nuanced, but this source includes selected/arranged tables and creative gloss text, so relying on a “facts only” theory creates unnecessary risk.

## API limits, etiquette, robots, and recommended acquisition policy

Binding policy and guidance URLs:

- API usage policy: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines
- Action API etiquette: https://www.mediawiki.org/wiki/API:Etiquette
- User-Agent policy: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
- Robot policy: https://wikitech.wikimedia.org/wiki/Robot_policy
- Current API rate limits: https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits
- English Wiktionary robots file: https://en.wiktionary.org/robots.txt

Verbatim requirements/evidence:

> “When using Wikimedia APIs, an operator must: Follow the User-Agent policy and otherwise correctly label user agents; Follow rate limiting requests (e.g., throttling notification) you may receive; Follow the requirements of the content licenses when republishing downloaded or cached data; and Follow the robot policy if your software is automatically consuming content at a large scale.”

> “There is no hard speed limit on read requests, but be considerate and try not to take a site down.”

> “Making your requests in series rather than in parallel, by waiting for one request to finish before sending a new request, should result in a safe request rate.”

> “As of February 15, 2010, Wikimedia sites require a HTTP User-Agent header for all requests.”

> “User-Agent strings that begin with non-descriptive default values, such as python-requests/x, may also be blocked from Wikimedia sites...”

The 2026 cross-API limits page says the limits are mutable:

> “The rate limits described on this page are new in 2026 and are subject to experimentation and change.”

Its current table lists verbatim:

> “Unidentified Requests with no identifying characteristics other than IP address 10”

> “User-Agent only Unauthenticated bot requests with a compliant User-Agent header 200”

Those are requests per minute. It also instructs clients to:

> “limit the number of concurrent requests to 3 or fewer.”

and:

> “respect the Retry-After header provided with a 429 Too Many Requests status code.”

The Robot policy says:

> “Consider if dumps are more efficient than live requests.”

> “Honor Robots.txt. Honor every directive in our robots.txt file.”

> “When we reply with a 429 Too Many Requests status code respect the delay specified by the Retry-After header sent with the response.”

The live `robots.txt` currently contains, for the wildcard user agent:

> `User-agent: *`
>
> `Disallow: /w/`
>
> `Disallow: /api/`
>
> `Disallow: /trap/`
>
> `Disallow: /wiki/Special:`

**Operational recipe:** for the intended five-page refresh, use one batched Action API request (the API policy applies; robots exclusions are crawler directives, not a reason to scrape `/w/` HTML). Send a descriptive product/version User-Agent with a real contact URL/email, request gzip, run serially, cache by revision ID, and retry 429/503 only after `Retry-After` (otherwise exponential backoff). Never parallel-scrape HTML. For broader recurring extraction, use a dated dump and its checksum.

## Suggested registry fields

```yaml
id: enwiktionary-jlpt-appendices
kind: community_secondary
homepage: https://en.wiktionary.org/wiki/Appendix:JLPT
api: https://en.wiktionary.org/w/api.php
pages:
  N1: Appendix:JLPT/N1
  N2: Appendix:JLPT/N2
  N3: Appendix:JLPT/N3
  N4: Appendix:JLPT/N4
  N5: Appendix:JLPT/N5
license: CC-BY-SA-4.0-or-GFDL-1.1+
attribution_required: true
share_alike: true
official_jlpt: false
refresh: revision-id-aware
preferred_acquisition: batched_action_api
dump_fallback: https://dumps.wikimedia.org/enwiktionary/latest/enwiktionary-latest-pages-meta-current.xml.bz2
```
