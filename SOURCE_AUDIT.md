# JLPT Website Source Audit

Last checked: 2026-09-15 (UTC)

## Scope and decision rule

This audit covers commonly cited website/commercial JLPT lists. It records terms,
provenance, robots policy, and API status without copying any vocabulary or kanji
list content.

`robots.txt` is a crawler-control signal, **not a copyright license**. An empty or
permissive robots file does not authorize copying or redistribution. Conversely,
a source may separately license downloads even if its website is crawlable.

The official JLPT does not publish a definitive post-2010 vocabulary list. Its FAQ
says that after the 2010 revision it stopped publishing the former “Test Content
Specifications” containing lists of vocabulary, kanji, and grammar items. Therefore,
third-party level labels below are estimates or reconstructions, not official
classifications.

Evidence: <https://www.jlpt.jp/e/faq/>

## Summary classification

| Source | Classification for this project | Why |
|---|---|---|
| Tanos / Jonathan Waller | **Redistributable with attribution**, but preserve a dated copy of the license evidence | The author explicitly licenses everything on the site that is not sold under Creative Commons Attribution, including commercial use. |
| Jisho | **Reference-only; do not scrape or redistribute Jisho-derived JLPT output** | Its JLPT labels come from Tanos, while a Jisho result combines several independently licensed datasets. The API exists, but is an early/poorly documented search API, not a bulk redistribution license. Prefer Tanos directly. |
| JLPT Sensei | **Forbidden for ingestion/redistribution; reference-only** | Explicit terms reserve IP and prohibit republishing, copying, and redistribution. Its lists are internally compiled estimates. |
| Kanshudo | **Forbidden for scraping/ingestion/redistribution; reference-only** | Explicit terms prohibit downloading, scraping, distributing, copying, or external use without permission. Commercial licensing/bulk export is offered separately. |
| Nihongo-Pro | **Forbidden for ingestion/redistribution; reference-only** | Terms prohibit reproducing, copying, selling, reselling, or exploiting any portion of the service or access without written permission. No public data API or separate list license was identified. |

## 1. Tanos / JLPT Resources (Jonathan Waller)

**Classification: redistributable with attribution, subject to the stated exclusion
for items being sold.** This is the notable exception among the sites in this audit.

- Main resource: <https://www.tanos.co.uk/jlpt/>
- Vocabulary download index: <https://www.tanos.co.uk/jlpt/skills/vocab/>
- Explicit sharing/license page: <https://www.tanos.co.uk/jlpt/sharing/>
- Robots: <https://www.tanos.co.uk/robots.txt>

### Exact evidence

The sharing page is unusually explicit:

> “Everything on this site (that I'm not selling), is licenced under Creative
> Commons ‘BY’. Basically this means... use anything here however you like
> (commercial or non-commercial), but credit my site.”

It separately says to contact the author before non-personal use of something he
is selling. The JLPT landing page calls the material “free resources,” and the
vocabulary page presents downloadable lists. The robots file was fetched
successfully and was empty at audit time.

### Provenance and handling

Jisho identifies Jonathan Waller’s JLPT Resources as the source of its word/kanji
JLPT-level information. Kanshudo says its JLPT vocabulary lists were compiled by
“Wikipedia and Tanos from past papers.” These are useful corroborating provenance
statements but not substitutes for Tanos’s own license.

Recommended handling:

1. Fetch from Tanos directly, not through a republishing website.
2. Attribute “JLPT Resources / Jonathan Waller” and link the sharing page.
3. Record the retrieval date and archive the license statement with the build
   provenance because the page does not display a CC version number.
4. Do not include clearly sold products or paid audio under this permission.
5. Treat level assignments as unofficial estimates, not JLPT-authoritative data.

## 2. Jisho.org

**Classification: reference-only. Do not use Jisho as the project’s redistributable
bulk source.** The underlying Tanos labels can instead be obtained from Tanos under
its direct license.

- About/data provenance: <https://jisho.org/about>
- Search API discussion by the site operator: <https://jisho.org/forum/54fefc1f6e73340b1f160000-is-there-any-kind-of-search-api>
- Live API endpoint shape: <https://jisho.org/api/v1/search/words?keyword=test>
- Placeholder documentation repository: <https://github.com/Jisho-org/API-docs>
- Robots: <https://jisho.org/robots.txt>

### Exact evidence

The About page says:

> “Information about what word and kanji belong to which JLPT level comes from
> Jonathan Waller’s JLPT Resources page.”

It also lists multiple other data sources and licenses (including JMdict/JMnedict,
KANJIDIC2, DBpedia/Wikipedia, Tatoeba and other assets). Thus a Jisho API response
is a compiled product with field-specific provenance; Jisho’s permission to query
it is not a blanket license to redistribute every returned field.

In the operator’s API forum thread:

- the operator introduced the endpoint as a “very early test” and said proper API
  documentation still needed to be written;
- when asked about app use, the operator requested credit to Jisho and compliance
  with the licenses of the data sources listed on the About page;
- the operator said scraping was “fine” in that thread, while warning that the HTML
  could change.

That forum permission makes ordinary querying/scraping less ambiguous, but it does
**not** remove the underlying licenses, establish a bulk-download SLA, or grant a
single redistribution license for the assembled data. The live JSON API returned
HTTP 200 at audit time and currently includes a `jlpt` field, despite older comments
in the thread saying it was then absent.

The robots file currently allows general crawling but specifies `Crawl-delay: 40`
for `User-agent: *` (and blocks SemrushBot). This reinforces that any permitted
reference crawl should be very slow; it is not redistribution permission.

### Why not ingest

- The desired JLPT annotations have a cleaner, expressly CC-BY upstream (Tanos).
- Bulk enumeration through a search endpoint adds load and depends on unstable,
  incomplete API semantics.
- Redistributing complete responses would require field-by-field compliance with
  the independently licensed source datasets.

## 3. JLPT Sensei

**Classification: forbidden for ingestion, copying, and redistribution;
reference-only links are acceptable.**

- Example list landing page (do not copy content):
  <https://jlptsensei.com/jlpt-n5-vocabulary-list/>
- Terms and Conditions: <https://jlptsensei.com/terms-and-conditions/>
- Robots: <https://jlptsensei.com/robots.txt>

### Exact evidence

Under “License,” the terms say JLPT Sensei and/or its licensors own the intellectual
property rights, reserve all rights, and allow access for personal use subject to
restrictions. The listed prohibitions include:

> “Republish material from JLPT Sensei”
>
> “Reproduce, duplicate or copy material from JLPT Sensei”
>
> “Redistribute content from JLPT Sensei”

The list page explains its provenance and uncertainty:

> “Officially, there are no kanji, vocabulary, or grammar lists for the JLPT.”

and says its study lists are based on prior test data and comparisons with other
available lists. That is a compiled editorial dataset, not a claim of an open
upstream license.

The robots file allows ordinary public pages and disallows `/wp-admin/` (while
allowing `admin-ajax.php`). That crawl permission does not override the explicit
copy/redistribution restrictions. No public data API was identified in this audit.

## 4. Kanshudo

**Classification: explicitly forbidden for scraping, downloading, copying,
distribution, or use outside Kanshudo without express permission.**

- Terms and conditions: <https://www.kanshudo.com/tc>
- Credits and detailed provenance: <https://www.kanshudo.com/credits>
- JLPT center: <https://www.kanshudo.com/jlpt>
- JLPT vocabulary collection index (reference only):
  <https://www.kanshudo.com/collections/wikipedia_jlpt>
- Robots: <https://www.kanshudo.com/robots.txt>

### Exact evidence

The terms state:

> “Kanshudo is for the personal or group study of Japanese. No other use of the
> system is allowed without the express permission of Kanshudo.”

They further state:

> “Unless otherwise noted, all collections, kanji and word usefulness data,
> grammar reference articles, and other data used around the site are copyright
> Kanshudo. Kanshudo data may not be downloaded, scraped, distributed, copied or
> used outside Kanshudo except for personal study without the express permission
> of Kanshudo.”

The same page says most data is available to license and that Kanshudo offers bulk
export/custom formatting services. Therefore, a negotiated license is the only
appropriate ingestion route.

The credits page says the JLPT vocabulary lists were compiled by “Wikipedia and
Tanos from past papers,” but Kanshudo also maps and recommends forms using its own
usefulness system. That provenance does not make Kanshudo’s transformed collection
freely reusable; use the openly licensed upstream instead.

The robots file does not disallow ordinary users generally, but blocks several
named crawlers (Yandex, AhrefsBot, BLEXBot, linabot, SemrushBot). Explicit terms
nevertheless prohibit scraping. No public data API was identified in this audit.

## 5. Nihongo-Pro / Kanji Pal

**Classification: forbidden for copying/ingestion/redistribution without express
written permission; reference-only.**

- JLPT-indexed Kanji Pal page (do not copy content):
  <https://www.nihongo-pro.com/kanji-pal/list/jlpt>
- Terms of Service: <https://www.nihongo-pro.com/terms-of-service>
- Robots: <https://www.nihongo-pro.com/robots.txt>

### Exact evidence

The Terms of Service say:

> “You agree not to reproduce, duplicate, copy, sell, resell or exploit any
> portion of the Service, use of the Service, or access to the Service without
> the express written permission by Nihongo-Pro.”

They also reserve the website look and feel and forbid duplicating/copying/reusing
its HTML/CSS or visual design elements without written permission. The public page
is ad-supported and advertises JLPT-grouped kanji and vocabulary, but it supplies
no visible open-data license or provenance for the JLPT assignments. No public
bulk/data API was identified in this audit.

The robots file disallows `/quiz-media`, `/kyouzai`, and `/hp/internal`, while not
disallowing the public Kanji Pal page. Again, crawler access does not grant copying
or redistribution rights.

## Project policy resulting from this audit

- **Permitted candidate:** Tanos list data only, with attribution, dated license
  evidence, and exclusion of sold material.
- **Reference/fetch-at-build only:** none of the other sites should be fetched to
  construct the distributable artifact. If used for manual QA, record only aggregate
  observations or links—not copied entries.
- **Forbidden ingestion:** JLPT Sensei, Kanshudo, and Nihongo-Pro.
- **Jisho:** link/reference and occasional API lookup are defensible under the
  operator’s forum statements and source licenses, but bulk list extraction is
  unnecessary and should be prohibited by project policy because Tanos is the
  direct licensed source.
- A permissive `robots.txt` must never be treated as license evidence.
