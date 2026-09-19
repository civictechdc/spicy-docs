# Normalize GPO PDF text after extraction

`extraction/gpo_normalize.py` is a post-extraction step: given the page texts
`extraction.DocumentExtractor` already produced, it strips the seven GPO
print artifacts BillTrax's `pdf-normalize.ts` named, an eighth ported later
from DeltaTrack (the unbulleted running bill-stage footer — see "Where this
port now matches a DeltaTrack rule" below), and rejoins the words GPO's
line-wrap hyphenates, keeping one output string per input page. It takes no
PDF, opens no file and makes no network request; it is a pure function over
`PageResult.text` values plus the `GpoCleanupRecord` accounting of what it
removed.

```python
from spicy_docs.extraction import DocumentExtractor, NativeText
from spicy_docs.extraction.gpo_normalize import normalize_gpo_pages

results = list(DocumentExtractor(NativeText()).extract(pdf_bytes, media_type="application/pdf"))
pages = tuple(result.text for result in results)
normalized_pages, cleanup = normalize_gpo_pages(pages)
```

This pair is the PDF branch of
[`extraction/body_text.py`](sources/govinfo-bodies.md#turning-a-body-into-text),
which runs it for a caller holding a fetched `pdf` rendition and gives the
other three renditions their own derivation; `normalize_gpo_glyphs`, the line
ending and quote rule this module opens with, is shared with all of them.

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
zero occurrences across all four real fixtures below; PyMuPDF's span
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
| `bullet_bill_id` | Bullet-prefixed bill identifier (`•HR 7148 IH`) | Kept verbatim; unmeasured on the first three fixtures below (none contains one), confirmed still present under this extractor by the sidecar's other sampled bills (`BILLS-119hr9499rh`: 2, `BILLS-119s218is`: 4 — see `docs/research/billtrax-raw-data-2026-09-19.json`, `sources.billPdfTextArtifacts`) |
| `running_footer` | Unbulleted running bill-stage line (e.g. `HR 5895 PCS`) | Ported from DeltaTrack's `_RUNNING_FOOTER` (`pdf_text.py:68-71`, built for its own #140), with one addition upstream's own rule does not need: it strips only when the *next* line is not itself a bare gutter number, so a real numbered content line that happens to share the shape is not deleted with its digit — see ["Where this port now matches a DeltaTrack rule"](#where-this-port-now-matches-a-deltatrack-rule-not-imported-ported) below |
| gutter-number adjacency (`is_gpo_layout`) | Line-numbered IH-style layout | Re-derived: adjacency instead of trailing-suffix (see artifact 1 above); at or above a minimum content-line floor the ratio alone decides, below it a page's gutter digits must also form a consecutive run starting at 1 — same section below |
| small-caps merge | A lone uppercase letter split from the word it starts | Kept verbatim; unmeasured on the four fixtures below (none exercises it) |
| hyphen rejoin | Mid-word line-wrap break | Re-derived trigger (gutter adjacency instead of trailing-digit suffix); scope kept identical to BillTrax (gutter-numbered documents only), gated by the same layout verdict as gutter-number adjacency above |
| space collapse | Multiple internal spaces from PDF kerning | Kept verbatim; measured at zero occurrences on all four fixtures under this extractor |

## Measured counts per fixture

Fixtures are `tests/fixtures/gpo_pdf_text/*.json` (extracted text, not the
PDF; provenance and sha256 in that directory's README). Full field-by-field
assertions are in `tests/extraction/test_gpo_normalize.py`.

| Fixture | Version | Pages | Content lines | `line_numbers` | `gpo_footers` | `running_footer_lines` | `small_caps_merges` | `hyphen_rejoin_count` | Chars before → after |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | --- |
| `BILLS-119hr4727ih` | Introduced (IH) | 1 | 19 | `True` | `True` | 0 | 0 | 2 | 854 → 675 (21.0%) |
| `BILLS-119sconres1enr` | Enrolled (ENR) | 1 | 30 | `False` | `False` | 0 | 0 | 0 | 1,291 → 1,263 (2.2%) |
| `CRPT-119hrpt105` | Committee report | 3 | 146 | `False` | `True` | 0 | 0 | 0 | 7,111 → 6,537 (8.1%) |
| `BILLS-119hr1009rfs` | Referred in Senate (RFS) | 2 | 28 | `True` | `True` | 1 | 0 | 2 | 1,412 → 1,034 (26.8%) |

`BILLS-119hr4727ih` is genuinely gutter-numbered (6 of its 19 content lines
are each followed by their own line-number line, 1-6, a consecutive run
starting at 1) and 19 sits under the minimum-content-line floor described
below, so it is the structural run test, not the ratio alone, that clears
`line_numbers` here — both real hyphen wraps ("Representa-/tives",
"relat-/ing") correctly rejoin. Its page-number lines strip on either
evidence: the page's own VerDate/DSK footer, or the (now `True`) layout
verdict (see `GpoPageCleanup.bare_page_number_evidence`).

`BILLS-119sconres1enr` is not gutter-numbered, has no GPO footer on its one
page, and its own genuine hyphen wraps ("concur-/ring),", "President-/elect")
are left split — this is BillTrax's original scope, not a gap this port
introduced: see artifact 1 above. (Its 30 content lines are also under the
floor, but neither the ratio — 0 numbered — nor the run test finds anything
to work with either way.)

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

`BILLS-119hr1009rfs` is the fourth fixture, added to exercise the
`running_footer` rule: none of the first three is a PCS/RDS/RFS print stage,
so none carries the unbulleted running bill-stage line the rule strips. It is
a short Senate-received postal-facility-naming act (H.R. 1009, 119th
Congress); page 2 opens with `HR 1009 RFS`, stripped once. Genuinely
gutter-numbered (12 of its 28 content lines are each followed by their own
line number) and, like `BILLS-119hr4727ih`, under the minimum-content-line
floor — but it also demonstrates the run test's per-page aggregation: page
1's own run is only 2 long (1, 2, short of the 3 required), while page 2's is
10 long (1 through 10), which is sufficient on its own, the same way one
page's own footer evidence is enough for `gpo_footers`. Both real hyphen
wraps rejoin: "Representa-/tives" on page 1, and "reg-/ulation" on page 2.

## Where this port now matches a DeltaTrack rule (not imported, ported)

Validated against upstream DeltaTrack at commit `c636448`
(`docs/research/deltatrack-upstream-issues-2026-09-19.md`, claims B2 and B3):
these two rules were previously listed below as gaps to raise upstream, on
the mistaken premise that upstream lacked them. Both are upstream features
this port lacked, not upstream gaps, so both are now ported into
`gpo_normalize.py` instead:

- **The unbulleted running bill-stage footer.** DeltaTrack's `_RUNNING_FOOTER`
  (`pdf_text.py:68-71`) strips a line like `HR 5895 PCS` — a print-stage tag
  GPO does not bullet, which neither BillTrax's `BULLET_BILL_RE` nor this
  port's own `_BULLET_BILL_RE` catches. Upstream built it for its own #140
  (closed), with corpus evidence there (`diff_pdfs` on two real versions of
  the same bill reported `{'modified': 125}` against an XML-diff truth of
  `{'modified': 1}`; 80 of 125 hunks were footer-only; the footer appeared on
  181 of 184 pages). None of this port's first three fixtures is a
  PCS/RDS/RFS print stage, so a fourth, `BILLS-119hr1009rfs`, was added
  specifically to exercise it — see the measured counts above. Ported with
  one addition of this port's own, caught in review: DeltaTrack's rule
  strips the line unconditionally, but a real numbered content line can
  coincidentally share the same shape, and deleting it would delete its
  gutter number along with it — this port's rule strips only when the next
  physical line is not itself a bare gutter number, keeping the real
  `HR 1009 RFS` (followed by prose) stripped while a coincidental match
  (followed by its own digit) is kept as content instead.
- **The minimum-size floor on the numbered-ratio layout verdict — ported for
  intent, not for its constant.** DeltaTrack derived, over 60 real corpus
  PDFs, that a numbered/unnumbered ratio is not evidence below
  `_MIN_LINES_FOR_GUARD = 50` content lines (`compare/pdf.py:85`, derivation
  table at `:62-78`): a hard cliff between 28 and 29 judged lines (minimum
  accepted ratio 0.4286 → 0.5517), with 50 chosen for a comfortable margin
  past it. That 50 was derived for a **document-wide** ratio guard over a
  corpus with no comparable page concept; this port's own signal is
  **structural per page** — a content line immediately followed by its own
  digit line — so porting the constant alone regressed the common case: a
  first pass flipped both genuinely gutter-numbered fixtures above
  (`BILLS-119hr4727ih` at 19 content lines, ratio 0.316; `BILLS-119hr1009rfs`
  at 28, ratio 0.429) to `line_numbers=False`, leaving their real hyphen
  wraps split. Caught in review and corrected: at or above the 50-line floor
  the ratio alone still decides, as before, but below it a page also has to
  carry a **consecutive run of gutter digits starting at 1, at least three
  long** (`_MIN_GUTTER_RUN_LENGTH`) — GPO's own gutter numbering restarts at
  1 on every page and steps by one per typeset line, which a footnote marker
  or outline number need not do. Evaluated per page and aggregated the same
  way `page_has_footer` is (any one page's evidence is enough): on
  `BILLS-119hr1009rfs`, page 1's own run is only 2 long, but page 2's is 10,
  which alone recovers the whole document. **Residual false positive:** a
  numbered outline whose own numbers sit on their own lines and happen to
  restart at 1 on every page would pass this test too — indistinguishable
  from real GPO numbering by this signal alone. The run test is validated on
  this repo's four real fixtures plus synthetic cases below the floor (a
  page with digits 1, 2, 4; five footnote-style markers split across two
  pages that number straight through, 1-2 then 3-4-5, rather than restarting
  at 1 on the second page), not against a corpus the way upstream's 50 was.
  Upstream's own residual — a genuinely unnumbered document under 50 lines
  is still exempt from its decline-guard — is tracked in its **#261** (open,
  following closed #141) and its active research spike **#679** (open); this
  port's floor is a different mechanism entirely, gating a *positive*
  layout verdict rather than a decline, which is what keeps hyphen-rejoin
  from trusting an under-evidenced hyphen (see "Where this port did not
  adopt a DeltaTrack design" below).

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
- **PDF-vs-XML.** Parametrized over the three bill fixtures (the committee
  report has no bill-text XML counterpart to compare against, so it is not
  included), each checks for a matching bill-text XML sample and asserts
  token concordance at or above BillTrax's own retroactive criterion
  (`validate-pdf-xml-concordance.ts`: "β.5 ≥95%" mean heading concordance).
  None of `BILLS-119hr4727ih`, `BILLS-119sconres1enr` or
  `BILLS-119hr1009rfs` has a matching XML sample in this repo or in
  `docs/research/billtrax-raw-data-2026-09-19.json` (which recorded only
  line-count statistics for the first two, and predates the third) — the
  sidecar's XML text fixtures under `tests/fixtures/govinfo_bills/` are for
  other bills (`119hr6028ih/eh`, `119hjres25enr`, `119s5enr`). All three
  cases are marked `pytest.skip` with that reason, per this port's own rule
  for an absent sample, rather than silently passed.

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
  `normalize_gpo_glyphs`, independently confirmed against
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
its own hyphen. Run through DeltaTrack's **real** page pipeline
(`normalize_raw` → `strip_page_chrome` → `_parse_print_lines` →
`_merge_print_lines`, as `extract_clean_pages` composes them at
`pdf_text.py:526-528`) that becomes `Presidentelect` — a word that appears
nowhere in the bill — and the same sentence reshaped into DeltaTrack's own
numbered GPO layout corrupts identically, while a true print-wrap control
("Representa-"/"tives") rejoins correctly. The rule *as printed*
(`current.text.endswith("-") and current.text[-2].isalnum() and
parsed[next_i].text[:1].islower()`) does **not** match this fixture if fed
literally: the captured line ends `"President- "`, with a trailing space, so
`.endswith("-")` is `False` and the rule declines. It only fires once
`normalize_raw` (`pdf_text.py:128-146`) strips that trailing space at `:145`
— which is exactly what the real pipeline does first, at `:526`. This port's
gutter-adjacency gate (module docstring, artifact 1) correctly leaves it
split regardless of feed order. Kept as this port's own, narrower rule rather
than adopted broader — see `test_cleans_enr_format_and_leaves_hyphen_wraps_
unrejoined_without_gutter_numbers`.

This is a real gap worth raising upstream — DeltaTrack's own pipeline
corrupts a genuine compound word, not just an artificial feed order — and it
is the mirror image of DeltaTrack's own open **#650** ("Words split across a
printed line stay broken in the exported bill text when the continuation is
uppercase"): #650 is the false *negative* (an uppercase continuation left
split), this is the false *positive* (a lowercase continuation wrongly
joined), and both follow from the same test #650 already calls "not
decidable from the PDF alone." See
`docs/research/deltatrack-upstream-issues-2026-09-19.md` (claim B4) for the
full suggested issue text, written as a sibling to #650 with the corrected
mechanism above — a maintainer who tries the literal reproduction first will
see it decline and may close a report that skips this correction.

**Gaps found, to raise upstream, not fixed here** (out of this port's scope
— it is DeltaTrack's rule, not BillTrax's, and it is not exercised by a
fixture in this repo):

- `_WATERMARK_AND_BELOW` (`pdf_text.py:73`) still requires a literal `DSK`
  substring (`\S+ on DSK\S*PROD with .*`). The real, non-`DSK`-prefixed
  machine id this port measured (`ssavage on LAPJG3WLY3PROD with BILLS`,
  `BILLS-119hr4727ih`) would not match it either. Likely masked in practice
  by `_VERDATE_AND_BELOW` running first on the same page (VerDate precedes
  the watermark in every sample either project has), but a latent gap if the
  watermark ever appears without a preceding VerDate match. See
  `docs/research/deltatrack-upstream-issues-2026-09-19.md` (claim B1) for
  the suggested issue text.

The unbulleted running-footer rule and the numbered-ratio floor that used to
be listed here were both misdescribed as upstream gaps — DeltaTrack already
has both, shipped for its own #140 and #261 respectively — and are now
ported into this module instead; see ["Where this port now matches a
DeltaTrack rule"](#where-this-port-now-matches-a-deltatrack-rule-not-imported-ported)
above.

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

## Corpus validation

Gap B6 (`docs/research/closing-the-gaps-2026-09-19.md`): the four fixtures
above and the synthetic below-floor cases establish this normalizer's rules,
not its coverage across GPO's own real variety of bill print stages,
Congresses and document families. This section pins a wider run: 42
documents run through `extraction.body_text`'s PDF branch (PyMuPDF, then
`normalize_gpo_pages`) — 36 GPO bill PDFs, 5 committee reports, 1
Congressional Record issue — the way upstream DeltaTrack validated its own
50-line floor on 60.

**Corpus.** 36 bills spanning every print stage the task named (`ih`, `is`,
`rh`, `rs`, `eh`, `es`, `enr`, `rfs`, `pcs`, `ats`) plus six more the sealed
vocabulary in `sources/congress/bill_versions.py` names as measured in the
119th BILLS census (`rds`, `cps`, `eas`, `eah`, `rfh`, `rhuc`) — 30 from the
119th Congress, 6 from the 113th; 5 committee reports — 4 House (3 from the
119th, 1 from the 113th), 1 Senate (113th; `CRPT-113srpt77`, whose `srpt`
code maps to `senate` in `committee_report_tables.py`); 1 Congressional
Record issue (`CREC-2026-09-18`). Three bill entries and one report reuse
the page text already captured in `tests/fixtures/gpo_pdf_text/*.json`
rather than re-fetching it (marked `reused_fixture` in the pinned JSON
below); every other row is this run's own live capture.

Forty bills, not the full forty the task named, is a request-budget
consequence stated up front rather than padded past: CRPT/CREC each cost
three requests (`GovInfoBodyAcquirer.acquire`'s summary, MODS and body, keyed
via `read_api_key(Path(".env"), "API_GOV")`, header-only), so five reports
and one Record issue already spend 18 of the stated 50-request bound; one
keyless bulk-listing request (`bulkdata/json/BILLS/113/1/hr`) found real
113th package ids at no further discovery cost, and every 119th bill id was
already known from `docs/research/billtrax-raw-data-2026-09-19.md`'s own
measured PDF-sample and version-code-census tables (both keyless-fetched
there, at that document's own request cost, not this run's) — so this run's
own count is exactly 50: 2 discovery (one of them a retry after an empty
first response) + 33 keyless BILLS GETs + 15 keyed CRPT/CREC requests. 36
bills, not 40, is what that ceiling bought once the reports and the record
kept their fixed cost.

**Method.** Every fresh capture: `httpx.Client(follow_redirects=True)` at
`package_body_locator(package, "pdf")` for a bill (one request, checked for
a `%PDF` signature so a redirected "not offered" error page is never
mistaken for a body), or `GovInfoBodyAcquirer.acquire(package,
prefer=("pdf",))` for a report or the Record issue. `content_lines`,
`line_numbers`, `gpo_footers` and `hyphen_rejoin_count` are
`GpoCleanupRecord` fields read directly, not re-derived. `gutter_digits_leaked`
counts a standalone 1-2 digit line surviving in the *normalized* text of a
document the verdict called numbered. `footers_left` counts a `VerDate` or
job-code line surviving normalization. `false_rejoin_count` replays
`_rejoin_hyphens`'s own gate-then-merge steps to recover the word each
rejoin actually produces (mutating the same working list the real function
does, so a multi-hyphen chain reports its one final word rather than an
intermediate fragment), then checks each result against a wordlist built
from `/usr/share/dict/words` plus every one of the document's own content
lines *not* corroborated by an adjacent gutter number, with light suffix
stemming (`-s`, `-es`, `-ies`, `-ing`, `-ed`, doubled-consonant undo) — a
plain exact match against a 1934-vintage headword list flags most ordinary
plurals and participles as "unknown," which would make the check meaningless
noise rather than a signal.

**Results.**

| Document | Stage | Congress | Pages | Verdict | Leaked | Footers left | Rejoins | False rejoins | Time (ms) |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `BILLS-113hr1033rfs` | rfs | 113 | 5 | `True` | 0 | 0 | 17 | 0 | 19.9 |
| `BILLS-113hr1095rh` | rh | 113 | 6 | `True` | 0 | 0 | 17 | 0 | 26.8 |
| `BILLS-113hr1151pcs` | pcs | 113 | 10 | `True` | 0 | 0 | 45 | 0 | 38.0 |
| `BILLS-113hr1636ih` | ih | 113 | 4 | `True` | 0 | 0 | 15 | 0 | 20.2 |
| `BILLS-113hr3487enr` | enr | 113 | 2 | `False` | 0 | 0 | 0 | 0 | 9.1 |
| `BILLS-113hr674eh` | eh | 113 | 6 | `True` | 0 | 0 | 23 | 1 | 17.8 |
| `BILLS-119hconres11eh` | eh | 119 | 4 | `True` | 0 | 0 | 0 | 0 | 44.0 |
| `BILLS-119hconres26ih` | ih | 119 | 10 | `True` | 0 | 0 | 11 | 0 | 48.0 |
| `BILLS-119hjres174ih` | ih | 119 | 2 | `True` | 0 | 0 | 2 | 0 | 9.1 |
| `BILLS-119hr1009rfs` | rfs | 119 | 2 | `True` | 0 | 0 | 2 | 0 | 0.1 |
| `BILLS-119hr1834rhuc` | rhuc | 119 | 36 | `True` | 0 | 0 | 166 | 4 | 152.5 |
| `BILLS-119hr1eas` | eas | 119 | 870 | `True` | 0 | 0 | 4364 | 71 | 3513.2 |
| `BILLS-119hr4275rfs` | rfs | 119 | 435 | `True` | 0 | 0 | 2331 | 22 | 1911.8 |
| `BILLS-119hr4323rds` | rds | 119 | 19 | `True` | 0 | 0 | 84 | 0 | 82.5 |
| `BILLS-119hr4727ih` | ih | 119 | 1 | `True` | 0 | 0 | 2 | 0 | 0.1 |
| `BILLS-119hr8800eh` | eh | 119 | 2586 | `True` | 0 | 0 | 14244 | 185 | 11209.3 |
| `BILLS-119hr8800rh` | rh | 119 | 1614 | `True` | 0 | 0 | 8515 | 134 | 8438.4 |
| `BILLS-119hr8870ih` | ih | 119 | 1005 | `True` | 0 | 0 | 4953 | 74 | 4453.1 |
| `BILLS-119hr9499rh` | rh | 119 | 4 | `True` | 0 | 0 | 4 | 0 | 14.0 |
| `BILLS-119hres426rh` | rh | 119 | 4 | `True` | 0 | 0 | 6 | 0 | 22.7 |
| `BILLS-119s1051rfh` | rfh | 119 | 8 | `True` | 0 | 0 | 36 | 0 | 35.0 |
| `BILLS-119s1071eah` | eah | 119 | 3022 | `True` | 0 | 0 | 16356 | 177 | 13197.0 |
| `BILLS-119s1071enr` | enr | 119 | 1259 | `False` | 0 | 0 | 0 | 0 | 10312.0 |
| `BILLS-119s218is` | is | 119 | 5 | `True` | 0 | 0 | 25 | 1 | 26.0 |
| `BILLS-119s2296es` | es | 119 | 3100 | `True` | 0 | 0 | 17354 | 228 | 13211.4 |
| `BILLS-119s3612is` | is | 119 | 24 | `True` | 0 | 0 | 130 | 4 | 105.8 |
| `BILLS-119s3971cps` | cps | 119 | 40 | `True` | 0 | 0 | 197 | 4 | 167.4 |
| `BILLS-119s4784rs` | rs | 119 | 1562 | `True` | 0 | 0 | 8810 | 135 | 8114.4 |
| `BILLS-119s5066is` | is | 119 | 2009 | `True` | 0 | 0 | 11212 | 191 | 9042.1 |
| `BILLS-119s515is` | is | 119 | 1 | `True` | 0 | 0 | 1 | 0 | 5.9 |
| `BILLS-119sconres1enr` | enr | 119 | 1 | `False` | 0 | 0 | 0 | 0 | 0.1 |
| `BILLS-119sconres39pcs` | pcs | 119 | 70 | `True` | 0 | 0 | 139 | 1 | 285.5 |
| `BILLS-119sjres104is` | is | 119 | 4 | `True` | 0 | 0 | 8 | 0 | 18.2 |
| `BILLS-119sjres141is` | is | 119 | 2 | `True` | 0 | 0 | 2 | 0 | 8.7 |
| `BILLS-119sres660ats` | ats | 119 | 3 | `True` | 0 | 0 | 5 | 0 | 14.3 |
| `BILLS-119sres94rs` | rs | 119 | 54 | `True` | 0 | 0 | 261 | 0 | 256.1 |
| `CRPT-113hrpt135` | report | 113 | 229 | `False` | 0 | 0 | 0 | 0 | 1444.9 |
| `CRPT-113srpt77` | report | 113 | 190 | `False` | 0 | 0 | 0 | 0 | 1725.3 |
| `CRPT-119hrpt1` | report | 119 | 4 | `False` | 0 | 0 | 0 | 0 | 35.9 |
| `CRPT-119hrpt105` | report | 119 | 3 | `False` | 0 | 0 | 0 | 0 | 0.2 |
| `CRPT-119hrpt2` | report | 119 | 3 | `False` | 0 | 0 | 0 | 0 | 27.4 |
| `CREC-2026-09-18` | record | — | 3 | `False` | 0 | 0 | 0 | 0 | 24.5 |

Full per-document detail (URL, sha256, byte size, a sample of the flagged
false-rejoin words) is pinned in
[`tests/fixtures/gpo_pdf_text/corpus-2026-09-19.json`](../../tests/fixtures/gpo_pdf_text/corpus-2026-09-19.json),
asserted against by `tests/extraction/test_gpo_corpus_table.py`. No PDF bytes
are committed anywhere; the fetched bytes, the four measurement scripts and
this run's full console output (including the two failed 404-shaped retries
folded into the request count above) are retained outside the repository as
the campaign receipt, per `AGENTS.md`, at
`~/Work/corpora/supply-2026-09-02/receipts/gpo-normalizer-corpus-2026-09-19/`.

**Layout verdict versus expectation.** Every introduced (`ih`/`is`) and
reported (`rh`/`rs`) bill is `True`; every enrolled bill and every committee
report is `False` — zero disagreements across all 42 documents, but only
after two rule defects the corpus surfaced were fixed (see
`extraction/gpo_normalize.py`, `_layout_verdict`'s own docstring for the
full derivation):

1. **`BILLS-119sjres141is`** (introduced in the Senate) and
   **`BILLS-119hconres11eh`** (engrossed) both landed at a numbered/content
   ratio of *exactly* 0.30 with a genuine per-page consecutive run
   confirming real GPO numbering on inspection — and both reported
   `line_numbers=False`, because the ratio gate used a strict `> 0.3`. Fixed
   to `>= 0.3`.
2. **`BILLS-119hconres26ih`**, a 10-page House concurrent resolution, has a
   six-page unnumbered "Whereas" preamble (a print convention this
   resolution type uses; a plain bill's enacting clause carries no
   comparable preamble) before its "Resolved" operative text begins. Its
   whole-document ratio (0.268) is genuinely under 30%, not a boundary tie,
   despite four pages — 70 of its 261 content lines — each showing an
   unambiguous consecutive run from 1, one of them 25 long. The per-page
   run test used to run only *below* the 50-line floor; it now runs at or
   above it too, as an alternative to the ratio rather than a corroboration
   of it. Reading the page settled which side was right: pages 7-10 are
   real, unmistakable GPO gutter numbering.

Both fixes are covered by new tests
(`test_true_below_the_floor_on_an_exact_thirty_percent_ratio`,
`test_true_at_or_above_the_floor_when_a_long_unnumbered_preamble_dilutes_the_ratio_but_a_page_shows_a_real_run`)
alongside a third
(`test_false_below_the_floor_when_a_real_run_exists_but_the_ratio_is_too_low`)
that locks in the more conservative half of the fix: below the floor, a
per-page run still cannot decide the verdict alone, unchanged from the
original design — only the fix's over-broad first draft (caught in review
before landing, not in this corpus) would have regressed that.

**Gutter digits leaked and footers left: zero, on every one of the 42
documents.** No standalone 1-2 digit line survives in a numbered document's
normalized text, and no `VerDate`/job-code line survives normalization
anywhere in the corpus — both artifacts the evidence-gated bare-digit rule
and the footer-truncation rule exist specifically to remove, and both
continue to work at this corpus's full range of document sizes (1 page to
3,100 pages) and vintages (113th and 119th Congress print).

**Hyphen rejoin: 89,337 merge operations, 70,054 resulting words checked, 1,232
flagged as not a known word (1.76%), 659 of them distinct.** Every flagged
case sampled by reading its page (a representative cross-section, not an
exhaustive audit of 1,232 instances) falls into one of three shapes, none a
parsing defect:

- **A genuine compound word's own hyphen coincided with the print-wrap
  point.** Seen across many fixtures: `communitybased`, `longterm`,
  `evidencebased`, `spacebased`, `thirdparty`, `chairperson`-style compounds
  where GPO's line wrap happened to land exactly at the compound's real
  hyphen, which the rule then strips along with the wrap — the same
  ambiguity already documented for the non-numbered case
  (`docs/research/deltatrack-upstream-issues-2026-09-19.md`, claim B4,
  "President-elect") but now measured, for the first time, on confirmed
  gutter-numbered text. A handful are three-word compounds
  (`off-the-shelf`, `case-by-case`) where the coincidence claims only the
  *first* hyphen, leaving a visibly odd but not corrupted result
  (`offthe-shelf`) — read on the page (`BILLS-119hr8800eh`, page 94): "...
  commercially available, off-" / "2" / "the-shelf components ...", a real
  wrap at a real hyphen, same mechanism, more visible result.
- **A proper noun or a modern/technical compound the 234,456-word system
  dictionary does not carry at all.** `/usr/share/dict/words` is macOS's
  1934-vintage Webster's Second headword list, and it is missing more than
  a first read suggests: re-checked directly on this machine
  (`grep -ic '^coordinate$' /usr/share/dict/words` and the same for
  `^co-ordinate$`), it carries `coordinate` in *neither* spelling, hyphenated
  or not — both return 0. The flagged instance in `BILLS-119hr8870ih`'s
  rejoin sample is a correct rejoin of an ordinary word the list simply
  never had, not a hyphenated headword the rejoin missed. Likewise no
  `database` (flagged in `BILLS-119s3971cps`) and no `Díaz-Canel` (read on
  the page, `BILLS-119s218is`, page 2: "...of Raúl Castro and his successor,
  Miguel Díaz-" / "3" / "Canel;" — a correct rejoin of a real name, flagged
  only because the check's own regex captured just the ASCII tail "az"
  before the diacritic).
- **An ordinary word whose base form the dictionary carries, but whose
  inflection the analysis script's own stemmer cannot reduce to it.** The
  largest of the three shapes in the sample read. The script's suffix
  stripper (strips `-s`, `-es`, `-ies`, `-ing`, `-ed`, and undoes a doubled
  final consonant — see `_stem_candidates` in the receipt's
  `analyze_all.py`) has no rule for the `-y` → `-ied` shift a regular verb
  ending in a consonant plus `y` takes in the past tense: `specified`
  (flagged in `BILLS-119hr1834rhuc`) never reduces to `specify`, and
  `identified` (flagged in `BILLS-119hr4275rfs`) never reduces to
  `identify`. Both base forms are themselves confirmed headwords in
  `/usr/share/dict/words` on this machine. Not a compound-hyphen ambiguity
  like the first two shapes: the rejoined word is exactly correct English
  and the check's own stemmer is what is too narrow to accept it.

No instance read across any of the three shapes produced a result unrelated
to this known ambiguity (no transposed, truncated or otherwise corrupted
word) — every flagged instance is a gap in the 234,456-word checking list or
its narrow stemmer, a wordlist blind spot, not damage the rejoin rule did to
the text. That makes 1.76% an upper bound on how many rejoins get *flagged*
by this check, not a defect rate on the rejoin rule itself. The rate is a
new, previously unstated number for the residual this port's docstring
already acknowledged qualitatively; it does not change the module's
documented policy of declining to rejoin at all on a document without
confirmed GPO layout, which remains the stronger, unconditional protection
against the same ambiguity in the far more common non-numbered case.

## Decision

See ["GPO PDF text normalization runs after extraction, gated by
evidence"](decisions.md#gpo-pdf-text-normalization-runs-after-extraction-gated-by-evidence)
in `docs/decisions.md`.

`sources/agency_reports/report_blocks.py`'s `parse_agency_blocks` takes
either a flat string or a `Sequence[PageResult]` directly, not this module's
`tuple[str, ...]` output. `extraction/body_text.py` now does that wiring for
a fetched body: it runs `DocumentExtractor` and `normalize_gpo_pages` for a
`pdf` rendition and hands back `BodyText.text`, already joined page by page
with the same `"\n"` `parse_agency_blocks`'s own `_flatten` uses, so a caller
passes `body_text(result).text` and no longer decides for itself whether to
normalize first. What it does not restore is page attribution: `PageResult` is
not this module's to rebuild after normalization, so `AgencyBlock.page_span`
is `None` on that path. Restoring it — and doing the same for any future
bill-PDF section parser — is for the maintainer landing the caller.

This document and its rule table are for that maintainer to move into
wherever the extraction pipeline's own documentation index lives
(`docs/architecture.md` and its extraction pipeline listing were outside
this port's stated scope).
