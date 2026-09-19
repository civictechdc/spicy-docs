# Validated: gaps spicy-docs proposes to raise in `civictechdc/DeltaTrack`

**Status:** validated 2026-09-19 against `c636448` (upstream's default branch
`develop`, which this pin is the tip of — `main` is a stale promotion target,
465 commits behind; see below).
**Filed:** nothing — read-only validation, no PR opened, no repository modified.

- **Upstream pin:** `c636448` (2026-09-13)
- **Validated:** 2026-09-19
- **Sources:** `docs/sources/congress-bill-tree.md` §"To raise upstream";
  `docs/extraction-gpo.md` §"Compared against upstream DeltaTrack"
- **Clone:** a scratch clone of `civictechdc/DeltaTrack`, read-only

## Upstream has not moved since the pin — but not for the reason the brief assumed

The brief asked to diff `c636448..origin/main`. That command fails, and the failure is
informative rather than incidental:

| Ref | Commit | Date | Relationship to pin |
| --- | --- | --- | --- |
| `origin/HEAD` → `origin/develop` | `c636448` | 2026-09-13 | **identical to the pin** |
| `origin/main` | `3fc85ca` | 2026-08-11 | **465 commits behind**; diverged (a merge of PR #603) |

The default branch is `develop`, not `main`. `main` is a stale promotion target — upstream's
own #555 calls it out ("Epic: the develop to main promotion is unowned and unrehearsed, and
the published site is 862 commits behind"), with #556, #545 and #400 as its follow-ups.

**Consequence for this validation:** every claim was validated once, at `c636448`, because
that commit *is* `origin/develop`'s tip. Validating "at origin/main" as well would measure a
tree 465 commits older, where each of these gaps is present at least as strongly — it would
manufacture agreement rather than test anything, so it was not done. The one new ref the
fetch pulled, tag `pdf-bakeoff-prevalidation` (`3a67b03`, 2026-08-06), is an **ancestor** of
the pin, not movement past it.

## Method

- Code read at `c636448` in the clone; every `file:line` below re-derived, not copied from
  spicy-docs.
- Behavioural claims re-run through **upstream's own runner** (`uv run` inside the clone), so
  the measurement uses upstream's pinned dependency set rather than anything on `PATH`.
- Issues matched against `gh issue list --repo civictechdc/DeltaTrack --limit 200 --state all`
  (200 returned: 88 open, numbers 722→284), plus targeted `gh issue view` on #650, #515, #535,
  #679, #356, #676, #698, #261, #141, #140, #368.
- Probe scripts left in the scratchpad: `hyphen_probe.py`, `hyphen_probe2.py`,
  `collision_probe.py`, `asym_probe.py`, `asym_probe2.py`, `dsk_probe.py`.

### Where the stated measurements landed

| Measurement spicy-docs cites | Status |
| --- | --- |
| `GREEDY_PAIR_GROUP_CAP = 200`, `section-diff.ts:26` | **Verified verbatim** at that line |
| `SECTION_COUNT_THRESHOLD = 10`, `section-diff.ts:40` | **Verified verbatim** at that line |
| `canonicalToken`, `section-diff.ts:104` | **Verified verbatim** at that line |
| `BODY_CAP = 30_000`, `diff_service.py:31` | **Verified verbatim** at that line |
| 120-second SIGKILL, 118th NDAA, 988 vs 1 | **Provenance verified** (`section-diff.ts:28-39`, "Task #9 (NDAA 118-hr-2670)") — but it does **not** reproduce against upstream at the pin (see claim 2) |
| 0.46 s / 1.88 s repetitive-prose alignment | **Verified present** in `spicy_docs/interpretation/section_diff.py:50-53` |
| "President-elect" fixture case | **Verified present** in `tests/fixtures/gpo_pdf_text/BILLS-119sconres1enr.json`, page 0 lines 14-15 |

---

# Part A — `congress-bill-tree.md` §"To raise upstream"

## A1. Collision-group cap — **real gap**

**Claim as stated.** BillTrax's `GREEDY_PAIR_GROUP_CAP = 200` (`section-diff.ts:26`) bounds the
O(p×q) similarity matrix inside one match-path group, falling back to body-equality pairing
above it. Upstream's `_match_collision_group` (`diff_bill.py:803`) has no cap; its retrieval
gates each candidate with `real_quick_ratio`/`quick_ratio`, bounding cost per pair but not the
number of pairs.

**Upstream at the pin.** `src/deltatrack/diff_bill.py:803` (`_match_collision_group`), dispatched
at `:958`. No cap constant exists anywhere in the matching path — a grep for
`CAP|_LIMIT|MAX_|SECTION_COUNT` across `diff_bill.py` and `matching.py` returns only an
unrelated prose comment at `diff_bill.py:52`. At `origin/main`: same absence, 465 commits older.

**Measured** (upstream's runner, `collision_probe.py`; N sections per side, all sharing one
`match_path`, via the public `match_nodes`):

| N/side | pairs (N²) | seconds | µs per pair |
| ---: | ---: | ---: | ---: |
| 25 | 625 | 0.062 | 98.7 |
| 50 | 2,500 | 0.232 | 92.7 |
| 100 | 10,000 | 0.946 | 94.6 |
| 200 | 40,000 | 3.845 | 96.1 |
| 300 | 90,000 | 8.736 | 97.1 |

Cost per pair is flat at ~95 µs across a 12× range of group sizes; total time tracks N²
(each doubling costs ~4×). The per-pair gate works exactly as spicy-docs says, and exactly as
it says, it does not bound the *count*. One 300-section collision group costs 8.7 s.

**Verdict: real gap (absent upstream).** The claim is accurate as written.

**Existing issue:** none covering group-size capping. #356 (open) is the adjacent but distinct
round-2 move-detection cost; #672/#673 concern move-cutoff boundaries, not group size.

**Suggested title:** `One match_path group is matched without bound, so a bill that reuses a section number pays N² similarity comparisons`

**Body:**
> `_match_collision_group` (`diff_bill.py:803`, dispatched at `:958`) resolves every observation
> sharing one `match_path` against every observation on the other side, and while retrieval gates
> each candidate with `real_quick_ratio`/`quick_ratio`, nothing bounds how many candidates are
> formed. Timed on this checkout at `c636448` through `match_nodes`, a single collision group
> costs a flat ~95 µs per pair across group sizes 25 through 300 — 0.062 s at 25 per side,
> 3.845 s at 200, and 8.736 s at 300 — so the stage is cleanly quadratic in group size with no
> ceiling. BillTrax, diffing the same bills, bounds the equivalent matrix at
> `GREEDY_PAIR_GROUP_CAP = 200` (`section-diff.ts:26`) and falls back to body-equality pairing
> above it, trading cross-rename detection for a linear path, which is the shape of decision this
> engine has not yet made.

---

## A2. Asymmetric-pair guard — **already addressed** (different mechanism)

**Claim as stated.** `SECTION_COUNT_THRESHOLD = 10` (`section-diff.ts:40`) came from a measured
120-second SIGKILL on the 118th NDAA: an enrolled bill with 988 sections against a public law
with 1 ran the whole removed×added matrix against a single huge blob. Upstream's round 2
(`diff_bill.py:1468`) runs unconditionally.

**Upstream at the pin.** `retrieve_move_candidates` at `src/deltatrack/diff_bill.py:1468` does run
unconditionally — the literal half of the claim is correct. But it delegates scoring to
`similarity.move_candidates` (`similarity.py:97`), which gates every pair on `real_quick_ratio`
at `similarity.py:143`.

**Measured** (`asym_probe.py`, `asym_probe2.py`) — the exact shape cited, 988 sections against
one concatenated blob:

| old secs | new secs | blob words | `diff_bills` seconds |
| ---: | ---: | ---: | ---: |
| 50 | 1 | 8,600 | 0.00 |
| 988 | 1 | 169,936 | **0.03** |

Instrumenting the gate directly: for a 124-word section against a 122,512-word blob,
`real_quick_ratio` = **0.00202** against `MOVE_THRESHOLD` = 0.6, so every pair is pruned before
`quick_ratio` or `ratio` runs. `move_candidates` returns **0 candidates in 0.014 s**.
`real_quick_ratio` is a length-ratio bound, so the more extreme the asymmetry, the *harder* it
prunes — which is why the degenerate case BillTrax guards against is upstream's cheapest one.

That gate predates the pin substantially (present by `4b23e65`, 2026-07-09, and carried through
`16039ed` #398 and `1d5836a` #492). BillTrax's comment at `section-diff.ts:28-39` blames "the
Python DeltaTrack engine" for the 120 s timeout, but that attribution cannot be reproduced
against this engine at this pin.

**Verdict: already addressed**, by a length-ratio bound rather than a section-count threshold —
and the bound is the better instrument, since it keys on the actual cost driver instead of a
proxy. **The claim is also misdescribed**: it says upstream "runs the whole removed×added matrix
against a single huge blob", and upstream demonstrably does not.

**Residual, and it is real but different.** The population the length gate cannot prune is
many×many at similar lengths:

| shape | pairs | seconds |
| --- | ---: | ---: |
| 200 × 200 | 40,000 | 3.77 |
| 400 × 400 | 160,000 | 15.22 |
| 800 × 800 | 640,000 | 60.45 |

That is **already #356** (open): "Move detection is the dominant cost of comparing a large bill,
at over five seconds on one corpus bill", measured there at 1192 × 1700 = 5.65 s of 5.84 s total.

**Existing issue:** #356 (open) covers the residual. **Not worth filing.**

---

## A3. Body-size cap on inline word segments (`BODY_CAP`) — **not applicable upstream**

**Claim as stated.** `BODY_CAP = 30_000` (`diff_service.py:31`) caps inline word segments;
"upstream has no word-segment rendering at all, so this has no home there yet — worth raising
with the feature rather than alone."

**Upstream at the pin.** Confirmed: a case-insensitive grep for `word_segment|word-segment|
wordSegment` across all of `src/` returns **nothing**. spicy-docs's own framing is correct.

**Verdict: correctly self-described as not-yet-applicable.** There is no upstream code for the
cap to attach to, so an issue would describe a cap on a feature that does not exist.

**Existing issue:** none, and none needed. **Not worth filing** until/unless the feature is
proposed upstream.

---

## A4. Hyphen-tolerant matching tokens — **real gap**

**Claim as stated.** `canonicalToken` (`section-diff.ts:104`) folds `cyber-security` and
`cybersecurity` to one key, which matters when one side of a comparison came from a PDF.
Upstream's `similarity.py:73` compares raw `split()` tokens; its only hyphen handling is the
PDF page-break rejoin in `amounts.py:59`, a different problem.

**Upstream at the pin.** `text_similarity` is defined at `similarity.py:73`; the raw comparison
is at **`similarity.py:75`** (`difflib.SequenceMatcher(None, a.split(), b.split()).ratio()`) —
spicy-docs cites the `def` line, one line off from the operative one. No canonicalization of any
kind. The hyphen handling it points at is `PAGE_HYPHEN_RE`, whose comment block starts at
`amounts.py:59` with the regex itself at **`amounts.py:68`** — again the comment line rather than
the code line. Both citations are close enough to find, but neither is the operative line.

**Verdict: real gap (absent upstream)**, with two off-by-a-few line citations worth correcting
before filing.

**Existing issue:** none directly. **#706 (open)** — "The diff summary reports different change
categories for the same bill depending on whether it was compared from XML or PDF" — is the
symptom class this would contribute to, and is the right issue to reference.

**Caveat on evidence.** Neither spicy-docs nor this validation measured how often a hyphen split
actually changes a pairing decision on real bills. The mechanism is certain; the frequency is
unmeasured. File it as a mechanism with an honest "frequency not measured" line, the way #368
does ("**Unverified:** no corpus example demonstrating the misleading rendering was produced").

**Suggested title:** `A word hyphenated in one version and not the other counts as two different words when sections are compared`

**Body:**
> `text_similarity` compares two provisions as raw whitespace tokens
> (`similarity.py:75`, `difflib.SequenceMatcher(None, a.split(), b.split())`), so
> `cyber-security` and `cybersecurity` are unequal tokens and every occurrence pushes the pair's
> ratio down toward the 0.4 correspondence cutoff and away from the 0.6 move cutoff. The engine
> normalizes hyphens elsewhere for a different purpose — `PAGE_HYPHEN_RE` (`amounts.py:68`) closes
> a printer's page-break split — but nothing folds a hyphen that is genuinely present in one
> version and absent in the other, which is the common shape when one side was read from a PDF and
> the other from XML. BillTrax folds both forms to one key before comparing
> (`canonicalToken`, `section-diff.ts:104`, `token.toLowerCase().replace(/-/g, "")`); how often
> this changes a pairing on real bills is not measured here, and #706 is where the
> XML-versus-PDF divergence it would contribute to is already tracked.

---

## A5. The `" "` versus `""` join change (D4) — **real, but not an upstream defect**

**Claim as stated.** Upstream moved section text to a space join; anyone holding `bill_sections`
rows produced by the vendored snapshot has bodies that will not compare equal to freshly parsed
ones. Worth a note upstream that the change is observable in stored output.

**Upstream at the pin.** Confirmed at both cited lines: `bill_tree.py:1136`
(`" ".join(part for part in parts if part).strip()`) and `bill_tree.py:1192`
(`_LIST_MARKER_RE.sub("", " ".join(part for part in parts if part)).strip()`). Both are space
joins. The citations are exact.

**Verdict: accurate, but it describes a consumer-side migration, not an upstream defect.** The
behaviour upstream has is the intended one; the stale rows live in BillTrax's and spicy-docs's
databases. Upstream's **#676** (open, epic) is explicit that "Nothing in this repository should
require BillTrax to exist, name it as an authority, or describe it as the destination for work
that falls outside DeltaTrack's scope" — an issue whose content is "a downstream consumer's
stored rows need a reparse" is the coupling that epic is retiring.

**Existing issue:** #676 (open) makes the case against filing this as stated.

**Not worth filing.** The reparse is spicy-docs's to do. If anything belongs upstream it is a
line in the canonical-diff contract's changelog noting that section body text is space-joined —
worth raising only if upstream publishes a body-text stability guarantee, which it currently
does not.

---

## A6 + A7. Version-from-filename, and a parsed-tree entry point — **real gap** (file as one)

spicy-docs itself says a keyword argument "would close both this and the point above", so these
are validated together and should be filed together.

**Claim as stated.** `normalize_bill` (`bill_tree.py:1470`) derives `BillTree.version` from
`xml_path.stem` after splitting on `_`; a caller holding bytes has to encode the version into a
temporary file name. And the same function parses the file itself, so a caller that must gate the
bytes first parses the document twice.

**Upstream at the pin.**
- `normalize_bill(xml_path: Path) -> BillTree` at `bill_tree.py:1470`; it calls `ET.parse(xml_path)`
  at `:1481`. Signature takes a path and nothing else — confirmed.
- Version derivation at `bill_tree.py:1316-1320`:
  `stem = xml_path.stem` / `parts = stem.split("_", 1)` / `version = parts[1]` when there are two
  parts. Confirmed.
- **Upstream's own byte-oriented caller pays it**, exactly as claimed: `compare/xml.py:84-96`,
  `_build(start_bytes, end_bytes, ...)`, whose docstring reads "Temp files exist only long enough
  for `normalize_bill` to read them", writing `start.xml` and `end.xml` into a
  `tempfile.TemporaryDirectory`.

**A detail stronger than spicy-docs's own framing.** Those temp names — `start.xml`, `end.xml` —
contain no `_`, so `parts` has length 1 and `version` comes back **`""`** on every web upload.
Upstream compensates by threading `start_label`/`end_label` through `_build_from_trees`
(`compare/xml.py:39-60`, "override the XML's embedded version names so the report reflects the
file the caller actually supplied"). The filename-derived version is not merely awkward for
outside callers; it is already dead on upstream's own upload path, and a second parameter exists
to work around it.

**Partly addressed, on the second half only.** `_build_from_trees` (`compare/xml.py:39`) already
accepts parsed `BillTree`s, so the *diff* stage has a tree-level entry point. What has none is
the *parse* stage: `normalize_bill` still insists on a `Path`.

**Verdict: real gap (absent upstream)** for the version keyword; **partly addressed** for the
parsed-tree entry point (tree-level diff exists, tree-level parse does not).

**Existing issue:** none directly. **#698 (open, labelled `blocked`)** — "The XML pipeline reaches
the canonical document through an intermediate dictionary the PDF pipeline does not need" — is
adjacent pipeline-shape work and the natural cross-reference. **#676 (open)** is the epic that
makes "an outside consumer should not need a privileged path" the motivation.

**Suggested title:** `A caller holding bill XML as bytes must write a temp file with a crafted name, and the web upload path already loses the version doing it`

**Body:**
> `normalize_bill` accepts only a `Path` (`bill_tree.py:1470`) and reads the version from that
> path's stem, `xml_path.stem.split("_", 1)[1]` (`bill_tree.py:1316-1320`), so a caller holding
> bytes must materialize a temp file whose *name* encodes the version — which is what this
> repository's own `compare/xml._build` does (`compare/xml.py:84-96`, "Temp files exist only long
> enough for `normalize_bill` to read them"). That workaround already fails silently here: `_build`
> names its files `start.xml` and `end.xml`, neither of which contains `_`, so `version` is `""` on
> every web upload and `_build_from_trees` has to carry `start_label`/`end_label` as separate
> parameters to put the version back (`compare/xml.py:39-60`). A `version` keyword on
> `normalize_bill`, plus an overload taking an already-parsed `ET.Element` root with the path form
> calling it, would let this repository's own upload path drop both the temp directory and the
> label workaround, and would let a consumer that must validate bytes before parsing them stop
> parsing each document twice.

---

## A8. The XML path imports the PDF stack — **real gap**, one sub-claim misdescribed

**Claim as stated.** `bill_tree.py:8` imports from `parsers/pdf_anchors`, which loads
`pypdfium2`. Reading one bill's XML therefore pulls a native PDF library into the process "and
emits its SWIG deprecation warnings". Upstream's `[project.dependencies]` comment says the
engine's dependency list "is what a consumer of the engine actually gets".

**Upstream at the pin.** The import chain is exactly as claimed:

```
bill_tree.py:8    from deltatrack.parsers.pdf_anchors import _RUNIN_QUOTED_LINE, _match_runin_subsection
pdf_anchors.py:19 from deltatrack.parsers.pdf_text import Page, parse_lines, strip_page_chrome
pdf_text.py:28-29 import pypdfium2 as pdfium
                  import pypdfium2.raw as pdfium_raw
```

The `pyproject.toml` quote is verbatim, at **`pyproject.toml:51`**: "This list is what a consumer
of the engine actually gets." The sole runtime dependency is `pypdfium2>=5.12.1`
(`pyproject.toml:52-54`).

**Measured.** `import deltatrack.bill_tree` takes **69 ms** and leaves both `pypdfium2` and
`pypdfium2.raw` in `sys.modules`.

**One sub-claim does not reproduce.** "emits its SWIG deprecation warnings" is **false at this
pin**: importing `deltatrack.bill_tree` under `-W all` with `warnings.simplefilter("always")`
produces **0 warnings** in upstream's own environment, and **0 warnings** in spicy-docs's
environment too (pypdfium2 5.13.0). Whatever produced that warning has been fixed upstream of
both projects. Filing it would hand a maintainer a claim they would fail to reproduce on their
first try, which is the fastest way to get a real issue closed as stale.

**Verdict: real gap (absent upstream)** on the import coupling; **misdescribed** on the warnings.
File with the warnings sentence removed and the 69 ms measurement in its place.

**Existing issue:** none. **#676 (open)** is the motivating epic (consumers on equal terms).

**Suggested title:** `Reading a bill's XML loads the native PDF library, because the XML parser imports two helpers from the PDF anchor parser`

**Body:**
> `bill_tree.py:8` imports `_RUNIN_QUOTED_LINE` and `_match_runin_subsection` from
> `parsers.pdf_anchors`, which imports `parsers.pdf_text` (`pdf_anchors.py:19`), which imports
> `pypdfium2` and `pypdfium2.raw` at module scope (`pdf_text.py:28-29`) — so a consumer who only
> ever calls `normalize_bill` still loads a native PDF library, measured at 69 ms for
> `import deltatrack.bill_tree` on this checkout at `c636448`, with both `pypdfium2` and
> `pypdfium2.raw` resident afterwards. `pyproject.toml:51` states the intent this cuts against:
> the engine's dependency list "is what a consumer of the engine actually gets", and an XML-only
> consumer gets more than the XML path needs. The two imported helpers are a compiled regex and a
> run-in subsection matcher, neither of which is PDF-specific, so moving them to a module both
> parsers import — or inlining them in `bill_tree` — would decouple the XML path from PDFium
> without changing either parser's behaviour.

---

# Part B — `extraction-gpo.md` §"Compared against upstream DeltaTrack"

## B1. The DSK-literal watermark regex — **real gap** (latent)

**Claim as stated.** `_WATERMARK_AND_BELOW` (`pdf_text.py:73`) still requires a literal `DSK`
substring (`\S+ on DSK\S*PROD with .*`). The real non-`DSK` machine id measured
(`ssavage on LAPJG3WLY3PROD with BILLS`, `BILLS-119hr4727ih`) would not match it. Likely masked
by `_VERDATE_AND_BELOW` running first, but latent if the watermark ever appears without a
preceding VerDate.

**Upstream at the pin.** `pdf_text.py:73`, verbatim:
`_WATERMARK_AND_BELOW = re.compile(r"\n?\S+ on DSK\S*PROD with .*\Z", re.DOTALL)`.
Applied at `pdf_text.py:165`, one line after `_VERDATE_AND_BELOW` at `:164`, inside
`strip_page_chrome` (def at `:149`). Every citation exact.

**Measured** (`dsk_probe.py`, upstream's runner):

| sample | matches `_WATERMARK_AND_BELOW` |
| --- | --- |
| `smith on DSK123PROD with BILLS` (BillTrax's literal example) | True |
| `ssavage on LAPJG3WLY3PROD with BILLS` (measured, `BILLS-119hr4727ih`) | **False** |
| `abielarski on DSK125SN23PROD with HEARING` (measured, hearing print) | True |

And the masking behaves exactly as predicted — watermark survives into body text:

| page shape | leaks? |
| --- | --- |
| VerDate line precedes the watermark | False (masked, `_VERDATE_AND_BELOW` truncates first) |
| watermark with no preceding VerDate | **True** — `'body text here\nssavage on LAPJG3WLY3PROD with BILLS'` |

**Verdict: real gap (absent upstream).** The claim is accurate in every part, including its own
correct assessment that it is latent rather than active.

**Existing issue:** **#515 (open)** is the nearest — "PDF: text-layer watermark leakage remains
unhandled pending a real draft sample" — but it is about *draft "DRAFT" stamps* rendered as
selectable text, a different artifact from the GPO print-shop job-code line. #535 (open) covers
running header/footer splicing into words, also different. **No issue covers this.**

**Suggested title:** `The print-shop watermark line is only stripped when the machine id contains "DSK", and real GPO output no longer always does`

**Body:**
> `_WATERMARK_AND_BELOW` (`pdf_text.py:73`) requires a literal `DSK` in the machine id
> (`\n?\S+ on DSK\S*PROD with .*\Z`), but current GPO output also prints ids that do not carry
> it — `ssavage on LAPJG3WLY3PROD with BILLS`, measured on `BILLS-119hr4727ih` — and checked
> against this regex on this checkout that line does not match, while `abielarski on
> DSK125SN23PROD with HEARING` does. In practice it is usually masked, because
> `_VERDATE_AND_BELOW` (`pdf_text.py:72`) truncates from `VerDate` to end-of-page one line
> earlier at `:164` and a VerDate line precedes the watermark in every sample we have; running
> `strip_page_chrome` on a page carrying the watermark **without** a preceding VerDate leaves
> `ssavage on LAPJG3WLY3PROD with BILLS` in the body text. Generalizing the id to any token
> ending `PROD`, and the trailing token to any job code, keeps every currently-matching sample
> matching while closing the case where the VerDate mask is absent.

---

## B2. The unbulleted running footer — **misdescribed** (upstream already has it)

**Claim as stated, under a heading reading "Gaps found, to raise upstream".** "`_RUNNING_FOOTER`
(`pdf_text.py:68-71`) strips an **unbulleted** running bill-stage line (e.g. `HR 5895 PCS`) — an
artifact neither BillTrax's `BULLET_BILL_RE` nor this port's kept-verbatim `_BULLET_BILL_RE`
handles. None of this port's three fixtures is a PCS/RDS/RFS print stage, so there is nothing
here to re-derive the rule against; flagged, not built."

**Upstream at the pin.** `_RUNNING_FOOTER` is present and correct at `pdf_text.py:68-71`:

```python
_RUNNING_FOOTER = re.compile(
    r"^(?:H|S|HR|HRES|SRES|HJRES|SJRES|HCONRES|SCONRES)\s+\d+\s+[A-Z]{2,4}$\n?",
    re.MULTILINE,
)
```

applied at `:163` inside `strip_page_chrome`, with a 8-line comment at `:60-67` deriving the
suffix set from the corpus ("PCS/RDS/RFS unbulleted and EAH/RH/EH/RS/IH bulleted, all 2-4 caps")
and citing `DeltaTrack#140`.

**Verdict: misdescribed — this is a gap in spicy-docs's port, filed under the wrong heading.**
Read closely, the bullet's own prose says so ("neither BillTrax's ... nor **this port's** ...
handles"; "flagged, not built"). It is upstream's rule that spicy-docs has not re-derived, not a
thing upstream lacks. Filing it would report upstream's own shipped feature back to upstream as
missing.

**Existing issue:** **#140 (CLOSED)** — "PDF chrome: unbulleted running footer (e.g. 'HR 5895
PCS') not stripped, inflates diff" — is the issue that produced this code, with its own measured
evidence (`diff_pdfs(v2, v3).summary` → `{'modified': 125}` against an XML-diff truth of
`{'modified': 1}`; 80 of 125 hunks footer-only; footer on 181 of 184 pages).

**Not worth filing.** Recommend instead correcting `extraction-gpo.md` to move this bullet out of
"to raise upstream" into a spicy-docs backlog note, citing #140.

---

## B3. The 50-line floor — **misdescribed** (upstream already has it; residual already tracked)

**Claim as stated, under the same "to raise upstream" heading.** `compare/pdf.py:60` measured
numbered/unnumbered populations ~50× apart; `compare/pdf.py:61-78` derives a 50-line floor
because short real documents read an artificially low share. "This port keeps BillTrax's original
3-content-line floor unchanged ... but the concern is real and evidence-backed on a much larger
corpus, worth a maintainer's look before `is_gpo_layout` is trusted on a very short document."

**Upstream at the pin.** Present, and more thoroughly derived than the claim suggests.
`_MIN_NUMBERED_RATIO = 0.5` at `compare/pdf.py:60` with the population sweep at `:48-59`;
`_MIN_LINES_FOR_GUARD = 50` at **`compare/pdf.py:85`**, with a floor-selection table at `:62-78`
(floors 20/29/50/200 against judged, declined and min-accepted-ratio) and an explicit
`RESIDUAL:` paragraph at `:80-84` stating that a sub-50-line unnumbered document "is still exempt
and will still diff to one anchorless block", accepted deliberately, with removal requiring
"a signal that works on tiny documents (#261)".

spicy-docs cites `:61-78` for the floor derivation; the constant itself is at `:85`.

**Verdict: misdescribed — the concern is about spicy-docs's own 3-line floor, not an upstream
gap.** Upstream has the floor, the derivation, the named residual and a tracking issue. There is
nothing here to raise.

**Existing issue:** **#261 (open)** — "Line-number-independent anchor pass for unnumbered
(enrolled / public-law) PDF layouts" — is the tracked residual, following closed **#141**.
**#679 (open)** is the active research spike on the same problem.

**Not worth filing.** Recommend the same correction as B2: move this into a spicy-docs note
citing #261/#679 as upstream's tracking.

---

## B4. The ungated hyphen rejoin — "President-elect" — **real gap**, mechanism misdescribed

**Claim as stated.** DeltaTrack's `_merge_print_lines` (`pdf_text.py:213-241`) runs
unconditionally on any line ending alphanumeric-plus-`-` whose next line starts lowercase.
`BILLS-119sconres1enr.json` contains `"...inauguration of the President-\nelect and the Vice
President-elect..."`, where `President-elect` is a genuine compound that happens to wrap at its
own hyphen. "DeltaTrack's rule as written (`current.text.endswith("-") and
current.text[-2].isalnum() and parsed[next_i].text[:1].islower()`) matches this exactly and would
delete the hyphen, producing `Presidentelect`."

**Upstream at the pin.** `_merge_print_lines` at `pdf_text.py:213-243`; the guard is at
`:231-236`:

```python
next_i < len(parsed)
and current.text.endswith("-")
and len(current.text) >= 2
and current.text[-2].isalnum()
and parsed[next_i].text[:1].islower()
```

spicy-docs's quotation omits the `len(current.text) >= 2` clause, which does not change the
outcome. The fixture is confirmed at `BILLS-119sconres1enr.json` page 0, lines 14-15:
`'the necessary arrangements for the inauguration of the President- '` /
`'elect and the Vice President-elect of the United States, is continued '`.

**Measured** (`hyphen_probe.py`, `hyphen_probe2.py`, upstream's runner). The mechanism is **not**
what spicy-docs says, and the difference matters for filing:

| how the fixture is fed | produces `Presidentelect`? |
| --- | --- |
| `strip_page_chrome` → `_parse_print_lines` → `_merge_print_lines` (**fed literally**) | **No** |
| `normalize_raw` → `strip_page_chrome` → `_parse_print_lines` → `_merge_print_lines` (**upstream's real order**, `pdf_text.py:526-528`) | **Yes** |
| export path: `rejoin_soft_hyphens(normalize_raw(raw))` (`pdf_text.py:264`) | **Yes** |
| same sentence re-shaped into upstream's own numbered GPO layout | **Yes** |

Fed literally, the captured line ends `"President- "` — with a trailing space — so
`.endswith("-")` is False and the rule declines. It only fires once `normalize_raw`
(`pdf_text.py:128-146`) strips trailing spaces at `:145`, which is precisely what
`extract_clean_pages` does first at `:526`. So spicy-docs's "matches this exactly" is wrong as
stated, and right about the outcome in the pipeline that actually runs.

Confirming it is not an artifact of feeding PyMuPDF text to a PDFium parser, the same sentence in
upstream's **own** numbered line shape corrupts identically:

```
in:  "1 the necessary arrangements for the inauguration of the President-"
     "2 elect and the Vice President-elect of the United States, is continued"
out: "the necessary arrangements for the inauguration of the Presidentelect and the Vice President-elect of the United States,"
```

Control, a genuine print-wrap in the same shape, correctly rejoins:
`"1 the House of Representa-"` / `"2 tives shall appoint a committee"` →
`"the House of Representatives shall appoint a committee"`.

**The same lowercase guard appears at three sites**, so a fix has three homes:
`_SOFT_HYPHEN_BREAK` (`pdf_text.py:32`), `_merge_print_lines` (`pdf_text.py:231-236`), and
`PAGE_HYPHEN_RE` (`amounts.py:68`). The third carries a comment at `amounts.py:64-67` arguing the
guard makes it "incapable of creating or destroying a dollar amount" — true for digits, and
orthogonal to the compound-word false positive.

**Verdict: real gap (absent upstream), mechanism misdescribed in one load-bearing detail.**
The defect reproduces; the "fed literally" framing does not. File with the corrected mechanism —
a maintainer who tries the literal reproduction first will see it decline and may close it.

**Existing issue:** **#650 (open)** — "Words split across a printed line stay broken in the
exported bill text when the continuation is uppercase" — is **the same function, the opposite
direction**. #650 is the false *negative* (`INTEL-`/`LIGENCE`, `McKinney-`/`Vento` left split
because the continuation is uppercase). This is the false *positive* (`President-`/`elect`
wrongly joined because the continuation is lowercase). #650 even names the underlying difficulty
— "Which of the two dispositions applies is not decidable from the PDF alone" — but its examples,
its title and its remedy are all about the uppercase branch. **Not covered; file as a sibling and
cross-reference.**

**Suggested title:** `A genuine hyphenated compound that wraps at its own hyphen is silently joined into one word, changing what the bill says`

**Body:**
> `_merge_print_lines` joins a line ending in `-` to the next when the continuation starts
> lowercase (`pdf_text.py:231-236`), and that test cannot distinguish a printer's syllable break
> from a real compound that happens to wrap at its own hyphen — `S. Con. Res. 1` of the 119th
> prints "...inauguration of the President-" / "elect and the Vice President-elect...", and run
> through this repository's own page pipeline (`normalize_raw` → `strip_page_chrome` →
> `_parse_print_lines` → `_merge_print_lines`, as `extract_clean_pages` composes them at
> `pdf_text.py:526-528`) that becomes `Presidentelect`, a word that appears nowhere in the bill.
> The same input re-shaped into our numbered GPO layout corrupts identically while a true
> print-wrap control ("Representa-" / "tives") rejoins correctly, and the export path is affected
> too, since `page_range_text` re-runs `rejoin_soft_hyphens` on the page seam
> (`pdf_text.py:264`) using the same lowercase guard that `_SOFT_HYPHEN_BREAK` (`pdf_text.py:32`)
> and `PAGE_HYPHEN_RE` (`amounts.py:68`) also carry. This is the mirror image of #650, which
> tracks the same rule declining a real break when the continuation is uppercase: #650 loses a
> word boundary, this loses a hyphen, and both follow from a single test that #650 already
> observes is "not decidable from the PDF alone" — the U+FFFE soft-hyphen glyph
> `_HYPHEN_BREAK` reads at `pdf_text.py:44` is the signal that distinguishes them, and it is
> discarded before either rule runs.

---

# Verdict table

| # | Claim | Upstream `file:line` at pin (= `origin/develop`) | Verdict | Existing issue |
| --- | --- | --- | --- | --- |
| A1 | Collision-group cap | `diff_bill.py:803`, dispatch `:958` | **Real gap** | none |
| A2 | Asymmetric-pair guard | `diff_bill.py:1468`; gate `similarity.py:143` | **Already addressed** (length-ratio bound); claim misdescribed | #356 open (residual) |
| A3 | Word-segment `BODY_CAP` | no such feature (`grep` empty) | **Not applicable**; correctly self-described | none |
| A4 | Hyphen-tolerant tokens | `similarity.py:75` (doc says `:73`) | **Real gap**; frequency unmeasured | #706 open (symptom) |
| A5 | D4 `" "` vs `""` join | `bill_tree.py:1136`, `:1192` | **Accurate, but consumer-side**, not an upstream defect | #676 open (argues against) |
| A6 | Version from filename | `bill_tree.py:1316-1320`, `:1470` | **Real gap**; upstream's own `compare/xml.py:84-96` pays it and loses version | none |
| A7 | Parsed-tree entry point | `compare/xml.py:39` exists; `bill_tree.py:1470` does not | **Partly addressed** (diff yes, parse no) | #698 open (adjacent) |
| A8 | XML path imports pypdfium2 | `bill_tree.py:8` → `pdf_anchors.py:19` → `pdf_text.py:28-29` | **Real gap**; "SWIG warnings" sub-claim **misdescribed** (0 warnings measured) | none |
| B1 | DSK-literal watermark regex | `pdf_text.py:73`, applied `:165` | **Real gap** (latent) | #515 open (different artifact) |
| B2 | Unbulleted running footer | `pdf_text.py:68-71`, applied `:163` | **Misdescribed** — upstream has it; gap is in spicy-docs's port | **#140 CLOSED** (built it) |
| B3 | 50-line floor | `compare/pdf.py:85`, derivation `:62-84` | **Misdescribed** — upstream has it, residual tracked | **#261 open**, #679 open |
| B4 | Ungated hyphen rejoin, "President-elect" | `pdf_text.py:231-236`; also `:32`, `amounts.py:68` | **Real gap**; mechanism misdescribed (needs `normalize_raw` first) | #650 open (opposite direction) |

# Worth filing, in priority order by measured impact

1. **B4 — hyphen rejoin false positive.** *Correctness, not performance.* Silently changes what a
   bill says (`Presidentelect`), reproduced through upstream's real pipeline and in upstream's own
   line shape, affecting both the diff path and the exported `full_text`. Three code sites share
   the guard. Sibling to open #650, which gives it a maintainer already holding the context.
   **File with the corrected mechanism** — the literal reproduction fails.
2. **A1 — collision-group cap.** Measured 8.74 s for a single 300-section `match_path` group, flat
   ~95 µs/pair, clean O(N²) with no ceiling. The one claim here with a complete measurement of its
   own and no existing issue.
3. **A6 + A7 — version keyword and a parsed-tree `normalize_bill`** (one issue). Strongest
   self-evidence of the set: upstream's own `_build` writes temp files and gets `version == ""`
   for its trouble, then carries `start_label`/`end_label` to work around it. Cheap fix,
   immediately useful to upstream itself. Cross-reference #698, motivate with #676.
4. **A8 — XML path loads pypdfium2.** 69 ms and a native library for XML-only consumers, against
   `pyproject.toml:51`'s stated intent. Two non-PDF helpers are the whole coupling. **Drop the
   SWIG-warnings sentence** — 0 warnings measured in both environments.
5. **B1 — DSK-literal watermark regex.** Correct in every particular, including that it is latent.
   Low urgency, low cost, and the measured non-matching machine id makes it concrete. Note in the
   body that it is currently masked, so nobody treats it as an active bug.
6. **A4 — hyphen-tolerant matching tokens.** Real and certain in mechanism, but no measurement of
   how often it flips a pairing. File only with an explicit "frequency not measured" line, in the
   style #368 already uses, and reference #706.

# Not worth filing, with reasons

| Claim | Reason |
| --- | --- |
| **A2 — asymmetric-pair guard** | Already addressed, and better than proposed: `real_quick_ratio` (`similarity.py:143`) prunes the cited 988×1 shape to **0.014 s / 0 candidates**, because extreme asymmetry is what a length-ratio bound prunes hardest. BillTrax's attribution of a 120 s SIGKILL to "the Python DeltaTrack engine" does not reproduce at this pin, and the gate predates it (`4b23e65`, 2026-07-09). The genuine residual is many×many, already **#356**. |
| **A3 — word-segment `BODY_CAP`** | Upstream has no word-segment rendering (`grep` returns nothing), so the cap has nothing to attach to. spicy-docs says as much itself. Revisit only if the feature is proposed. |
| **A5 — D4 space-join note** | Accurate, but it is a downstream reparse obligation, not an upstream defect; upstream's behaviour is the intended one. **#676** is explicitly retiring the practice of routing BillTrax-consumer concerns into this tracker. |
| **B2 — unbulleted running footer** | Upstream **has** the rule (`pdf_text.py:68-71`), shipped for **#140 (closed)** with its own corpus evidence. The bullet's own prose says the gap is in *this port*. Filing would report a shipped feature back as missing. |
| **B3 — 50-line floor** | Upstream **has** `_MIN_LINES_FOR_GUARD = 50` (`compare/pdf.py:85`) with a floor-selection table, a named `RESIDUAL:` and tracking issue **#261** (plus active spike **#679**). The concern described is about spicy-docs's own 3-line floor. |

# Two corrections recommended to spicy-docs

Both are cases where a bullet sits under "to raise upstream" while its own text describes a gap
in spicy-docs's port:

- `docs/extraction-gpo.md:228-234` (`_RUNNING_FOOTER`) — move out of the upstream list; cite
  upstream **#140** and `pdf_text.py:68-71` as already solving it.
- `docs/extraction-gpo.md:235-247` (50-line floor) — move out of the upstream list; cite
  `compare/pdf.py:85` and upstream **#261**/**#679** as the tracked residual.

Additionally, three citation fixes for accuracy before anything is filed:
`similarity.py:73` → `:75` (operative line), `amounts.py:59` → `:68` (regex, not its comment),
and `compare/pdf.py:61-78` → `:85` for the constant itself.
