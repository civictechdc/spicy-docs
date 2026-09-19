# GovInfo package bodies and acquisition

`GovInfoBodyAcquirer` fetches the body of one GovInfo package named by its
package id: a committee report, hearing transcript, committee print,
Congressional Record issue, congressional document, congressional directory or
bill text. It reads the package summary, then the package MODS, then the one
rendition the publisher says it offers, and returns exact bytes with every
response that proved them. Install `spicy-docs[acquisition]`.

`acquire_granule` does the same for one granule of a package -- the daily
Record's individual speeches and page ranges -- reading the granule summary
and MODS instead of the package's own, at the same three-request shape. See
[Granule bodies](#granule-bodies-for-the-record) below.

This is a body fetch, not a crawl: the caller names the package (or the
package and granule). Discovery of which packages exist stays with the
[list routes](listings.md), and MODS field meanings stay with the
[MODS mapping](govinfo-metadata.md).

## Acquire a body

```python
from pathlib import Path

from spicy_docs.sources.govinfo.body_acquisition import GovInfoBodyAcquirer, GovInfoBodyBudget
from spicy_docs.transport.credentials import read_api_key

budget = GovInfoBodyBudget(
    max_requests=5,
    max_body_bytes=24 * 1024 * 1024,
    max_metadata_bytes=8 * 1024 * 1024,
    timeout_seconds=60,
    min_request_interval_seconds=0.5,
)
with GovInfoBodyAcquirer(budget=budget, api_key=read_api_key(Path(".env"), "API_GOV")) as client:
    result = client.acquire("CRPT-119hrpt1")  # BODY_PREFERENCE is the default

body = result.body_capture.body
digest = result.body_capture.sha256
chosen, offered = result.format, result.offered_formats
```

Then turn the body into text with one function, whatever rendition came back:

```python
from spicy_docs.extraction.body_text import body_text

derived = body_text(result)
derived.text  # parser-ready text
derived.rendition  # "xml", "uslm", "htm", "txt" or "pdf" -- what the publisher offered
derived.derivation  # "markup-reader", "text-rendition-cleanup" or "pdf-extraction-gpo-normalized"
derived.record  # the cleanup counts for that branch
```

## The preference rule

`BODY_PREFERENCE` in `sources/govinfo/bodies.py` is **one sealed order for
every caller**: `("xml", "uslm", "htm", "txt", "pdf")`. It is `acquire`'s
default, and `sources/congress/bill_versions.py::DEFAULT_FORMAT_PREFERENCE` is
the same order in Congress.gov's own format names (`("xml", "uslm", "html",
"txt", "pdf")` — the GovInfo rendition `htm` is spelled `html` there). A test
pins the two equal, so a version chosen in one spelling is fetched in the
other. `GRANULE_BODY_PREFERENCE` (`("htm", "pdf")`) is `acquire_granule`'s own
default; see [Granule bodies](#granule-bodies-for-the-record).

`prefer` is still a plain tuple a caller can override, and `bill_pdf.py` does,
naming `("pdf",)` because it wants that rendition specifically rather than the
best one available. `max_bytes` can narrow the body allowance for one call,
never raise it — a PDF is the rendition most likely to exceed it.

What the sealed order changes, measured over the original six collections
(the formats table below adds a seventh, CPRT, after this ruling): for CRPT,
CHRG, CDOC, CDIR and BILLS it picks exactly what the previous default picked.
The one collection whose answer changes is **CREC**, which offers PDF and
nothing else: it used to refuse with `GovInfoFormatNotOfferedError` and now
returns a body. That is the whole of the ruling this seals. Two additions
came later, under the same order: `uslm` (§B7) — BILLS states a second
structured rendition at `uslm/{id}.xml`, which this module now fetches
directly rather than reporting it as a
[moved rendition](#formats-and-how-the-offered-set-is-read); measured on
every BILLS package in the 2026-09-19 text-versions sample that offers one —
five enrolled packages, pinned per package in
`tests/fixtures/govinfo_bills/uslm-renditions-2026-09-19.json` — and CPRT
(§A10), which offers `htm`, `pdf` and `xml` and picks `xml`, the same
structure-first rule the rest of the order already follows.

## Package ids

| Collection | Grammar | Example |
| --- | --- | --- |
| Committee reports | `CRPT-{congress}{hrpt\|srpt\|erpt}{number}` | `CRPT-119hrpt1` |
| Hearings | `CHRG-{congress}{hhrg\|shrg\|jhrg}{jacket}` | `CHRG-119hhrg64242` |
| Congressional documents | `CDOC-{congress}{hdoc\|sdoc\|tdoc}{number}` | `CDOC-119tdoc2` |
| Committee prints | `CPRT-{congress}{HPRT\|SPRT\|JPRT}{number}` | `CPRT-118HPRT57104` |
| Congressional Record | `CREC-{yyyy-mm-dd}` with optional `-v{volume}` or `-i{issue}` | `CREC-2019-01-03-v164` |
| Congressional Directory | `CDIR-{yyyy-mm-dd}` | `CDIR-2026-02-20` |
| Bill text | `BILLS-{congress}{type}{number}{version}` | `BILLS-119hr1enr` |

Congress.gov route URLs carry these ids as their file stems, so a caller
holding a route holds a package id. A Record date alone is not one: a single
date can publish two volumes, so the suffix belongs to the id and is never
inferred. Report and document numbers reject a leading zero; a hearing jacket
keeps the publisher's digits as printed. The bill-type vocabulary is the one
`sources/congress/bill_status.py` already states, imported rather than copied.
The committee-print token is upper-case (`HPRT`/`SPRT`/`JPRT`), unlike the
committee-report token it otherwise resembles (`hrpt`/`srpt`/`erpt`) — verified
on a real package summary 2026-09-19, not inferred from CRPT's own spelling.

`parse_package_id` refuses anything else and names what it expected. That
includes real packages from neighboring collections that a collection-scoped
`published` walk returns anyway — `ERP-2009` states `collectionCode` `ERP` and
`GPO-J6-REPORT` states `GPO` (79 of 1,681 CDOC-scoped and 3 of 3,000
CRPT-scoped ids sampled on 2026-09-19). They have different addresses, so they
are refused rather than guessed at.

A **granule id** names one constituent of a package — the daily Record's
individual speeches and page ranges — and has no per-collection grammar of its
own; `parse_granule_identity` bounds it as a safe path segment (the same
length limit as a package id) and pairs it with its package's identity. See
[Granule bodies](#granule-bodies-for-the-record).

## Routes and credentials

| Request | Route | Credential |
| --- | --- | --- |
| Summary | `https://api.govinfo.gov/packages/{id}/summary` | `X-Api-Key` header |
| MODS | `https://api.govinfo.gov/packages/{id}/mods` | `X-Api-Key` header |
| Body | `https://www.govinfo.gov/content/pkg/{id}/{folder}/{id}.{extension}` | none |
| Granule summary | `https://api.govinfo.gov/packages/{id}/granules/{granuleId}/summary` | `X-Api-Key` header |
| Granule MODS | `https://api.govinfo.gov/packages/{id}/granules/{granuleId}/mods` | `X-Api-Key` header |
| Granule body | `https://www.govinfo.gov/content/pkg/{id}/{folder}/{granuleId}.{extension}` | none |

The key travels in the header only, never in a URL, a request body or a
retained locator. The two routes use separate clients drawing on one request
budget: the keyed client retains no refusal body, because an api.data.gov error
can echo the key, while the keyless client retains its 401/403 body, because
there a refusal is a bot wall or an access-denied document — the publisher's
own answer. A keyed response containing the key is refused and not retained.

## Formats and how the offered set is read

`PACKAGE_BODY_FORMATS` is the grammar — every rendition this module can
address. `BODY_PREFERENCE` above is the order to ask for them in.

| Format | Path | Media type | Text derivation |
| --- | --- | --- | --- |
| `xml` | `xml/{id}.xml` | `application/xml`, `text/xml` | `markup-reader` |
| `uslm` | `uslm/{id}.xml` | `application/xml`, `text/xml` | `markup-reader` |
| `htm` | `html/{id}.htm` | `text/html` | `markup-reader` |
| `txt` | `text/{id}.txt` | `text/plain` | `text-rendition-cleanup` |
| `pdf` | `pdf/{id}.pdf` | `application/pdf` | `pdf-extraction-gpo-normalized` |

The folder is not the format name: text is served from `text/`, HTML from
`html/`, USLM from `uslm/` — the last shares `xml`'s file extension, so only
the folder (and the caller's own locator, which this module derives) tells
the two apart. No package offers all five. The offered set is read from the
package MODS, from each `location/url` whose `access` is `raw object` and
whose URL is exactly this module's locator for a supported format. Measured
2026-09-19:

| Package | MODS says offered | Keyless routes answering 200 | Summary `download` body links |
| --- | --- | --- | --- |
| `CRPT-119hrpt1` | HTML, PDF | `htm`, `pdf` | none |
| `CHRG-119hhrg64242` | HTML, PDF | `htm`, `pdf` (46.6 MB) | none |
| `CDOC-119tdoc2` | HTML, PDF | `htm`, `pdf` | none |
| `CPRT-118HPRT57104` | HTML, PDF, XML | `htm`, `pdf`, `xml` | none |
| `CREC-2026-01-02` | PDF | `pdf` | four PDF links |
| `CDIR-2026-02-20` | PDF, Text | `pdf` (18.3 MB), `txt` | `txtLink`, `pdfLink` |
| `BILLS-119hr1enr` | HTML, PDF, XML, USLM | `htm`, `xml`, `pdf`, `uslm` | `xmlLink`, `txtLink`, `xhtmlLink`, `uslmLink`, `pdfLink` |

The MODS statement agreed exactly with what the routes served, in both
directions, for every package measured: each stated rendition answered 200 and
every unstated one redirected to the error page. The summary's `download`
block did not: it names no body rendition at all for CRPT, CHRG, CDOC and
CPRT, which do serve HTML and PDF, and it spells the BILLS HTML rendition
`txtLink`. So the summary is read and kept — its `download_links` exactly as
spelled, its `dateIssued` and its `lastModified` are in the result — but
nothing is derived from those links and the offered set comes from MODS alone.

A stated rendition that is not one of these locators is separated by what it
means. `moved_renditions` holds `(format, url)` for a rendition of this
package in a supported file type at an address this module does not derive —
before §B7, BILLS's own USLM rendition was the standing example (stated at
`uslm/{id}.xml`, an address this module did not then fetch from); now that
`uslm` is a first-class format with that exact locator, this case is any
supported extension found at an unexpected folder, and `other_renditions`
holds `(displayLabel, url)` verbatim for everything else: another package's
address, another file type, another host. `uslm` and `xml` share a file
extension, so a rendition found this way can only be labelled by extension
when the folder disagrees; `xml` is the tie-break
(`sources/govinfo/bodies.py::_FORMAT_BY_EXTENSION`).

## Turning a body into text

`extraction/body_text.py` is the one function that turns a fetched rendition
into parser-ready text, so no caller re-implements a stripper and no two
callers derive two different texts from one document. One derivation per
rendition, named on the result, never guessed from the bytes:

| Derivation | Renditions | Built from |
| --- | --- | --- |
| `markup-reader` | `xml`, `uslm`, `htm` | `reading/markup.py`'s event readers |
| `text-rendition-cleanup` | `txt` | the shared rules below, nothing else |
| `pdf-extraction-gpo-normalized` | `pdf` | `DocumentExtractor(NativeText())`, then [`normalize_gpo_pages`](../extraction-gpo.md) |

`uslm` takes the same branch as `xml`, not a dedicated USLM parser: measured
2026-09-19 on all five sampled BILLS packages that offer it
(`tests/fixtures/govinfo_bills/uslm-renditions-2026-09-19.json`), the root is
`<resolution>` (hconres) or `<bill>` (the four H.R. bills) in the same
`schemas.gpo.gov/xml/uslm` namespace GPO's PLAW/COMPS USLM uses, but neither
of `sources/govinfo/uslm.py`'s two fixed roots (`pLaw`, `statuteCompilation`)
— and a bill's own root varies by bill type (`bill`, `resolution`,
`jointResolution`, …) where a law or compilation each has exactly one. That
grammar validates identity against a `PublicLawSelection` or
`StatuteCompilationSelection`, and a bill has neither, so it does not apply;
the generic markup reader, which reads any well-formed XML's text in document
order regardless of vocabulary, does.

`BodyText` is frozen and carries `text`, `pages` (the per-page text for a PDF,
`None` otherwise — no other rendition states a page boundary), `rendition`,
`media_type`, `byte_size`, `derivation` and `record`: a `GpoCleanupRecord` for
the PDF branch and a `RenditionCleanup` for the others. That is enough for a
hosted row to say how its text was made without holding the bytes.

### What the non-PDF renditions carry, and the rules for it

Measured 2026-09-19 over four keyless `htm` bodies (CRPT-119hrpt1,
-119hrpt105, -113hrpt135, -113srpt77), one `txt` body (CDIR-2026-02-20 — the
only collection measured that offers one), three BILLS `xml` bodies and five
BILLS `uslm` bodies — every package in the 2026-09-19 sample offering one
(reading facts pinned per package in
`tests/fixtures/govinfo_bills/uslm-renditions-2026-09-19.json`; the per-rule
counts below are measured on the one USLM fixture whose bytes are retained,
BILLS-119hconres11enr). The per-file counts are in
`tests/fixtures/govinfo_bodies/README.md` and
`tests/fixtures/govinfo_bills/README.md`; only what was counted above zero
has a rule.

| Rule | Artifact | Renditions | Measured |
| --- | --- | --- | --- |
| `metadata_element` | HTML `<title>`: document metadata restating the printed heading | `htm` | 591, 703, 80, 77 characters |
| `element_line_break` | An XML element boundary, kept as a line break so two elements' text never runs together | `xml`, `uslm` | 26 on BILLS-119hr6028ih; 31 on the USLM body |
| `whitespace_only_line` | XML pretty-print indentation between elements | `xml`, `uslm` | 38 on BILLS-119hr6028ih; 32 on the USLM body |
| `line_ending` | CRLF/CR line endings | `xml`, `htm`, `txt` | 27,717 in the CDIR text; 0 elsewhere, including the USLM body |
| `end_of_text_marker` | GPO's trailing `U+001A` terminator | `xml`, `htm`, `txt` | 1 each in the CRPT-113hrpt135 and -113srpt77 `htm`; 0 on the USLM body |
| `gpo_quote_pair` | GPO's `` `` ``/`''` typewriter quote pairs | `xml`, `htm`, `txt` | 6, 2, 54, 119 pairs in the four `htm` bodies; 0 on the USLM body |
| `trailing_space` | Trailing spaces from GPO's fixed-width columns; leading spaces are the layout and stay | `xml`, `htm`, `txt` | 19,077 lines in the CDIR text; 0 on the USLM body |

The last four rules are not named for `uslm` in
`RENDITION_CLEANUP_RULES`, though the same shared code produces their counts:
this one small USLM fixture measured zero on each, and only what is counted
above zero has a rule, the standard this table already holds itself to.

Four things are deliberately **not** stripped:

- **Blank lines in an `htm` or `txt` body.** They are the document's own
  layout, and `parse_agency_blocks` decides a heading has a body by whether
  the lines under it are blank. Dropping them merges blocks. Whitespace-only
  lines are dropped in the XML branch only, where they are pretty-printing.
- **Doubled internal spaces.** The PDF branch collapses them
  (`gpo_normalize`'s space-collapse rule); the `htm` branch does not, because
  that spacing is what keeps an appropriations account row's label, leader
  dots and amount aligned. One consequence worth knowing before ingesting one
  report from both renditions: `report_blocks`'s `agency_key` is
  `upper().strip()` only, so the same heading yields `OFFICE OF  THE
  COMPTROLLER…` from `htm` and `OFFICE OF THE COMPTROLLER…` from the PDF.
- **`[[Page N]]` markers and form feeds.** Zero in all nine bodies measured.
  Unmeasured, so no rule — the same standard `gpo_normalize` holds itself to.
- **`VerDate` print footers.** A PDF artifact; `normalize_gpo_pages` already
  owns them and this module does not duplicate the rule.

One asymmetry the markup reader creates and this module does not correct: GPO
writes its end-of-document marker as literal `[all]` in some bodies and as a
pseudo-element `<all>` in others (`CRPT-113srpt77`, `-113hrpt135`). The reader
drops the element form, because it carries no text, and keeps the literal
form, because it is text. Both are one marker; making them agree would be a
policy this module has no measurement for.

A BILLS `xml` body declares an external DOCTYPE (`<!DOCTYPE bill PUBLIC …
"bill.dtd">`), which `read_xml_events` refuses unless a caller says otherwise,
so `body_text` allows it explicitly. Nothing is fetched for it: the reader
never loads an external resource and still refuses every entity declaration.

## Why PDF is last

The order above puts the page image last, and that is a measurement, not a
preference. Three real committee reports, each read in the rendition it offers
and in its own PDF through `DocumentExtractor(NativeText())` and
`normalize_gpo_pages` (receipts and digests in
`tests/fixtures/govinfo_bodies/README.md`):

| | CRPT-119hrpt105 | CRPT-113srpt77 | CRPT-113hrpt135 |
| --- | ---: | ---: | ---: |
| Mid-word print wraps, `htm` | 2 | 32 | 47 |
| Mid-word print wraps, PDF text | 18 | 1,863 | 1,894 |
| Account rows keeping label + amount on one line, `htm` | 0 | 841 | 190 |
| Account rows keeping label + amount on one line, PDF text | 0 | 0 | 3 |
| Heading lines the report parser matches, `htm` | 10 | 391 | 130 |
| Heading lines the report parser matches, PDF text | 11 | 413 | 221 |
| Character similarity, `htm` text vs PDF text | 0.66 | 0.84 | 0.94 |

- **The PDF text splits words the other rendition keeps whole.** A committee
  report is never gutter-numbered by GPO, so `normalize_gpo_pages`'s
  hyphen-rejoin stays off by design and those ~1,870 wraps per report stay
  split. The words only the PDF side has are the fragments (`tion` ×79,
  `ment` ×66, `recommenda` ×28, `secu`/`rity`); the words only the `htm` side
  has are the whole words they came from (`security` ×29, `department` ×27,
  `recommendations` ×22). The `htm` rendition's own hyphens are real compound
  words — `man-made`, `long-standing`, `one-size-fits-all` — not wraps.
- **The PDF text destroys table rows.** `htm` gives
  `Amount of 2013 appropriations\4\ \6\ \8\......  59,742,509,000` on one
  line; PyMuPDF emits the label and `59,742,509,000` as two lines, and on a
  multi-column table it emits every label first and then every amount, so the
  row-to-amount association is gone rather than merely reformatted.
- **The PDF's extra heading matches are not better ones.** Its 11th match on
  CRPT-119hrpt105 is a block labelled `REPORT` whose entire body is `"` and
  `!` — the two decorative cover-page glyphs
  [`docs/extraction-gpo.md`](../extraction-gpo.md) already records as PyMuPDF
  artifacts of that exact page. On the larger reports the extra matches are
  headings split across two lines by the page width (`TRUSTED INTERNET
  CONNECTIONS/HUMAN RESOURCES INFORMATION` + `TECHNOLOGY`), counted twice.
- **There is no font cue to buy the structure back.** GPO sets section
  headings in the body face at body size. Across CRPT-113srpt77 and
  -113hrpt135: 89 and 16 lines are bold, against 297 and 201 heading lines the
  parser matches, and only 15 and 12 matched lines carry any font distinction
  at all. The 3,948 and 1,207 lines that *do* differ from the body font are
  the table cells (`TradeGothic-CondEighteen` 7pt, `Helvetica` 6.5pt) and
  dollar amounts. A span-aware extractor — `Recognition.raw` already retains
  PyMuPDF's full `get_text("dict")`, so the cost is a reader, not a new
  dependency — would therefore label the tables, not the headings, and would
  still have to rebuild each row from bounding boxes. The `htm` rendition
  hands those rows over already joined, for nothing.

So PDF stays last, and it stays *in* the order: it is the only rendition
CREC offers, and a body from a page image beats no body at all.

`htm` before `txt` is not a measured ranking. No package offers both — CRPT,
CHRG and CDOC offer `htm` and `pdf`; CDIR offers `txt` and `pdf`; BILLS offers
`htm`, `xml` and `pdf`; CREC offers `pdf` — so the two never compete. They are
ordered by the same structure-first rule, since markup can only add to what
plain text already states.

## Table geometry recovered from the PDF

B5 of `docs/research/closing-the-gaps-2026-09-19.md`: does retaining PyMuPDF's
table geometry (`extraction.DocumentExtractor(strategy, tables=True)`, a
`TableObservation` per detected table -- see
[the extraction API doc](../extraction/pdf-extraction-api.md#table-geometry))
recover any of the rows the section above shows native text destroying?
Measured 2026-09-19 on the same two reports, re-fetched keyless through
`sources.govinfo.bodies.package_body_locator` (both PDF digests agree with
"The rendition comparison that ordered `BODY_PREFERENCE`" above -- an
independent re-fetch, not a restatement) and run through the shipped
default: no strategy override, PyMuPDF's line-ruled `find_tables()`. Input
pins, the fetch and analysis scripts and their full output are in
`~/Work/corpora/supply-2026-09-02/receipts/gpo-pdf-tables-2026-09-19/`; the
one committed fixture this measurement's pinned test reads from is
`tests/fixtures/gpo_pdf_tables/README.md`.

An account row is counted the same way on both sides: a line (`htm`) or a
table cell (PDF) whose label is non-empty text that is not itself an amount,
followed by dot leaders or two or more spaces, then a token that parses as a
dollar amount (`$`-prefixed, thousands-grouped, decimal, or parenthesized/
signed for a negative delta) -- the row rule this measurement is pinned to,
implemented once and applied to both renditions of both reports. On the PDF
side, PyMuPDF rules only a table's header, its whole account block and its
total, never between individual accounts, so one `TableObservation` row can
hold many accounts as one `\n`-joined cell per column (the fixture behind
`tests/extraction/test_api.py`'s pinned real-page test is exactly this
shape); recovering one row per account means splitting each cell on its own
newlines and zipping the split cells of one raw row by line position --
a post-processing step over the retained geometry, not something the frozen
`TableObservation` record does itself.

| | CRPT-113srpt77 | CRPT-113hrpt135 |
| --- | ---: | ---: |
| Pages | 190 | 229 |
| PDF bytes | 531,055 | 3,233,438 |
| Ruled tables PyMuPDF finds | 69 | 0 |
| Account rows recovered from PDF tables | 199 | 0 |
| Account rows by the same rule over `htm` | 802 | 273 |
| Row-recovery rate | 25% | 0% |
| Wall time, `tables=True` (whole document) | 11.8 s | 7.7 s |
| Wall time, `tables=False` (same document) | 1.7 s | 1.4 s |
| False account rows on a prose page (page 1, title/letter page) | 0 of 22 nonblank lines | 0 of 84 nonblank lines |
| False account rows on a dollar-figure-dense narrative page | -- | 0 of 85 nonblank lines (page 5, "INTRODUCTION", every sentence carries a `$` figure) |

The `htm` counts here (802, 273) are this same rule re-derived today, not a
rerun of the script that produced the 841 and 190 stated above and in
`docs/research/closing-the-gaps-2026-09-19.md`; they track that measurement
(close for srpt77, higher for hrpt135, because this rule also counts the many
per-project "Appropriation / Budget estimate / Recommended" comparison
triplets printed throughout the narrative body, not only rows inside the
report's one summary table) without reproducing it byte-for-byte. The
qualitative finding does not depend on matching that number exactly:

- **Recovery tracks ruling, not report size or row count.** srpt77 rules 69
  real tables (header/body/total boxes) and recovers a quarter of its rows
  that way; hrpt135 -- six times the PDF bytes -- rules **none**: every one
  of its appropriations tables is leader-dot or whitespace-aligned, the same
  layout `find_tables()`'s default line-based strategy cannot see, so table
  geometry recovers nothing there and native text stays the only PDF-derived
  source (0 or 3 rows, per the section above).
- **The default strategy never invents a row.** Zero false account rows on
  every prose page tested, including one packed with dollar figures inside
  ordinary sentences (`$30,426,000,000, $2,857,000,000 less than the amount
  appropriated in fiscal year 2013 ...`). Switching PyMuPDF's table finder to
  its whitespace-based `vertical_strategy="text"` to try to reach the
  leader-dot tables was tried on that same prose page: it fabricates one
  58-row, 6-column table out of ordinary justified prose, splitting words
  mid-sentence into spurious columns -- the row rule still finds no false
  account row in that wreckage, but the geometry itself is garbage. That is
  why the shipped default stays the plain, unparameterized
  `page.find_tables()` the gap asked for, not a tuned strategy.
- **The cost is real and the option defaults off.** Table detection adds 6-7x
  wall time to whole-document extraction (1.7 s to 11.8 s; 1.4 s to 7.7 s) for
  a quarter, or zero, of the rows native text already destroys. `tables`
  defaults to `False`.

**Verdict: reach for PDF table geometry only where no HTML (or other
text-bearing) rendition exists.** Every collection in the package-id grammar
that offers a committee report, hearing, document or bill also offers `htm`
or `xml`, and `BODY_PREFERENCE` already prefers it; `htm`'s rows arrive
already joined, for nothing, and stay the reference above. The one collection
where this changes anything is CREC, PDF-only in this grammar -- and even
there, recovery is not guaranteed: it depends on whether GPO ruled that
particular table, exactly as measured above.

## Decision

**One sealed body preference, XML first and PDF last, and one text-derivation
function per rendition.**

The ruling, verbatim: *"shouldn't we prefer xml? and accept pdf as a final
fallback?"* Before it, each caller carried its own order and stopped early —
the spicy-regs bill family asked for `("xml", "txt")`, its committee-report
transform for `("txt", "htm", "xml")` — so a version or report offered only as
PDF got no body, and two callers disagreed about what the same publisher
offers. `BODY_PREFERENCE` is now the single order, `acquire`'s default, and
`bill_versions.DEFAULT_FORMAT_PREFERENCE`'s source of truth.

Alongside it, `extraction/body_text.py` is the one place a rendition becomes
text. The committee-report path previously fed an `htm` body straight through
`normalize_gpo_pages` and `parse_agency_blocks` — a normalizer and a parser
both derived on PDF-extracted text — splitting the body on a form feed that
the measurement above shows is never there. Each rendition now gets the
derivation measured for it, and the record says which one ran.

Both were measured before being sealed, and the measurement is above: it is
also what decided the order between the text renditions and PDF, rather than
an argument about which format "has structure". This section and its tables
are for the maintainer owning the source-workflow docs to move into place.

## Identity rules and why each exists

A GovInfo body carries no machine-readable package id — the CRPT-119hrpt1 HTML
body never spells `CRPT-119hrpt1` — so there is no equivalent of the Federal
Register granule's printed `[FR Doc No: ...]` marker to check. Identity is
instead four publisher statements about the one URL whose bytes were kept:

- **The summary states `packageId` and `collectionCode`.** They must equal the
  request. The summary route is also the only one that answers `404` for a
  missing package: the MODS route answers `400` and the body routes redirect.
  So it runs first, and a missing package is typed unavailable at once.
- **The MODS states `accessId`.** Every `accessId` under the package root's own
  `extension` children must equal the requested id; a constituent's `accessId`
  names a granule and is not read. This is the same rule the Federal Register
  granule route applies to its resolved `accessId`.
- **The MODS states the rendition URL.** The fetched locator must be one the
  MODS named as a `raw object` rendition of this package, so the address this
  module derives and the address the publisher publishes have to agree.
- **The response arrived at that locator.** Redirects are refused, so a 200 at
  this URL is this package's rendition or it is the error page.
- **It is not the error page.** A missing package or unoffered rendition
  redirects to `https://www.govinfo.gov/error`, which answers 200 with a
  44,165-byte "Page Not Found" page. The final URL and the `govinfo.gov/error`
  marker are both checked. This is one publisher rule with one home,
  `sources/govinfo/error_page.py`, which imports nothing from `spicy_docs` so
  a validator that needs only this rule need not import a source family. The
  two witnesses stay separable because callers interleave them differently:
  the Federal Register granule validator refuses an error-page URL, then a
  mismatched locator, then the marker, so a marker-bearing body at the wrong
  locator reports the locator. The page's byte length is its size today, not
  an identity rule.
- **The media type matches the format, the body is not empty, and a PDF begins
  with `%PDF-`.** A 200 that is not the requested format is a refusal with its
  bytes retained, never data and never absence.

## Granule bodies for the Record

The daily Record is `pdf`-only at package level, but its granules — one
speech, one page range — carry their own HTML. `GovInfoBodyAcquirer.
acquire_granule(package_id, granule_id, prefer=GRANULE_BODY_PREFERENCE)`
reads a granule's own summary and MODS, then its body, at the same
three-request shape `acquire` uses, and with identity proved before bytes the
same way:

- **The granule summary states `packageId` and `granuleId`.** Both must equal
  the request; a missing or mismatched granule answers `400`, not `404` --
  measured 2026-09-19 two ways: a wrong-day granule id under
  `CREC-2026-09-18`, and that fixture's own real granule id requested under
  `CREC-2026-09-17` instead. Neither body states `packageId` or `granuleId` at
  all (`{"message":"invalid granuleId"}`), so this reads as the field mismatch
  it is, typed `GovInfoPackageUnavailableError` the same way a package's own
  404/410 is.
- **The granule MODS states its own `accessId`, and its host package's,
  separately.** Its own sits directly under the root, the same shape a
  package MODS states its own accessId in; its host package's sits nested
  inside a `relatedItem type="host"` — GovInfo's own proof of membership, not
  an assumption from the request URL. Both are checked before any rendition
  is trusted.
- **The granule MODS states the rendition URL, from its own `location`
  only** (never the nested host's), at `granule_body_locator` — the package's
  folder, the granule's own file stem — the same offered/moved/other split
  `validate_package_mods` uses, shared through `_read_offered_renditions`.
- **A granule body carries a page-level marker, not a granule-level one.**
  `[Congressional Record Volume 172, Number 148 …] [Senate] [Page S4837]`
  names the issue and the page, but several granules can share one page (four
  of CREC-2026-09-18's eleven share `PgS4837`), so it cannot stand in for
  `granuleId` the way the Federal Register granule route's printed
  `[FR Doc No: ...]` marker can. Identity stays on the locator and MODS
  statement, exactly as for a package.
- The error-page and media-type rules are unchanged from a package body's.

`GRANULE_BODY_PREFERENCE` (`("htm", "pdf")`) defaults to the granule's own
HTML first, measured on CREC-2026-09-18 to be what every one of its 11
granules offers; its own PDF is the fallback, through the same granule
locator — not the whole-issue package PDF, which stays reachable unchanged
through `acquire(package_id)`.

## Bounds and measured basis

- Every summary, MODS, body request and retry spends the same `max_requests`.
  The two clients share it: whatever is left bounds the next call, including
  its retries. A skipped request is refused as `request-budget-exhausted`
  without implying a fetch was attempted.
- `max_body_bytes` and `max_metadata_bytes` must each be positive and at most
  24 MiB. Acquisition requests identity encoding, refuses other encodings,
  checks the stated length and bounds accumulated bytes through EOF. No partial
  body becomes evidence. Bodies above the bound refuse: the CHRG-119hhrg64242
  PDF (46.6 MB) is one. That is a bound, not a preference — `BODY_PREFERENCE`
  reaches PDF only after every text-bearing rendition, so a package that
  offers one is never asked for tens of megabytes, and a PDF-only package
  that exceeds the bound refuses on the bound and says so.
- Transport failures and HTTP 429/5xx retry with bounded exponential backoff.
  Request-start pacing applies across retries and successive acquisitions, and
  meters the keyed and keyless hosts separately, as they answer separately;
  zero disables it. The timeout bounds transport waits, not total elapsed time.
  These caller settings are not GovInfo rate-policy claims.
- Use one client sequentially and close it. Injected HTTPX transports must
  preserve streaming and add no hidden requests or authentication.
- The measured basis for every rule above is recorded in
  `tests/fixtures/govinfo_bodies/README.md` with the routes, dates and digests.

## What each refusal means

| Refusal | Meaning |
| --- | --- |
| `GovInfoPackageUnavailableError` | The exact locator said the object is not there: 404/410 on a keyed route, or a redirect on a body route. On a granule's summary or MODS route this is HTTP 400 instead, typed the same way when the 400's body is the documented `invalid granuleId` message -- GovInfo answers that way for a granule that does not belong to the requested package; any other 400 stays a generic refusal. It carries that capture. It is not a statement about other formats, packages or granules. |
| `GovInfoFormatNotOfferedError` | The package or granule stated its renditions and none was preferred. It carries `offered_formats`; no body request was made. |
| `GovInfoBodySourceError` | Identity or shape failed: a `packageId`, `granuleId`, `collectionCode` or `accessId` that differs, a final URL that differs, a wrong media type, an empty body, a PDF without its magic, or a bound exceeded. |
| `GovInfoRenditionAddressError` | The package or granule states a preferred format at an address this module does not derive. The publisher's own URL is on the error. Disagreement, not absence; no body request was made. |
| `GovInfoBodySourceError` naming the error page | The publisher's error page arrived as a 200. Its bytes are retained; it is a refusal, never absence. |
| `CredentialRefusedError` | HTTP 401/403, or a keyed response echoing the key. Stop the operation; do not continue with another route, package or granule. |

Every refusal attaches `refused_response` (`RefusedResponse`) with the exact
bytes where they exist, and `govinfo_body_acquisition` (`govinfo_granule_acquisition`
for `acquire_granule`) with the package id (and granule id), collection, stage
(`summary`, `mods` or `body`), preference, offered formats, chosen format,
consumed requests and effective budget. The context names the
active offending response: a failed body never labels the earlier successful
MODS as the refused one. A refusal returns no partial result.

## Result

`GovInfoPackageBody` is frozen and holds the parsed `identity`, the `format`
chosen, the `preference` asked for, `offered_formats`, the validated `summary`
(with its `download_links` as evidence), the validated `mods` (with
`moved_renditions`, `other_renditions` and `bills`) and `body` identities, the
three captures in request order, the consumed `request_count` and the
effective `budget`.

`PackageModsIdentity.bills` is every `<bill>` the MODS names, in the
publisher's own document order, read from the same root-level `extension`
children `accessId` and `collectionCode` already are. Document order is not
priority order: CRPT-119hrpt1's MODS lists S. 5 (`context="OTHER"`) before H.
Res. 53 (`context="PRIMARY"`), so `mods.bills[0]` names the wrong bill.
`mods.primary_bill` returns the one `<bill>` stating `context="PRIMARY"`, or
`None`, and is the accessor the committee-report transform uses instead of
re-parsing the MODS bytes itself. Each `ModsBill` keeps the publisher's own
`bill_type` spelling (`HRES`, `S`, `HR`, ...) alongside
`normalized_bill_type`, that spelling lower-cased to match
`sources.congress.bill_status.BILL_TYPES` — `None` when the lower-cased form
is not one of that vocabulary's entries, so a caller need not normalize
twice. A `<bill>` missing any of `congress`/`type`/`number`/`context` is
skipped, not guessed at.

`GovInfoGranuleBody` is the same shape for `acquire_granule`, with a
`GranuleIdentity` (the package and granule together), a `GranuleSummary` and a
`GranuleModsIdentity` (which also carries `host_package_ids`, the proof of
membership) in place of their package counterparts. Each capture carries its
requested and final URL, status, content type, observation time, exact bytes,
byte size and qualified SHA-256. To store one, pass its `sha256`, `byte_size`
and `[body]` to `SourceNativeBlobStore.put_blob` and keep the source facts
beside the returned reference.

