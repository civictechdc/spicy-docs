# Parse agency-report blocks

SpicyDocs provides a pure, dependency-free splitter for committee-report text
into header-led blocks, and two aggregate functions over the rows such a
parser's output would populate. All three are a straight port of BillTrax's
`report-parser.ts` and the two read-side queries of `committee-reports.ts`
(`docs/research/billtrax-value-inventory-2026-09-19.md` §2.6, §1a). None of the
three does I/O.

This module is unrelated to the FOIA and Oversight.gov readers documented in
[`docs/sources/agency-reports.md`](agency-reports.md), despite living in the
same `sources/agency_reports/` package and having a similar name: those read
retained *agency accountability reports* (FOIA annual reports, Oversight.gov
evaluations); this one splits a *committee report* (a document Congress
produces about a bill) into per-heading blocks, with no shared code or format.

```python
from pathlib import Path
from spicy_docs.extraction.api import DocumentExtractor, NativeText
from spicy_docs.sources.agency_reports.report_blocks import parse_agency_blocks
from spicy_docs.interpretation.report_sections import agency_recurrence, sections_for_agency

# Plain text also works; a PageResult sequence additionally attributes each
# block's page_span.
pages = list(DocumentExtractor(NativeText()).extract(Path("report.pdf").read_bytes(), media_type="application/pdf"))
blocks = parse_agency_blocks(pages)

# The two aggregates take an iterable of joined row mappings -- shaped like
# whatever storage layer holds parsed blocks -- not a live query.
recurrence = agency_recurrence(rows, "DEPARTMENT OF DEFENSE")
sections = sections_for_agency(rows, bill_id, "DEPARTMENT OF DEFENSE")
```

## What this is not

Despite the name inherited from BillTrax, `parse_agency_blocks` is **not** an
agency-name detector. Measured on two real GovInfo committee reports (see
"Evidence" below), it fires on section titles -- `REPORT`, `R E P O R T`,
`C O N T E N T S`, `HOUSE OF REPRESENTATIVES`, `HURRICANE SANDY`,
`INTRODUCTION`, `COMMITTEE VOTES` -- exactly as readily as it fires on a real
heading like `DEPARTMENT OF THE ARMY`. It is a heading splitter that BillTrax
happened to point at committee reports, and its stored `report_sections` rows
carry that same mix, because this is the code that produced every one of
them. Treat a returned block's `agency` field as "the text of a heading",
never as "a verified federal agency."

It also expects **normalized** input. GPO line numbers, `VerDate`/`DSK`
footers and hyphenated line-wrap rejoining are a separate, sibling concern
(the `pdf-normalize` port, applied as a post-extraction step) -- this module
does not do that work itself. Feeding it raw, unnormalized extraction text
reproduces BillTrax's own measured defect: hyphen-wrapped headings whose tail
half becomes its own spurious block. As a narrow guard against the worst of
that -- not a substitute for real normalization -- a line is never treated as
a header if the line immediately before it ends with a word character
followed by a hyphen. See "Evidence" for the measured before/after effect of
that guard on two real reports, and for a case the guard does *not* catch (an
all-caps title-page sentence that happens to satisfy a named pattern by
coincidence, not by line-wrapping).

## `parse_agency_blocks`

`parse_agency_blocks(text_or_pages)` takes either a plain `str` or a
`Sequence[extraction.model.PageResult]` (the shape
`extraction.api.DocumentExtractor.extract` yields) and returns a tuple of
`AgencyBlock`:

| Field | Meaning |
| --- | --- |
| `agency` | The header exactly as spelled/trimmed, or `None` for a block with no header. |
| `agency_key` | BillTrax's exact match normalization (`agency.upper().strip()`), or `None` alongside `agency=None`. |
| `body` | The block's text, joined and trimmed exactly as BillTrax stored it in `report_sections.body`. |
| `pattern` | The name of the header pattern that matched (below), or the `preamble`/`full_report` sentinels. |
| `char_span` | Half-open `(start, end)` offsets into the flattened input text. |
| `page_span` | Inclusive `(first_page, last_page)`, or `None` when given plain text (no page boundaries to attribute). |

Blocks partition the whole input: every `char_span` is contiguous with its
neighbors, with no gap and no overlap, even where `body` (BillTrax's own
narrower, trimmed content) covers less than the span. Two things follow from
that guarantee, both new relative to BillTrax:

- Text before the first matched header -- BillTrax silently discards this --
  becomes its own block (`pattern="preamble"`, `agency=None`) when non-blank.
  A document with no header at all still gets BillTrax's own `"Full Report"`
  sentinel, not a preamble block; that is the zero-header case BillTrax
  already had a name for.
- A header with a blank body is still not stored as its own block, matching
  BillTrax's own row-level behavior (a header immediately followed by another
  header, or by nothing, never became a stored row) -- but its raw span is
  absorbed into an adjacent emitted block rather than vanishing.

### The header patterns

One table, in BillTrax's exact precedence order (`_match_header` returns the
first name whose pattern matches):

| # | Name | Catches | Reason / measured status |
| ---: | --- | --- | --- |
| 1 | `department` | `DEPARTMENT OF …` | The most common cabinet-level heading. Measured: fires correctly on `DEPARTMENT OF THE ARMY` (CRPT-113hrpt135). |
| 2 | `office` | `OFFICE OF …` | Sub-cabinet/executive offices. Measured: fires correctly on `OFFICE OF THE SECRETARY AND EXECUTIVE MANAGEMENT` (CRPT-113srpt77). |
| 3 | `bureau` | `BUREAU OF …` | Bureaus with their own account. Unmeasured -- neither real report names one. |
| 4 | `agency_for` | `AGENCY FOR …` | e.g. Agency for International Development. Unmeasured. |
| 5 | `national` | `NATIONAL … (ADMINISTRATION\|AGENCY\|FOUNDATION\|INSTITUTE\|SERVICE\|COUNCIL)` | The trailing org-type word disambiguates from a line that merely starts with "National" (`NATIONAL DEFENSE PROGRAMS` correctly does not match). Unmeasured as a hit. |
| 6 | `corps_of` | `CORPS OF …` | Army Corps of Engineers civil works. Unmeasured as a heading, though CRPT-113hrpt135 is entirely about it. |
| 7 | `united_states` | `UNITED STATES …` | e.g. United States Institute of Peace. Unmeasured. |
| 8 | `food_and` | `FOOD AND …` | Food and Drug Administration, Food and Nutrition Service. Unmeasured. |
| 9 | `general_services` | `GENERAL SERVICES …` | General Services Administration. Unmeasured. |
| 10 | `small_business` | `SMALL BUSINESS …` | Small Business Administration. Unmeasured. |
| 11 | `environmental` | `ENVIRONMENTAL …` | Environmental Protection Agency. Unmeasured as a heading; the name appears in CRPT-119hrpt105's body prose. |
| 12 | `federal` | `FEDERAL … (AGENCY\|COMMISSION\|BOARD\|AUTHORITY)` | e.g. Federal Trade Commission. Measured gap: does not match `FEDERAL DEPOSIT INSURANCE CORPORATION` (ends in "Corporation", not one of the four words) -- caught by the fallback below instead, so nothing is lost. |
| 13 | `all_caps_multiword` | Any other all-caps line, 2+ words | Measured as the single largest source of blocks on both real reports -- section titles, not agencies (see "What this is not"). |
| 14 | `generic_agency_header` | A single all-caps word, 5-100 characters | Last resort: drops the two-or-more-word requirement, so it catches a lone all-caps word standing alone on a line. |

A length gate (5-100 characters, BillTrax's own bound) applies before any
pattern is tried, headers included. `HEADER_PATTERNS`, `MIN_HEADER_CHARS` and
`MAX_HEADER_CHARS` are importable for a caller that wants to reason about the
same rules directly.

### Evidence: what real reports exercise

Three real, keyless GovInfo committee-report PDFs (`tests/fixtures/agency_reports/README.md`
has full provenance: URLs, SHA-256, the repo's own pymupdf-based extraction):

| Fixture | Real package | Pattern hits |
| --- | --- | --- |
| `crpt-119hrpt105.txt` | CRPT-119hrpt105 (3 pages, complete) | `all_caps_multiword`, `office`, `preamble` |
| `crpt-113hrpt135.txt` | CRPT-113hrpt135 (229 pages, 72 KB excerpt) | `all_caps_multiword`, `department`, `preamble` |
| `crpt-113srpt77.txt` | CRPT-113srpt77 (190 pages, 180 KB excerpt) | `all_caps_multiword`, `department`, `office`, `preamble` |

`bureau`, `agency_for`, `national`, `corps_of`, `united_states`, `food_and`,
`general_services`, `small_business`, `environmental` and
`generic_agency_header` are unmeasured against real data: kept because
BillTrax shipped them and porting means porting the precedence table whole,
not because a real report has been seen to need them.

**The hyphen-wrap guard, measured before/after** (header-line matches on the
exact fixture files, with and without the guard; `tests/test_report_blocks.py::test_the_hyphen_guard_measurably_drops_header_matches_on_real_reports`):

| Fixture | Before | After | Dropped |
| --- | ---: | ---: | ---: |
| `crpt-119hrpt105.txt` (complete) | 11 | 9 | 2 |
| `crpt-113hrpt135.txt` (excerpt) | 30 | 29 | 1 |
| `crpt-113srpt77.txt` (excerpt) | 139 | 139 | 0 |

The drop counts (2, 1, 0) match `hyphenWrapFragmentHeaders` in
`docs/research/billtrax-raw-data-2026-09-19.json` for these same three
packages exactly, confirming the guard removes precisely the measured
hyphen-wrap fragments and nothing else.

**What the guard does not catch.** CRPT-119hrpt105's cover page is one
run-on, all-caps sentence describing the resolution's subject (GPO sets an
H.Res. procedural report's whole title in caps). Two fragments of that
sentence happen to satisfy a real pattern on their own terms -- not by
hyphen line-wrap, so the guard does not apply -- and become their own
(spurious) blocks: `OFFICE OF THE COMPTROLLER OF THE CURRENCY OF THE DEPART-`
(matches `office`) and `THE RULE SUBMITTED BY THE ENVIRONMENTAL PROTECTION
AGENCY` (matches `all_caps_multiword`). This is the same underlying fact as
"What this is not" above: a line-oriented all-caps heuristic cannot
distinguish a real section heading from an all-caps sentence fragment, and
no attempt is made here to solve that; it is out of scope for a faithful
port.

## `agency_recurrence` and `sections_for_agency`

`spicy_docs.interpretation.report_sections` ports BillTrax's two read
aggregates (`committee-reports.ts:136-210`) as pure functions over an
iterable of `ReportSectionRow` mappings -- the joined shape across `bills`,
`committee_reports` and `report_sections` those queries read, not a live
database call.

`agency_recurrence(rows, agency_label, *, limit=20)` counts how many distinct
congresses have report language for `agency_label`, across every bill in
`rows`. It normalizes both the query label and each row's label
(`.upper().strip()`) before comparing, matching BillTrax exactly, and
reproduces two things the original SQL does that a naive re-reading would
not: `LIMIT` caps the raw matching rows *before* the per-congress dedup runs
(so duplicate rows for one congress can starve out an older one), and ties
within a congress are resolved by Python's stable sort (input order) rather
than MySQL's unspecified tie order. Neither is "fixed" here -- both are
carried over as measured, because this ports the query BillTrax actually
ran.

`sections_for_agency(rows, bill_id, agency_label)` returns every report
section for one bill naming `agency_label`, ordered by chamber. Unlike
`agency_recurrence`, it matches `agency_label` **exactly** -- case-sensitive,
untrimmed -- because that is what BillTrax's SQL did (`rs.agency_label = ?`,
no `UPPER`/`TRIM`). The two functions' inconsistent matching rules are kept,
not harmonized, because harmonizing them would stop this from being a port.

BillTrax's `getAgencyRecurrence(agencyLabel, currentBillId)` took a second
parameter, `_currentBillId`, that its own body never read
(`committee-reports.ts:136-138`) -- dead code, dropped here rather than
ported.

## What is measured and what is not

Measured: the twelve-plus-two pattern precedence against BillTrax's source
(`report-parser.ts:1-66`) line-for-line; the hyphen-wrap guard's effect on the
same three real reports BillTrax's own upload path would have received; full
character-span coverage (every block's span, concatenated, reconstructs the
input exactly) on both synthetic cases and all three real fixtures; both
aggregate functions against constructed row sets covering dedup, ordering,
the `LIMIT`-before-dedup interaction and the two functions' different match
rules.

Not measured: any pattern's true precision/recall against a labeled set of
real agency names (no such set exists; see "What this is not"); the `national`,
`corps_of`, `united_states`, `food_and`, `general_services`, `small_business`,
`bureau`, `agency_for` and `generic_agency_header` patterns against a real
report that needs them; `agency_recurrence`'s `LIMIT`-before-dedup interaction
against real duplicate-congress data (House and Senate reports for the same
congress both matching the query agency) -- only constructed.

## Decision

*For the maintainer to move to `docs/decisions.md` once settled; not yet a
ratified decision.*

This is parsing of an uploaded artifact (a committee report a user attaches
to a bill), not acquisition -- there is no publisher endpoint to fetch here,
and `parse_agency_blocks`/`agency_recurrence`/`sections_for_agency` take
already-retrieved text and rows, exactly like `bill_tree.py` takes already-
fetched bill XML. That is why the parser lives under `sources/agency_reports/`
(alongside the other publisher-format-to-typed-fields parsers) and the two
aggregates live under `interpretation/` (shared logic over the facts those
parsers produce), rather than either gaining any fetch code of its own. The
GovInfo CRPT package body that would feed `committee_reports.text` in a
hosted system is a separate, already-existing concern
(`sources/govinfo/body_acquisition.py`); this module does not depend on it
and is tested entirely offline, against retained fixtures.
