# GAO open recommendations

Read GAO's open-recommendations export whole: one CSV from its recommendations
database listing every recommendation GAO still counts open, one row per
recommendation per agency. GAO has no recommendations API; this export is the
database's own download. The reader is
[`sources/gao/recommendations.py`](../../src/spicy_docs/sources/gao/recommendations.py),
and the table it fills is `gao_recommendations` ([tables](../tables.md)).
Why each rule is as it is: [decisions](../decisions.md#gao-recommendations-are-keyed-on-the-number-gao-states-and-accumulated-by-the-host).

## Capture

- One GET of `https://www.gao.gov/open-recs2-csv?q=` (an empty query selects
  every open recommendation), through Zyte, since `www.gao.gov` refuses plain
  clients. `ZYTE_TOKEN` must be in the environment; one request a run.
- `robots.txt` does not disallow this path, and one read a day is far inside
  its 420-second crawl delay.
- Measured 2026-09-28: `text/csv; charset=UTF-8`, 6,771,912 bytes, 5,379
  records; two captures twenty minutes apart were byte-identical.

```sh
uv run --frozen python -m spicy_docs.sources.gao.recommendations fetch --store STORE --receipts RECEIPTS.jsonl
uv run --frozen python -m spicy_docs.sources.gao.recommendations read --store STORE --receipts RECEIPTS.jsonl
```

`fetch` keeps GAO's exact bytes in a content-addressed store and appends one
receipt row (URLs, status, media type, size, digest, Zyte request id, the
export's stamp and record count); a refusal is a `failed` row with any refused
bytes. `read` re-reads the latest retained export offline, the store proving
its digest, and prints its records as JSON lines.

## What the reader refuses

The whole export, never a record of it:

- a preamble, header, status or priority it does not know. The header is
  eleven columns, `Publication  Number` with two spaces; the statuses are
  `Open` and `Open--Partially Addressed`;
- a cut export, where the bytes can show one: a body ending in CR or LF (GAO
  writes no final terminator), a quoted field left open, or no records. A cut
  just before a record's terminator shows only against a stated
  Content-Length, which the Zyte transport forwards when a target sends one;
  GAO sent none for this export on 2026-09-29, so that cut stays unseen;
- an ampersand spelled other than `&amp;`, or one still escaped after `&amp;`
  is read as `&`;
- a repeated key, a bad issue date, an empty agency or text, a publication
  number with a space, or a record of the wrong width.

## What a record states

The export's fields, unescaped, less the director's phone, which is never
read (owner decision: the name only). The stamp "status as of Sep 28, 2026 at
7:05 PM EST" is kept verbatim and only its date is read: GAO labels it EST all
year, but it is Eastern local time.

GAO numbers each recommendation within its product and states the number at
the end of the text: "(Recommendation 4)", "(Matter for Consideration 1)",
"(Matter for Congressional Consideration 2)", or on about twenty records a
variant such as "(Matter 1)", "[Recommendation 1]", "(Recommendations 5)",
"(Recommendation 19-01)" or an unclosed "(Recommendation 9". `stated_number`
reads it as a kind, `recommendation` or `matter`, and the number as written.
4,892 of the 5,379 records state one.

## The key

`gao-recommendation-key/1`: where the text states a number, a digest of the
lowercased publication number, the kind, the number and the agency; elsewhere,
of the publication number, the agency and the text. Agency and text are
whitespace- and case-folded. The agency is part of the key because one
numbered recommendation made to three agencies is three records. Both forms
are unique on the 2026-09-28 export.

## Publishing from the retained bytes

The retained bytes hold the directors' phones as GAO prints them. Anything
published from them, such as a host's source evidence, goes through
`redact_director_phone` first: it empties that column in every record and
keeps every other byte, and a redacted export reads back to the same records.
