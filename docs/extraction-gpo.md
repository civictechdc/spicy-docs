# Normalize GPO PDF text after extraction

`extraction/gpo_normalize.py` is a post-extraction step: given the page texts
`extraction.DocumentExtractor` already produced, it strips the seven GPO
print artifacts BillTrax's `pdf-normalize.ts` named and rejoins the words
GPO's line-wrap hyphenates, keeping one output string per input page. It
takes no PDF, opens no file and makes no network request; it is a pure
function over `PageResult.text` values plus the `GpoCleanupRecord` accounting
of what it removed.

```python
from spicy_docs.extraction import DocumentExtractor, NativeText
from spicy_docs.extraction.gpo_normalize import normalize_gpo_pages

results = list(DocumentExtractor(NativeText()).extract(pdf_bytes, media_type="application/pdf"))
pages = tuple(result.text for result in results)
normalized_pages, cleanup = normalize_gpo_pages(pages)
```

## Extractor this was derived against

PyMuPDF 1.28.2, through this repo's default PDF reader
(`extraction.DefaultReader` → `extraction.NativeText` →
`extraction.DocumentExtractor`; see `extraction/pages.py::_PDFPage.native`
and [the extraction API doc](extraction/pdf-extraction-api.md)). That
strategy calls PyMuPDF's `page.get_text("dict")` and joins each line's spans,
one physical line of output text per PDF text line — this is the "PDF and
image extraction API" path, not the separate, optional
[`PypdfReader`](pdf-page-text.md) (`extraction/pypdf.py`), which returns
pypdf's own page strings and is not used here. BillTrax's rules were derived
against `pdf-parse`'s line layout, which is neither of these.

The line layout matters because two of BillTrax's seven artifacts changed
shape under this extractor and had to be re-derived, not just ported:

1. **Line numbers move from a suffix to their own line.** pdf-parse glued a
   GPO gutter line number onto the end of its content line
   ("Representa-1"). PyMuPDF never does this — it emits the number as its
   own physical line immediately after the content line. BillTrax's
   `detectLineNumbered` trailing-suffix regex accordingly never matches under
   this extractor (confirmed independently: the raw-data research's own
   `detectLineNumbered` measurements, computed the old way over PyMuPDF text,
   read `false` on every sampled document, including
   `BILLS-119hr4727ih`, which genuinely is gutter-numbered — see
   `docs/research/billtrax-raw-data-2026-09-19.md` §3, §6, and §7 Q3, which
   anticipated exactly this failure mode). `is_gpo_layout` instead detects a
   content line immediately followed by a bare one- or two-digit line, and
   the same adjacency gates hyphen-rejoin, preserving BillTrax's original
   scope: a trailing hyphen is only trusted as a print-wrap artifact when a
   gutter number corroborates it, never on a document without one.
2. **The footer is several physical lines, and the job-code line changed
   shape.** pdf-parse fused GPO's whole per-page print-shop footer
   ("VerDate … Jkt … PO … Frm … Fmt … Sfmt … E:\\…") onto one line; matching
   its first token dropped the whole thing. PyMuPDF splits it across
   8-9 physical lines, each of which must be matched and dropped on its own.
   BillTrax's job-code line pattern (`/^\w+ on DSK\w+ with \$/`, matching
   only a literal `DSK`-prefixed machine id and a literal trailing `$`) also
   no longer matches real 2025-session output, which has neither: measured
   examples are `ssavage on LAPJG3WLY3PROD with BILLS` and
   `abielarski on DSK125SN23PROD with HEARING`. The rule is generalized to
   any machine id ending `PROD` and any trailing job-code token (still
   matching BillTrax's own literal example).

The other five artifacts — the VerDate/DSK-line detectors that start the
rules above, bare page numbers, bullet bill identifiers, small-caps
single-letter splits, and doubled internal spaces from kerning — are kept
verbatim. Doubled internal spaces and non-breaking spaces were measured at
zero occurrences across all three real fixtures below; PyMuPDF's span
reconstruction does not reproduce pdf-parse's kerning artifact. Both rules
stay in place for compatibility (the same precedent BillTrax set for its own
always-`true` `spacingNormalized` field) and are marked unmeasured here
rather than removed.

## Rule table

| Rule | GPO artifact | Status |
| --- | --- | --- |
| `verdate_footer` | GPO print metadata footer, starting `VerDate …` | Re-derived: now also consumes the multi-line continuation (see artifact 2 above) |
| `dsk_user` | Document-processing user/job-code line | Re-derived: generalized machine-id and job-code shape (see artifact 2 above) |
| `bare_page_number` | Bare page number or per-line gutter number, 1-4 digits | Kept verbatim |
| `bullet_bill_id` | Bullet-prefixed bill identifier (`•HR 7148 IH`) | Kept verbatim; unmeasured on the three fixtures below (none contains one), confirmed still present under this extractor by the sidecar's other sampled bills (`BILLS-119hr9499rh`: 2, `BILLS-119s218is`: 4 — see `docs/research/billtrax-raw-data-2026-09-19.json`, `sources.billPdfTextArtifacts`) |
| gutter-number adjacency (`is_gpo_layout`) | Line-numbered IH-style layout | Re-derived: adjacency instead of trailing-suffix (see artifact 1 above) |
| small-caps merge | A lone uppercase letter split from the word it starts | Kept verbatim; unmeasured on the three fixtures below (none exercises it) |
| hyphen rejoin | Mid-word line-wrap break | Re-derived trigger (gutter adjacency instead of trailing-digit suffix); scope kept identical to BillTrax (gutter-numbered documents only) |
| space collapse | Multiple internal spaces from PDF kerning | Kept verbatim; measured at zero occurrences on all three fixtures under this extractor |

## Measured counts per fixture

Fixtures are `tests/fixtures/gpo_pdf_text/*.json` (extracted text, not the
PDF; provenance and sha256 in that directory's README). Full field-by-field
assertions are in `tests/extraction/test_gpo_normalize.py`.

| Fixture | Version | Pages | `line_numbers` | `gpo_footers` | `small_caps_merges` | `hyphen_rejoin_count` | Chars before → after |
| --- | --- | ---: | --- | --- | ---: | ---: | --- |
| `BILLS-119hr4727ih` | Introduced (IH) | 1 | `True` | `True` | 0 | 2 | 854 → 671 (21.4%) |
| `BILLS-119sconres1enr` | Enrolled (ENR) | 1 | `False` | `False` | 0 | 0 | 1,291 → 1,263 (2.2%) |
| `CRPT-119hrpt105` | Committee report | 3 | `False` | `True` | 0 | 0 | 7,111 → 6,537 (8.1%) |

`BILLS-119hr4727ih` is genuinely gutter-numbered (its six content lines are
each followed by their own line-number line, 1-6) and both of its real
hyphen wraps ("Representa-/tives", "relat-/ing") are correctly rejoined.

`BILLS-119sconres1enr` is not gutter-numbered, has no GPO footer on its one
page, and its own genuine hyphen wraps ("concur-/ring),", "President-/elect")
are left split — this is BillTrax's original scope, not a gap this port
introduced: see artifact 1 above.

`CRPT-119hrpt105` is a 3-page House Rules Committee report — not itself a
bill, so it is never gutter-numbered by GPO — with a full VerDate footer
(including its multi-line continuation and job-code line) on every page, and
its own hyphen-wrapped headings ("DEPART-/MENT OF THE TREASURY",
"RE-/PORTED FROM THE COMMITTEE ON RULES") stay split for the same reason.
`docs/research/billtrax-raw-data-2026-09-19.md` §6 measured this same
package and reached the same conclusion independently: applying the
normalizer here is "safe" because `detectLineNumbered` is false on all three
reports it sampled, so the hyphen-rejoin branch stays off, while the
VerDate filter removes real per-page footer lines (229 of them, on the
largest of the three).

## Concordance checks

`tests/extraction/test_gpo_normalize.py` implements both of BillTrax's
concordance scripts as tests over the fixtures, using its own token-overlap
measure (`validate-pdf-pdf-concordance.ts`'s `concordance()`):

- **PDF-vs-PDF.** An offline check normalizes the same captured extraction
  twice and asserts it is byte-identical (BillTrax's scenario 1,
  self-comparison, expected ~100%). The `integration`-marked, bounded,
  keyless live test (`test_live_ih_bill_pdf_matches_the_captured_fixture_
  after_independent_extraction`) does the same comparison against a second,
  independently fetched-and-extracted copy of `BILLS-119hr4727ih` — two real
  extractions of the same document, agreeing after normalization.
- **PDF-vs-XML.** Parametrized over the two bill fixtures, each checks for a
  matching bill-text XML sample and asserts token concordance at or above
  BillTrax's own retroactive criterion (`validate-pdf-xml-concordance.ts`:
  "β.5 ≥95%" mean heading concordance). Neither `BILLS-119hr4727ih` nor
  `BILLS-119sconres1enr` has a matching XML sample in this repo or in
  `docs/research/billtrax-raw-data-2026-09-19.json` (which recorded only
  line-count statistics for them, not XML text) — the sidecar's XML text
  fixtures under `tests/fixtures/govinfo_bills/` are for other bills
  (`119hr6028ih/eh`, `119hjres25enr`, `119s5enr`). Both cases are marked
  `pytest.skip` with that reason, per this port's own rule for an absent
  sample, rather than silently passed.

## Compared against upstream DeltaTrack

DeltaTrack (`civictechdc/DeltaTrack`, commit `c636448`) solves the same
problem — GPO PDF text cleanup, ahead of its own diff engine — and was
checked here for overlap before finishing this port.
`src/deltatrack/parsers/pdf_text.py` extracts with **pypdfium2 (PDFium)**,
not PyMuPDF: `docs/research/pdf-backend-bakeoff/README.md` there records that
choice as a **licensing** decision (PyMuPDF is AGPL-3.0; DeltaTrack ships
Apache-2.0 and will not carry an AGPL dependency without a separate
decision), not a quality verdict — the bakeoff explicitly keeps PyMuPDF in
as "a ceiling reference" for extraction quality, benchmark-only. It says
nothing against spicy-docs' own choice to depend on PyMuPDF directly.

That backend choice is why this module stays its own port rather than
becoming a thin adapter over `deltatrack.parsers.pdf_text`: PDFium's raw
text is a **third**, incompatible line shape, different from both
pdf-parse's (suffix-glued number) and PyMuPDF's (number on its own following
line). `pdf_text.py:31` anchors every rule on a **prefix** match,
`_NUMBERED_LINE = re.compile(r"^(\d{1,2}) (.*)$")`, because PDFium's reading
order puts the left-margin gutter digit before the line's content; and its
hyphen handling (`pdf_text.py:44`, `_HYPHEN_BREAK = re.compile(r"￾(\d{1,2}) ")`)
depends on a PDFium-specific soft-hyphen glyph (U+FFFE) that PyMuPDF never
emits. Feeding PyMuPDF's `PageResult.text` through those functions would not
raise — it would silently match nothing (no line starts with a digit; no
U+FFFE glyph exists) and return the input close to unchanged: exactly the
"formatting assertion, not a verification" failure shape, where a clean-
looking no-op result is indistinguishable from a working one without
re-deriving against the real output. Concretely, none of BillTrax's 27 ported
cases would survive being fed through DeltaTrack's parser literally (every
fixture's line-number shape is on the wrong side of the content), for the
same structural reason PyMuPDF's own shape needed this port re-derived from
BillTrax's original pdf-parse-shaped rules rather than just copied.

**Where a design carried over anyway (re-implemented, not imported).**
Two of DeltaTrack's choices are extractor-shape-independent enough that this
port adopted the same design, checked and re-derived against this repo's own
fixtures rather than assumed from theirs:

- Its footer rule (`pdf_text.py:72-73`,
  `_VERDATE_AND_BELOW = re.compile(r"\n?VerDate\b.*\Z", re.DOTALL)` at 72,
  `_WATERMARK_AND_BELOW` at 73, applied `pdf_text.py:164-165` inside
  `strip_page_chrome`, def at 149) truncates from `VerDate` to the end of
  the page instead of matching each field. This port independently reached
  and then adopted the same conclusion after measuring that a VerDate line
  is always its page's last line across every fixture here — see the module
  docstring's artifact 2 and `_strip_metadata` in `gpo_normalize.py`.
- Its glyph normalization (`pdf_text.py:179`, `normalize_glyphs`) collapses
  GPO's doubled-single-curly-quote convention (`‘‘…’’`) into one straight
  double quote (`pdf_text.py:192`, `text.replace("''", '"')`, after the
  curly-to-straight step). This port adopted the same collapse in
  `_normalize_encoding`, independently confirmed against
  `CRPT-119hrpt105`'s own `‘‘Review of Final Rule…’’` — see
  `test_collapses_gpos_doubled_single_quote_into_one_double_quote`.

**Where this port did not adopt a DeltaTrack design, with the measured
reason.** DeltaTrack's hyphen-rejoin (`pdf_text.py:213-241`,
`_merge_print_lines`) runs unconditionally on any line ending in an
alphanumeric character plus `-` whose next line starts lowercase — it does
not gate on gutter-numbering the way BillTrax's, and this port's, does. That
is broader recall (it would also rejoin ENR-style wraps BillTrax's own scope
leaves split), but it is measurably unsafe: `BILLS-119sconres1enr.json`
(real, captured GovInfo text) contains `"...inauguration of the
President-\nelect and the Vice President-elect..."`, where `President-elect`
is a genuine hyphenated compound, not a print-wrap, and happens to wrap at
its own hyphen. DeltaTrack's rule as written (`current.text.endswith("-")
and current.text[-2].isalnum() and parsed[next_i].text[:1].islower()`)
matches this exactly and would delete the hyphen, producing `Presidentelect`.
This port's gutter-adjacency gate (module docstring, artifact 1) correctly
leaves it split. Kept as this port's own, narrower rule rather than adopted
broader — see `test_cleans_enr_format_and_leaves_hyphen_wraps_unrejoined_
without_gutter_numbers`.

**Gaps found, to raise upstream, not fixed here** (out of this port's scope
— they are DeltaTrack's rules, not BillTrax's, and none is exercised by a
fixture in this repo):

- `_WATERMARK_AND_BELOW` (`pdf_text.py:73`) still requires a literal `DSK`
  substring (`\S+ on DSK\S*PROD with .*`). The real, non-`DSK`-prefixed
  machine id this port measured (`ssavage on LAPJG3WLY3PROD with BILLS`,
  `BILLS-119hr4727ih`) would not match it either. Likely masked in practice
  by `_VERDATE_AND_BELOW` running first on the same page (VerDate precedes
  the watermark in every sample either project has), but a latent gap if the
  watermark ever appears without a preceding VerDate match.
- `_RUNNING_FOOTER` (`pdf_text.py:68-71`) strips an **unbulleted** running
  bill-stage line (e.g. `HR 5895 PCS`, for print stages GPO does not prefix
  with a bullet) — an artifact neither BillTrax's `BULLET_BILL_RE` (requires
  a bullet character) nor this port's kept-verbatim `_BULLET_BILL_RE`
  handles. None of this port's three fixtures is a PCS/RDS/RFS print stage,
  so there is nothing here to re-derive the rule against; flagged, not
  built, per this port's own "unmeasured, not invented" rule.
- `compare/pdf.py:60` measured, over 60 real documents under PDFium, that
  numbered and unnumbered line-share populations are ~50x apart with an
  empty gap between them (unnumbered 0.16%-1.76%, numbered 90%-99.9%),
  independently corroborating that BillTrax's original 30% `is_gpo_layout`
  threshold (kept here) sits safely inside that gap. The same file
  (`compare/pdf.py:61-78`) also derives a 50-line floor before trusting the
  ratio at all, because short real documents can read an artificially low
  share even when genuinely numbered (21-28 lines at 18%-43%). This port
  keeps BillTrax's original 3-content-line floor unchanged: none of the
  fixtures here is that short, so there is no measurement of this repo's own
  numbers to justify moving it, but the concern is real and evidence-backed
  on a much larger corpus, worth a maintainer's look before `is_gpo_layout`
  is trusted on a very short document.

## Found but out of scope

Real 2025-2026 GPO output contains artifacts that were not among BillTrax's
seven and are not handled here, kept out of scope because they were not
measured to interfere with anything this normalizer or a downstream
text-driven parser reads:

- An end-of-measure "Æ" glyph line, once at the end of a bill's last page
  (seen in `BILLS-119hr4727ih`).
- Decorative cover-page glyphs decoding as stray punctuation lines (`"`,
  `!`) on a committee report's title page (seen in `CRPT-119hrpt105`, page
  1) — likely a dingbat/seal font PyMuPDF has no substitute glyph for.
- A GPO catalog/serial number line using an en dash (`59–008`, seen at the
  top of `CRPT-119hrpt105`, page 1).

None of these collide with the agency-block heading grammar
(`docs/research/billtrax-raw-data-2026-09-19.md` §6: a line 5-100 characters
matching one of 12 department/office/agency patterns, or any all-caps line of
two or more words) or with prose word counts, so they were left as noise
rather than given a rule with a sample size of one.

## Decision

See ["GPO PDF text normalization runs after extraction, gated by
evidence"](decisions.md#gpo-pdf-text-normalization-runs-after-extraction-gated-by-evidence)
in `docs/decisions.md`.

`sources/agency_reports/report_blocks.py`'s `parse_agency_blocks` takes
either a flat string or a `Sequence[PageResult]` directly, not this module's
`tuple[str, ...]` output, so the two are not yet wired together — a caller
still has to run `normalize_gpo_pages` over `DocumentExtractor` output and
hand the result to `parse_agency_blocks` itself (as a joined string, since
`PageResult` is not this module's to construct). That wiring, and doing the
same for any future bill-PDF section parser rather than each parser deciding
independently whether to normalize first, is for the maintainer landing the
caller to move into place.

This document and its rule table are for that maintainer to move into
wherever the extraction pipeline's own documentation index lives
(`docs/architecture.md` and its extraction pipeline listing were outside
this port's stated scope).
