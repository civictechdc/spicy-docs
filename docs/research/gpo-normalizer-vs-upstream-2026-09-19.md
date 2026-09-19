# Measured: should `gpo_normalize.py` give way to DeltaTrack's PDF text pipeline?

Status: measured 2026-09-19 on the four fixtured GPO PDFs and one Congressional Record issue; read-only. Verdict: keep `extraction/gpo_normalize.py`; the pypdf path spicy-regs uses never detects the GPO layout, and upstream's pypdfium2 pipeline matches ours on gutter-numbered bills but merges hyphens without a gate.

**Status:** measured 2026-09-19, read-only. Nothing modified in `spicy-docs`, the
`DeltaTrack` clone, or `spicy-regs`. 7 live GovInfo requests total (4 keyless
GETs for the fixtured PDFs, 1 keyed `GovInfoBodyAcquirer.acquire()` call — 3
requests: summary, MODS, body — for one Congressional Record issue), all
through the repo's own bounded readers. All processing run via
`uv run --frozen ...` inside `spicy-docs`'s venv (which has `deltatrack`
installed alongside `pymupdf`, `pypdf`, `pypdfium2`) and cross-checked for the
one new upstream-gap claim via `uv run` inside the DeltaTrack clone itself.
Scripts and captured PDF bytes stayed in the scratchpad
(`gpo_measure/{fetch_gpo_pdfs.py,fetch_crec.py,run_pipelines.py,analyze.py,
time_pipelines.py,pdfs/,out/}`); the API key was read once via
`read_api_key(Path(".env"), "API_GOV")` and passed only as
`GovInfoBodyAcquirer`'s `api_key` argument — never printed, logged, or
written to any file.

## Corpus

| Document | Congress print | Pages | PDF bytes | sha256 matches README/live |
| --- | --- | ---: | ---: | --- |
| `BILLS-119hr4727ih` | Introduced (IH) | 1 | 223,439 | yes |
| `BILLS-119sconres1enr` | Enrolled (ENR) | 1 | 196,785 | yes |
| `CRPT-119hrpt105` | Committee report | 3 | 199,803 | yes |
| `BILLS-119hr1009rfs` | Referred in Senate (RFS) | 2 | 206,513 | yes |
| `CREC-2026-09-18` | Congressional Record, daily (Friday pro-forma) | 3 | 498,741 | n/a (not in README; sha256 `18520ed6…5677c5` recorded, live only) |

The four fixtured PDFs were fetched the same way
`tests/extraction/test_gpo_normalize.py`'s own integration test does
(`package_body_locator(pkg, "pdf")` + a plain `httpx.Client` GET) and matched
the README's recorded byte size and sha256 exactly — same bytes the fixtures
were captured from. `CREC-2026-09-18` was located via
`GovInfoBodyAcquirer.acquire("CREC-2026-09-18", prefer=("pdf",))`, which
confirmed the MODS states `offered=('pdf',)` alone, consistent with
`docs/research/pdf-only-corpus-2026-09-19.md`'s finding that CREC package
bodies are PDF-only.

## Method

Three pipelines run over each document's raw PDF bytes:

- **A (ours):** `DocumentExtractor(NativeText()).extract(bytes,
  media_type="application/pdf")` → PyMuPDF page text → `normalize_gpo_pages`.
- **B (spicy-regs' shape):** `spicy_docs.extraction.pypdf.PypdfReader`
  page text → the *same* `normalize_gpo_pages` (spicy-docs's rules, fed
  pypdf's layout, as spicy-regs actually does today).
- **C (upstream):** `deltatrack.parsers.pdf_text.extract_clean_pages(path)`
  (pypdfium2), using each returned `Page.text` — chrome already stripped and
  hyphens already rejoined per page inside that one call; there is no
  separate normalization step to add.

All "left in text" counts below are **independent, uniformly-applied
regexes run against each pipeline's own final output**, not each library's
self-reported counts — self-reporting would make pipeline A's own claims
unfalsifiable. Word count is whitespace-token count on the same final text.
Difflib ratios use `difflib.SequenceMatcher.ratio()` on whitespace-canonicalized
text (so page-join formatting differences don't dominate the score). Wall
time is a 7-repeat median after one warmup call per pipeline per document
(first-call backend-init time excluded, since that is a one-time process cost
not a per-document one).

## Results

### Residual artifacts (independent regex counts on final text)

"Glued suffix" = a 1-2 digit margin number that survives attached to the end
of a content line, either directly (`Representa-1`, a mid-word wrap with the
digit spliced into the break) or space-separated (`assembled, 2`) — the shape
BillTrax's original `pdf-parse`-derived regex looked for and this port's
PyMuPDF-adjacency detector cannot see. Not every glued-suffix match is a GPO
artifact — genuine trailing numbers in prose ("CHAPTER 8", "record vote No.
68", "September 21") match the same shape and are called out below.

| Document | Pipeline | gutter #s left | VerDate/job-code/footer left | bare page-# lines left | hyphen wraps left (line-break form) | glued-suffix count | word count |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BILLS-119hr4727ih | A | 0 | 0/0/0 | 0 | 0 | 0 | 107 |
| | B | 0 | 0/0/0 | 0 | 0 | **6** (`-1,2,3,-4,5,6` — real margin numbers 1-6, all six) | 113 |
| | C | 0 | 0/0/0 | 0 | 0 | 0 | 107 |
| BILLS-119sconres1enr | A | 0 | 0/0/0 | 0 | 2 | 1 (content: "…concur- 1" — not a real gutter number, no GPO layout on this doc) | 197 |
| | B | 0 | 0/0/0 | 0 | 2 | 0 | 197 |
| | C | 0 | 0/0/0 | 0 | 0 | 0 | 195 (see false rejoin below) |
| CRPT-119hrpt105 | A | 0 | 0/0/0 | 0 | 16 | 3 (all content: "CHAPTER 8", vote "No. 68"/"No. 69") | 876 |
| | B | 0 | 0/0/0 | 0 | 16 | 3 (same content) | 883 |
| | C | 0 | 0/0/0 | 0 | 0 | 3 (same content) | 858 (see false rejoins below) |
| BILLS-119hr1009rfs | A | 0 | 0/0/0 | 0 | 0 | 0 | 168 |
| | B | 0 | 0/0/0 | 0 | 0 | **12** (`-1,2,1,2,3,4,5,-6,7,8,9,10` — real margin numbers on both pages, all twelve) | 180 |
| | C | 0 | 0/0/0 | 0 | 0 | 0 | 168 |
| CREC-2026-09-18 | A | 0 | 0/0/0 | 0 | 6 | 3 (content: times/dates "…and 25 seconds", "September 22", "September 21") | 744 |
| | B | 0 | 0/0/0 | 0 | 6 | 3 (same content) | 742 |
| | C | 0 | 0/0/0 | 0 | 0 | 3 (same content) | 727 |

VerDate/job-code/running-footer lines are 0 left everywhere — all three
pipelines correctly strip those on every document (B's footer detection
survives because `_VERDATE_RE`/`_DSK_USER_RE` only need to match at the start
of a line, which pypdf still gets right even though it mangles the gutter
numbers).

**Real gutter-number leakage is B-only**, and total on the two genuinely
GPO-numbered fixtures: 6 of 6 margin numbers leak into visible prose on
`BILLS-119hr4727ih`, 12 of 12 on `BILLS-119hr1009rfs`. Two of those (`-1`,
`-4` on the IH bill; `-1`, `-6` on the RFS bill) are spliced directly into a
mid-word hyphen break (`Representa-1` / `tives…`, `relat-4` / `ing…`),
which is worse than an ordinary unrejoined wrap: the reader sees a digit
embedded in the middle of a broken word.

### `is_gpo_layout` / line-numbering verdict

| Document | A (`line_numbers`) | B (`line_numbers`) | C (numbered / total lines) |
| --- | --- | --- | --- |
| BILLS-119hr4727ih | **True** | False | 4/17 |
| BILLS-119sconres1enr | False | False | 0/27 |
| CRPT-119hrpt105 | False | False | 0/82 |
| BILLS-119hr1009rfs | **True** | False | 10/25 |
| CREC-2026-09-18 | False | False | 1/104 |

**B never detects GPO layout, on any document, including the two that
genuinely are gutter-numbered.** pypdf glues the margin number onto the
content line with no intervening physical line break (`Representa-1`), so
`normalize_gpo_pages`'s adjacency detector — "a content line immediately
followed by a bare 1-2 digit line" — never fires. That single miss cascades:
`hyphen_rejoin_count` is 0 for B on every document (rejoin is gated on
`gpo_layout`), and the `gutter_layout` half of the per-page bare-digit
evidence gate is dead code for B (only `page_footer` evidence can ever apply).
This is not an occasional degradation, it is complete: on a pypdf-fed
document, three of `gpo_normalize`'s core rules (layout detection, hyphen
rejoin, gutter-evidenced digit stripping) are structurally unreachable.

### False rejoins (damaged compounds)

| Document | A | B | C |
| --- | --- | --- | --- |
| BILLS-119hr4727ih | 0 (2 correct rejoins fire) | 0 (declines all; layout undetected) | 0 (2 correct rejoins, matching A exactly) |
| BILLS-119sconres1enr | 0 (declines both candidates; no GPO layout confirmed) | 0 (same) | **1** — `President-\nelect` → **`Presidentelect`**, a genuine compound wrapped at its own hyphen, hyphen silently deleted |
| CRPT-119hrpt105 | 0 (declines all 16; no GPO layout confirmed) | 0 (same) | **2** — `DEPART-\nMENT` → **`DEPART-MENT`**, `RE-\nPORTED` → **`RE-PORTED`** (bogus hyphen spliced in with **no line break at all**, not even an obviously-broken two-line artifact) |
| BILLS-119hr1009rfs | 0 | 0 | 0 (no candidates) |
| CREC-2026-09-18 | 0 (declines all 6; no GPO layout confirmed) | 0 (same) | 0 — all 6 confirmed correct (`perform`, `pro tempore` ×2, `pro forma session`, `September 21`, `Southern District`) |

`Presidentelect` reproduces the specific case spicy-docs already validated
and left open as **claim B4** in
`docs/research/deltatrack-upstream-issues-2026-09-19.md` (filed nowhere yet,
ranked #1 by that document's own priority order). My reproduction went
through `extract_clean_pages` directly — the real production entry point,
matching that document's "upstream's real pipeline" row exactly — and
confirms it still reproduces at the pinned commit.

`DEPART-MENT` / `RE-PORTED` is a **different, previously undocumented
mechanism**, confirmed with the DeltaTrack clone's own `uv run` (not just the
installed copy):

```
$ uv run python -c "
from deltatrack.parsers.pdf_text import normalize_raw
print(normalize_raw('OF THE DEPART￾MENT OF THE TREASURY RELATING TO\n'))
"
OF THE DEPART-MENT OF THE TREASURY RELATING TO
```
(clone at pinned `c636448`, `src/deltatrack/parsers/pdf_text.py`)

`normalize_raw` (`pdf_text.py:128-146`) has three branches for the
U+FFFE soft-hyphen glyph pypdfium2 emits at a print-line wrap: reconstruct
`-\n<margin-number> ` when a margin number follows (`:141`); join directly
with no hyphen when no margin number follows and the continuation is
lowercase (`:143`, the module's own docstring: "joined into one word, since
there is no `-\n` boundary for the later rejoin pass to act on"); everything
else falls through to `text.replace("￾", "-")` (`:144`), a bare glyph→hyphen
swap with **no** newline reinserted. That third branch is what fires for an
unnumbered, uppercase-continued wrap (a heading or title, which is exactly
where unnumbered text lives — enrolled bills and committee-report headings
carry no margin numbers at all). The result reads as a plausible hyphenated
word and carries no signal that anything went wrong — worse in one respect
than the already-tracked #650 (uppercase continuations left visibly split
across two lines): a two-line break is an obvious artifact; a silently wrong
mid-line hyphen is not.

### Difflib ratio between pipeline pairs (whitespace-canonicalized text)

| Document | A/B | A/C | B/C |
| --- | ---: | ---: | ---: |
| BILLS-119hr4727ih | 0.9897 | **1.0000** | 0.9897 |
| BILLS-119sconres1enr | 1.0000 | 0.9984 | 0.9984 |
| CRPT-119hrpt105 | 0.9995 | 0.9965 | 0.9959 |
| BILLS-119hr1009rfs | 0.9871 | 0.9913 | 0.9728 |
| CREC-2026-09-18 | 0.9968 | 0.9951 | 0.9962 |

A/C is the closest pair on both genuinely GPO-numbered documents (0.9913-1.0);
B/C is the weakest pair on the RFS bill (0.9728), tracking the 12 leaked
gutter digits directly.

### Wall time (median of 7 warm runs; extraction + normalization/cleaning per document, network excluded)

| Document | A | B | C |
| --- | ---: | ---: | ---: |
| BILLS-119hr4727ih | 4.74 ms | 4.06 ms | 3.31 ms |
| BILLS-119sconres1enr | 5.17 ms | 2.84 ms | 3.62 ms |
| CRPT-119hrpt105 | 19.82 ms | 6.54 ms | 12.57 ms |
| BILLS-119hr1009rfs | 6.57 ms | 4.38 ms | 4.01 ms |
| CREC-2026-09-18 | 20.71 ms | 30.07 ms | 15.62 ms |

All three pipelines process these documents (200 KB-500 KB PDFs, 1-3 pages)
in single-digit-to-tens of milliseconds. C is fastest or competitive on 4 of
5 documents; none of the three shows superlinear behavior worth flagging —
these are page-count-scale costs, not corpus-scale ones. Not a deciding
factor either way.

## Judgment

### Does C do the job at least as well as A on GPO documents?

**Yes, on the documents that are actually GPO gutter-numbered** — the two
that matter most, since that is the layout the whole normalizer exists for.
Identical hyphen-rejoin behavior (2/2 correct on both), highest-in-corpus
difflib agreement with A (0.9913, 1.0000), equal or matching word counts.
On the three *non*-numbered documents (ENR, committee report, CREC), C is
not strictly as safe: it attempts hyphen cleanup unconditionally (no
gpo-layout gate at all, unlike A's deliberate all-or-nothing policy), and on
this five-document corpus that produced 3 confirmed false rejoins (1 lost
compound hyphen, 2 bogus inserted hyphens) against zero for A. A's
conservatism trades recall for precision here: A leaves 16 CRPT hyphen-wraps
visibly broken across two lines (correctly declining to guess) rather than
getting 14 of 16 right and 2 silently wrong.

### Does B (pypdf) degrade A's rules, and would C remove that problem?

**Yes and yes.** B is not an occasional degradation — `is_gpo_layout` never
returns True for B on any document in this corpus, including the two that
truly are gutter-numbered, because pypdf glues the margin number onto the
content line (`Representa-1`) rather than emitting it as its own line the
way PyMuPDF does. That single layout miss makes three of the normalizer's
rules unreachable for every pypdf-fed document: layout detection, hyphen
rejoin (0/0 and 0/0 rejoins on the two numbered fixtures, vs A and C's 2/2),
and the `gutter_layout` half of the bare-digit evidence gate. The real
margin numbers (6 of 6, then 12 of 12) leak straight into the visible text
instead, two of them spliced into the middle of a broken word.
Since `deltatrack` already ships `pypdfium2` as its own extraction backend in
both repos (confirmed installed: `pypdfium2==5.13.0` in spicy-docs's venv,
same package DeltaTrack's `pdf_text.py` imports), routing spicy-regs's PDF
branch through `extract_clean_pages` — pypdfium2 end to end — removes this
specific failure mode entirely: no gluing artifact exists in pypdfium2's
output to begin with, and C's own results above show it handles the two
genuinely-numbered fixtures identically to A.

### What A does that C does not

1. **The per-page cleanup record the hosted `cleanup_*` columns need.**
   `src/spicy_docs/schemas/bill_version_tables.py:191-196` maps
   `GpoCleanupRecord` directly onto six `bill_versions` columns:
   `cleanup_line_numbers`, `cleanup_gpo_footers`,
   `cleanup_spacing_normalized`, `cleanup_small_caps_merges`,
   `cleanup_hyphen_rejoins`, and `cleanup_json` (the per-page breakdown:
   page number, verdate/dsk/running-footer/bullet/bare-page-number line
   counts, `bare_page_number_evidence`, content-line count, small-caps and
   hyphen-rejoin counts — `_page_cleanup`, same file, `:132-146`).
   `extract_clean_pages` returns `Page`/`Line` objects with cleaned text and
   nothing else — no counts of what was stripped, no per-page evidence tag,
   no boolean layout verdict exposed as data. A thin adapter would have to
   independently: (a) recompute a `line_numbers` verdict (`is_gpo_layout`'s
   own ratio + floor + consecutive-run logic, or an equivalent derived from
   `Line.line_number` density); (b) count VerDate/job-code/running-footer/
   bare-page-number lines by re-matching the same patterns
   `strip_page_chrome` already applied but discarded the counts of; (c)
   reconstruct a `bare_page_number_evidence` per-page tag, which has **no**
   DeltaTrack analogue at all (see point 3); (d) count hyphen-rejoin events,
   derivable from `Page.merge_ranges` spans `> 1` (confirmed workable — used
   for this measurement's own `merge_events` counts) but not returned as a
   count by the library; (e) supply `small_caps_merges` from scratch — see
   point 4.
2. **Page boundaries — not actually a gap.** `extract_clean_pages` already
   returns one `Page` per page, and `Page.text` (unlike the separate
   `page_range_text`, which explicitly reruns `rejoin_soft_hyphens` across a
   page seam for the full-bill display) does no cross-page hyphen rejoin.
   Used the way this measurement uses it, C already matches A's "never
   rejoin across a page break" policy.
3. **The evidence-gated bare-digit rule.** Confirmed on real pages in this
   corpus: `CRPT-119hrpt105` pages 2 and 3 each strip exactly one bare-digit
   line under `bare_page_number_evidence="page_footer"` even though the
   *document*-level verdict is `line_numbers=False` — a page-by-page decision
   `_gate_bare_digits` makes deliberately (module docstring: "a standalone
   1-4 digit line... outside a GPO document... could be a year or a footnote
   number"). DeltaTrack's `_PAGE_HEADER_NUMBER` strip
   (`pdf_text.py:56`, applied at `:162` inside `strip_page_chrome`) runs
   **unconditionally** on every page's leading digit line, with no
   evidence check of any kind. That is a defensible choice for DeltaTrack's
   own scope — it only ever runs on GPO bill printings for structural
   diffing (`README.md`: "Downloads U.S. bill text from official government
   data (GPO govinfo) and compares versions structurally") — but
   `gpo_normalize.py`'s own docstring states spicy-docs's normalizer is
   meant to run safely on *any* PDF-derived text, including the
   non-GPO-bill PDF families this repo's own corpus survey counts as
   PDF-only or PDF-primary (GAO reports, CRS files, Supreme Court opinions,
   CDIR, CHRG, CDOC). Reusing `strip_page_chrome` unconditionally over that
   broader corpus would risk silently deleting a real leading number on a
   non-GPO page.
4. **Small-caps merge.** `_merge_small_caps` has no DeltaTrack equivalent
   (confirmed: no `small.cap`/`SINGLE_CAP` pattern anywhere in
   `deltatrack/parsers/`). It fires on real data in this corpus — 10 times on
   `CREC-2026-09-18` (the masthead/seal "E PLURIBUS UNUM" banner text, each
   letter rendered by PyMuPDF as its own physical line) — and C has nothing
   that reconstructs it.
5. **Licensing.** Confirmed from installed package metadata, not secondhand:
   `pymupdf==1.28.2` reports `License: Dual Licensed - GNU AFFERO GPL 3.0 or
   Artifex Commercial License`; `pypdfium2==5.13.0` reports `BSD-3-Clause,
   Apache-2.0`. For a hosted, network-facing service, AGPL is the one with
   teeth (source-disclosure obligations on network use, absent a commercial
   Artifex license). This is a real point in pypdfium2's favor, but it is
   **not resolved by deleting `gpo_normalize.py` alone**: PyMuPDF
   (`spicy-docs[pdf]`) is the *extraction* backend for
   `DocumentExtractor(NativeText())`, used throughout
   `extraction/pages.py`, `extraction/body_text.py`, and `extraction/api.py`
   — not just by the GPO normalizer. Moving the GPO PDF path onto
   `extract_clean_pages` removes PyMuPDF from *that* path (extraction and
   normalization both, since DeltaTrack does its own pypdfium2 extraction),
   but spicy-docs's broader AGPL exposure only goes away if the default PDF
   extraction backend for every PDF family moves too — a larger question
   than this task's scope.

## Recommendation

**Keep `gpo_normalize.py`, do not delete it — but narrow where it is the
last word.** The measurement does not support a clean "adopt upstream
wholesale" verdict:

- On the two documents the normalizer exists for (real GPO gutter numbering),
  C matches A exactly in rejoin correctness and near-exactly in output
  (0.99-1.00 difflib agreement), at comparable or better speed, and removes
  B's demonstrated, complete rule failure if spicy-regs's PDF branch moves
  onto it too. That part of the case for adopting upstream is solid.
- On non-numbered layouts, C's own ungated hyphen handling introduced 3
  confirmed false rejoins on this 5-document corpus that A's more
  conservative, evidence-gated policy produces zero of. One of these
  (`Presidentelect`) is already known and tracked (claim B4, open, unfiled)
  in `docs/research/deltatrack-upstream-issues-2026-09-19.md`. The other
  (`DEPART-MENT`/`RE-PORTED`) is new — see below.
- C returns no cleanup-count record at all, and the hosted schema's six
  `cleanup_*` columns need one.

**A thin adapter is the right shape, not a full replacement,** and it must
add:

1. Extraction + chrome-strip + hyphen-rejoin from `extract_clean_pages`
   (pypdfium2), replacing PyMuPDF for this path.
2. A `line_numbers` verdict computed independently of DeltaTrack's own
   (DeltaTrack's diff-time guard, `compare/pdf.py`, is tuned for its own
   60-document corpus and a different purpose — declining to diff, not
   deciding whether to strip a digit); `is_gpo_layout`'s own ratio/floor/
   run-length logic can likely be ported to run over `Line.line_number`
   density instead of re-deriving PyMuPDF's own adjacency signal.
3. Per-page evidence-gated bare-digit stripping — DeltaTrack's own
   `_PAGE_HEADER_NUMBER` strip must **not** be reused unconditionally if this
   normalizer keeps running over non-GPO-bill PDF families.
4. A small-caps merge pass — DeltaTrack has none.
5. Counts of everything stripped, per page, in `GpoPageCleanup`'s exact
   shape, since `bill_version_tables.py` depends on that shape today.
6. A layout gate on hyphen rejoin (or an upstream fix to B4) before trusting
   C's rejoin decisions on a non-numbered page — until then, the adapter
   should keep A's "decline unless the document is confirmed GPO-numbered"
   policy for the rejoin step specifically, even while using pypdfium2 for
   extraction and chrome-stripping.

If upstream fixes B4 (and the new gap below) and a maintainer confirms the
evidence-gating and cleanup-record concerns are addressed on the adapter side
rather than upstream, revisit full deletion then. Until that adapter exists
and is measured the same way, deleting `gpo_normalize.py` now would trade a
working, evidence-gated, fully-tested normalizer for one with a smaller but
real false-rejoin rate and a missing telemetry contract.

## Upstream gaps to add to `docs/research/deltatrack-upstream-issues-2026-09-19.md`

- **B4 is not new** — already validated, already ranked #1 to file, still
  unfiled. This measurement's independent reproduction (through
  `extract_clean_pages`, on the same fixture, at the same pin) is additional
  corroboration worth noting in that document if it is revisited, but adds
  no new claim.
- **New candidate — call it B5: the unnumbered-uppercase soft-hyphen
  catch-all silently inserts a hyphen with no line break.**
  `normalize_raw` (`pdf_text.py:128-146`) has three branches for the U+FFFE
  soft-hyphen glyph: reconstruct `-\n<number> ` when a margin number follows
  (`:141`); join directly (no hyphen) when unnumbered and the continuation is
  lowercase (`:143`, documented behavior); everything else — unnumbered,
  uppercase continuation — falls to `text.replace("￾", "-")` (`:144`), which
  swaps the glyph for a literal hyphen with **no** newline reinserted.
  Reproduced with the clone's own `uv run` on a synthetic minimal case
  (`normalize_raw('OF THE DEPART￾MENT OF THE TREASURY RELATING TO\n')` →
  `'OF THE DEPART-MENT OF THE TREASURY RELATING TO\n'`) and confirmed on real
  GovInfo text: `CRPT-119hrpt105`'s own PDF contains `DEPART￾MENT` and
  `RE￾PORTED` in its title heading (verified via a direct
  `pypdfium2.PdfDocument` read of the captured PDF), both unnumbered
  (heading text carries no margin number) and both uppercase-continued, and
  both come out of `extract_clean_pages` as `DEPART-MENT` and `RE-PORTED` —
  a single run with a bogus embedded hyphen, no line break, no signal
  anything went wrong. This is distinct from the already-tracked #650 (same
  uppercase-continuation ambiguity, but in `_merge_print_lines`, on
  already-numbered body text, producing a visibly-broken two-line miss —
  `INTEL-`/`LIGENCE` stays split) and distinct from B4 (lowercase
  continuation, numbered or unnumbered, wrongly *joined*). B5 is: unnumbered
  + uppercase → wrongly *hyphenated-in-place*, silently, with the least
  visible signature of the three (no split, no line break, reads as a
  plausible word). Same root cause as B4 and #650 per that document's own
  analysis of #650: "the U+FFFE soft-hyphen glyph... is the signal that
  distinguishes them, and it is discarded before either rule runs" — true
  here too, one branch earlier, before `_merge_print_lines` is even reached.

## Files

- Report: this file.
- Scripts (scratchpad only): `gpo_measure/fetch_gpo_pdfs.py`,
  `gpo_measure/fetch_crec.py`, `gpo_measure/run_pipelines.py`,
  `gpo_measure/analyze.py`, `gpo_measure/time_pipelines.py`.
- Captured bytes (scratchpad only, not committed anywhere):
  `gpo_measure/pdfs/*.pdf`.
- Raw per-document results: `gpo_measure/out/*.json`,
  `gpo_measure/out/_metrics_report.json`, `gpo_measure/out/_timing_report.json`.
