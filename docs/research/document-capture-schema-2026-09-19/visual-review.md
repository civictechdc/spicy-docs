# Visual review of the document capture profiles

**Retained as received.** This is the review's own report, copied into the
design record's folder with its fourteen viewed pages under `png/` and nothing
else changed. What each finding moved is in the design record under "What the
reviews changed"; the fixes landed after this was written, so the verdicts
below are the ones the review reached against the draft, not against the
current captures. The remaining retained output (the per-page node listings
and the request log) stays in the review's own working folder.

2026-09-19. Read-only review of the six `DocumentCapture v1` family profiles on
branch `capture-schema-2026-09-19` (worktree
`spicy-docs/.claude/worktrees/capture-schema`), against the print rendition of
each family's worked document. Nothing in either repository was written; all
output is under this folder.

## Method

- One PDF per family. Two were already retained locally and matched their
  receipts by digest (`local-sources.md`): the SCOTUS slip opinion
  (`7c14a9d1…`, 66,165 bytes, receipt line 1 of
  `~/Work/corpora/supply-2026-09-02/receipts/document-capture-schema-2026-09-19/requests.jsonl`)
  and the CFR section PDF (`50854828…`, 157,908 bytes,
  `tests/fixtures/reconstruction/cfr/provenance.json`). The other four were
  fetched keyless with `httpx.Client(timeout=30)` from the publisher's stated
  folder grammar (`PACKAGE_BODY_FORMATS["pdf"]` in
  `src/spicy_docs/sources/govinfo/bodies.py`; the FR `pdf_url` from the
  retained `inputs/fr-2026-19200.json`). **4 requests of the 8 allowed**, all
  `200`, `application/pdf`, `%PDF-` magic, logged in `requests.jsonl` (URL,
  time, status, content type, bytes, sha256, magic, accepted). The fetched
  CRPT-119hrpt1 digest (`921bcbba…`) equals an older scratchpad copy, an
  incidental cross-check.
- Every page of every PDF rendered at 120 DPI with PyMuPDF (`png/`, 18 files);
  14 were viewed: scotus p1, p4, p5; cfr p1–p3; plaw p1–p4; bills p1; crpt p1,
  p3; fr p1.
- Capture nodes were listed per page with `nodes.py` (page coordinates for the
  two PDF-text families; the full tree, matched by text, for the four markup
  families). Listings retained: `scotus-pages-1-4-5.txt`, `cfr-pages.txt`,
  `plaw-tree.txt`, `bills-119hjres25enr-tree.txt`, `crpt-119hrpt1-tree.txt`,
  `fr-2026-19200-tree.txt`.
- Where the capture and the print disagreed, the publisher's own markup
  (`tests/fixtures/uslm/plaw-119publ1.xml`,
  `tests/fixtures/govinfo_bills/text-119hjres25enr.xml`,
  `tests/fixtures/cfr/annual-title30-vol3-sec716-2.xml`,
  `tests/fixtures/govinfo_bodies/body-CRPT-119hrpt1.htm`) was checked to
  separate a converter fault from a rendition gap or a publisher error.

Severity: BLOCKER = the profile cannot represent a structure the family's
print reliably shows; WARNING = the converter missed or mislabelled a visible
element the profile could carry; NIT = otherwise.

## Summary

| Family (profile) | Pages viewed | Visible structural elements | Nodes matched (right kind and level) | Disagreements B / W / N | Verdict |
| --- | --- | ---: | ---: | --- | --- |
| slip-opinion-pdf (scotus-26a274_l537) | p1, p4, p5 of 5 | 32 | 0 typed (all 32 present only as `line`; plus 39 whitespace-only `line` nodes the print does not show) | 1 / 3 / 2 | DOES NOT FIT as a family profile (holds only as a raw page/line capture) |
| cfr-reconstruction (CFR-2025-title30-vol3-sec716-2) | p1, p2, p3 of 3 | 76 | 74 | 0 / 0 / 5 | HOLDS |
| uslm-law (PLAW-119publ1) | p1–p4 of 4 | 91 | 90 | 0 / 1 / 4 | HOLDS WITH FIXES (U1) |
| bill-xml (BILLS-119hjres25enr) | p1 of 1 | 10 | 9 | 0 / 0 / 3 | HOLDS (thinly exercised) |
| committee-report-html (CRPT-119hrpt1) | p1, p3 of 4 | 23 | 11 | 0 / 2 / 5 | HOLDS WITH FIXES (R1, R2), or HOLDS only as a declared block capture not to be cited for structure |
| federal-register-xml (FR 2026-19200) | p1 of 1 | 40 | 37 | 0 / 0 / 6 | HOLDS |

"Nodes matched" counts visible elements that have a node of the right kind
(and level where the profile states one); the difference is either a
mislabel, a missing node, or a rendition gap, each listed below.

## Findings by family

### 1. Slip opinion (`slip-opinion-pdf`, `scotus-26a274_l537.capture.json`)

Images: `scotus-26a274_l537-p1.png`, `scotus-26a274_l537-p4.png`,
`scotus-26a274_l537-p5.png`. Capture: 243 nodes = 1 `document`, 5 `page`,
237 `line`; every node `derivation: pdf-text`; no family kind; `profile.ext.classification`
= "none: the no-reference case, pages and lines only".

What the print shows on the viewed pages, and what the capture has for it:

| Visible element | Image | Capture |
| --- | --- | --- |
| Running head "Cite as: 609 U. S. ____ (2026)" and page number "1" | p1, p5 | `line` n0023 / n0022 (p1), n0221 / n0220 (p5); core `runningHead`, `pageNumber` unused |
| Running head "NATIONAL REPUBLICAN CONGRESSIONAL / COMMITTEE v. BROWN" with page number "4" merged into the first line | p4 | `line` n0184 "4 NATIONAL REPUBLICAN CONGRESSIONAL", n0185 |
| Opinion-type header "Per Curiam" (p1, p4) and "JACKSON, J., dissenting" (p5) | p1, p4, p5 | `line` n0024, n0186, n0222 |
| Court masthead "SUPREME COURT OF THE UNITED STATES", two rules, docket "No. 26A274", caption (3 lines), "ON APPLICATION FOR STAY", "[September 4, 2026]" | p1, p5 | `line` n0020–n0031 and n0218–n0229; core `title`/`heading` unused |
| Opinion opening "PER CURIAM." and "JUSTICE JACKSON, dissenting." | p1, p5 | `line` n0032, n0230 |
| Body paragraphs (first-line indent at x=273‰ vs 255‰ is visible in the boxes) | all | `line` only; no `paragraph` |
| Section break "* * *" and closing formula "It is so ordered." | p4 | `line` n0191, n0202 |
| Two opinions: the per curiam (pp. 1–4) and the dissent (p. 5), the dissent restarting the printed page count at "1" | p1, p5 | nothing; `page` n0203 has `designation: "5"` |

Findings:

- **S1 BLOCKER.** The opinion division is unrepresented and unrepresentable
  in this profile. The print reliably marks it three ways (the header line
  "Per Curiam" / "JACKSON, J., dissenting", the opening formula, and the
  per-opinion restart of the printed page number), and the family is defined
  by it: syllabus, opinion of the Court, per curiam, concurrence and dissent.
  The profile declares no family kind, closes node `ext` to `{}`, and the
  core vocabulary has no opinion kind; the only route is a core `division`
  with a free-text `designation`, and the converter does not take it. The
  design record says so itself ("Everything: no running head, syllabus or
  opinion boundary is classified") and lists a reconstruction profile for
  this family among the decisions left to the user. The judgment here is
  that, as a *family profile*, it does not fit; as a raw page/line capture
  it round-trips (text coverage is complete: every printed line has a node).
- **S2 WARNING.** Page furniture and body are not separated. Running head,
  page number, masthead, docket number, caption, "ON APPLICATION FOR STAY",
  date line, opening formula, section break and closing formula are all
  `line` children of `page`; the core has `runningHead`, `pageNumber`,
  `title`, `heading`, `paragraph` for them. The running-head band is a
  fixed geometry (y 144–187‰ on every page) that a rule could classify
  without a corpus.
- **S3 WARNING.** 77 of 237 `line` nodes are whitespace-only (`exact` is
  one or two spaces, boxes 4–10‰ wide), 39 on the viewed pages (17 on p1:
  n0003–n0019; 8 on p4: n0176–n0183; 14 on p5: n0204–n0217). The print shows
  nothing there. They are ordered *before* the real lines, so `line`
  ordinals do not match printed line numbers (p1's page number is line 20).
  No `empty-leaf` issue is raised, although the bill and FR captures raise
  one for the publisher's empty elements.
- **S4 WARNING.** `page.designation` is the PDF ordinal ("1"…"5"), but the
  parent schema defines `designation` as "the publisher's own label … a
  printed page number", and page 5 prints "1" (`scotus-26a274_l537-p5.png`).
  Either the designation should be the printed number or the printed number
  should be a `pageNumber` node.
- **S5 NIT.** Line order is not reading order on p1/p5: the two rules
  (n0020/n0021, y 219–264‰) precede the running head (y 144‰), and "1"
  precedes "Cite as" on the same baseline although it sits at the right.
- **S6 NIT.** `profile.ext.classification` is a free string; if the family
  keeps a "no classification" mode it should be an enum so consumers can
  test it.

Verdict: **DOES NOT FIT** as a family profile. Fixes that would make it hold:
a `slip-opinion-pdf:opinion` (or core `division`) node per opinion with
`ext.author` and `ext.opinionType` (syllabus, perCuriam, opinionOfTheCourt,
concurrence, dissent, …), running head and page number by the fixed band,
whitespace lines dropped or flagged, `page.designation` set to the printed
number.

### 2. CFR reconstruction (`cfr-reconstruction`, `cfr-2025-title30-vol3-sec716-2.capture.json`)

Images: `cfr-2025-title30-vol3-sec716-2-p1.png`, `-p2.png`, `-p3.png`.
Capture: 87 nodes, all `reconstructed`, with `decision` and `reviewStatus`.

Matched on the print: page numbers 89/90/91 (`pageNumber` n0002, n0059,
n0062, boxes at y 906–919‰ = the foot of each page); running heads
(`runningHead`); "PART 716—SPECIAL PERFORMANCE STANDARDS" (`partHeading`);
the "Sec." contents list (`contents`, 9 lines); AUTHORITY and SOURCE
(`authority`, `sourceNote`); § 716.1–716.4 each as `section` +
`label` "§ 716.x" + `heading` level 1 (the subject); the paragraph ladder
`(a)/(1)/(i)/(A)` with depth following the print's indentation, checked
line by line for 716.2(e)(3)(i)–(iv), (iv)(A)–(C), (4)(i)–(iii),
(iii)(A)–(C) across p1–p2; a unit with its own text and children keeps its
lines in a first `text` child (n0012 for 716.1(a)); the amendment citation
"[42 FR 62691 … Dec. 17, 1980]" (`cita`); two paragraphs that run across a
column break within a page (716.2 intro n0023, (v) n0044) are single
contiguous leaves.

The two documented non-contiguous leaves are real page breaks inside a
paragraph:

- n0036 "(i) The permittee has demonstrated…" — spans s0237/s0239 on p1
  lines 116–117 (right column foot, y 872–893‰; `-p1.png` ends "that the
  purpose of the variance is to") then s0247–s0259 on p2 lines 4–10 (left
  column head, y 224–302‰; `-p2.png` opens "make the lands to be affected
  within").
- n0056 "(iv) Place off the mine bench…" — p2 lines 116–121 (`-p2.png`
  ends "ments of the Act and parts 710 through") then p3 lines 3–6
  (`-p3.png` opens "725 of this chapter.").

Findings:

- **C1 NIT.** The two italic run-in headings ("Variances from approximate
  original contour restoration requirements." in 716.2(e), `-p1.png` right
  column; "Definition." in 716.4(a), `-p3.png`) have no `heading` node and
  their spans say `style.italic: false` although `style.font` is
  "MIonic, MIonic-Italic". GPO's own XML marks the same text as an inline
  `<E T="03">` inside one `<P>`, so the tree is faithful to the reference;
  the `italic` flag is the extractor's miss and is recoverable from the font
  name.
- **C2 NIT.** 716.2(e)(1) has no node: "(1)" never begins a line and is
  folded into (e)'s text leaf (n0029), which is exactly GPO's single `<P>`.
  The parser then flags (2) `needs_review` ("marker (2) is out of sequence
  under marker_hierarchy"), which is the honest signal.
- **C3 NIT.** The p1 running head is one node ("Surface Mining Reclamation
  and Enforcement, Interior § 716.2", n0003) while p2/p3 have two (n0060
  "30 CFR Ch. VII (7–1–25 Edition)", n0061 "§ 716.2"); the print sets a left
  and a right part on every page. Line assembly, not the profile.
- **C4 NIT.** The neighbouring sections 716.1, 716.3 and 716.4 are full
  `section` trees at the same depth as the selected 716.2, distinguishable
  only by the absence of `ext.xmlPath` (33 nodes carry it) and by
  `profile.ext.selectedSection`. 716.4 is correctly `needs_review` with
  detail "ends at the rendition's last line: the section may continue beyond
  it" (`-p3.png` ends mid-paragraph).
- **C5 NIT.** The GPO authentication seal at the top left of p1 is a graphic
  with no node; it is not text and not in the reference XML. (The same seal
  appears on the PLAW, BILLS, CRPT and FR prints; not repeated below.)

Verdict: **HOLDS.**

### 3. USLM public law (`uslm-law`, `plaw-119publ1.capture.json`)

Images: `plaw-119publ1-p1.png` … `-p4.png`. Capture: 320 nodes, all
`native`.

Matched on the print: running head "PUBLIC LAW 119–1—JAN. 29, 2025"
(`runningHead` n0021, once, as the XML carries it once); "139 STAT. 3"
(`pageNumber` n0022); "Public Law 119–1", "119th Congress" (front-matter
`text`); "An Act", the official title (`title`); the four margin sidenotes
"Jan. 29, 2025", "[S. 5]", "Laken Riley Act.", "8 USC 1101 note."
(`uslm-law:sidenote` > `paragraph`); the enacting clause
(`uslm-law:enactingFormula`); SECTION 1 / SEC. 2 / SEC. 3 as `section` +
`label` + `heading`; the ladder (1)(A)(B)(C)(E)(i) as `paragraph` with
`label` and `designation`; every quoted insertion as `quote` >
`paragraph` with a `label` "“(2) " and a run-in `heading` ("Definition.—",
tag `inline`); subsection run-in headings "(a) INSPECTION OF APPLICANTS FOR
ADMISSION.—" as `heading` tag `inline`; "striking"/"inserting" as
`uslm-law:amendingAction`; quoted terms as spans tagged `quotedText`;
"Approved January 29, 2025." (`text <action>`); "LEGISLATIVE HISTORY—S. 5
(H.R. 29):" (`heading`), the two `note`s with their headings and lines, and
the end marker "○" (`-p4.png`). The print's unquoted "(E)(i)" followed by
quoted "“(ii)" (`-p1.png`) is exactly how the capture nests them (n0084
plain `subparagraph`, n0090 `quote` for (ii)); this was checked, not a
disagreement.

Findings:

- **U1 WARNING.** The legislative-history block (`-p4.png`, the ruled block
  at the foot of 139 STAT. 6) has no container node: the XML's
  `<legislativeHistory>` is dropped and its `heading` n0312 and `note`s
  n0313/n0317 hang off `document` at depth 1 beside `body`. Core
  `backMatter` exists and the bill profile uses it for the attestation; the
  USLM converter should map `legislativeHistory` to it.
- **U2 NIT (publisher error, surfaced without an issue).** `pageNumber`
  designations are "139 STAT. 3", "139 STAT. 4", "139 STAT. 4", "139 STAT.
  5"; the print runs STAT. 3–6. The XML's four `<page>` markers (lines 22,
  46, 58, 67) sit exactly where pages 1–4 begin (before "(3) ENFORCEMENT…",
  after "Secretary of Homeland Security”; and", before "(3) CERTAIN
  ACTIONS"), so GPO mislabelled the third and fourth. The capture is
  faithful; a cheap invariant (pageNumber designations unique and
  increasing) would raise an issue instead of passing the error on.
- **U3 NIT.** No `heading` carries `level`; section headings and inline
  run-in headings are told apart only by the span tag `inline`. The FR
  profile sets `level: 1` on every heading. The two families read the
  parent's optional `level` differently.
- **U4 NIT.** "Approved January 29, 2025." is a body-level `text` leaf with
  tags `actionDescription`/`date`; the print sets it as the approval line.
  Fine under "the publisher's element name travels in `source.element`",
  noted because it is the law's signature-equivalent.
- **U5 NIT.** The rule above the legislative history and the seal are
  graphics with no XML counterpart; no node, correctly.

Verdict: **HOLDS WITH FIXES** — U1 (map `legislativeHistory` to
`backMatter`); U2 as a recommended invariant.

### 4. Bill XML (`bill-xml`, `bills-119hjres25enr.capture.json`)

Image: `bills-119hjres25enr-p1.png` (one page). Capture: 26 nodes, all
`native`.

Matched: "H. J. Res. 25" (`text <legis-num>`); "One Hundred Nineteenth
Congress of the United States of America" (`<congress>`); "AT THE FIRST
SESSION" (`<session>`); the dateline (`<enrolled-dateline>`); "Joint
Resolution" (`<legis-type>`); the official title (`title`); the body
paragraph "That Congress disapproves…" (`body` > `section` > `label`
(empty) + `paragraph`); "Speaker of the House of Representatives." and
"Vice President of the United States and President of the Senate."
(`backMatter <attestation>` > `bill-xml:attestationGroup` > `text <role>`).

Findings:

- **B1 NIT (rendition gap, recorded).** The resolving clause "Resolved by the
  Senate and House of Representatives … assembled," is printed but has no
  node: the XML carries no such text (0 occurrences of "Resolved"; it is
  implied by `resolution-body style="traditional"`). The capture records the
  engine's synthesized `front-matter-resolving-clause` as a
  `deltatrack-node-without-element` issue, which is the right answer for a
  capture of this rendition.
- **B2 NIT.** The undesignated section has `designation: ""` and an empty
  `label` with an `empty-leaf` issue; the print shows no number, so this is
  correct, but a consumer should not read "" as a designation.
- **B3 NIT.** Only one of the profile's node-`ext` fields is populated
  beyond a default (`tag`, `elementId`, `bodyIndex` on n0019; `matchPath`
  and `displayPath` are empty lists); the profile requires all six on every
  node, so 25 of 26 nodes carry six empty fields.

Verdict: **HOLDS**, thinly exercised: a one-section resolution shows no
`toc`, no `quoted-block`, no enumerated ladder and no page furniture.

### 5. Committee report HTML (`committee-report-html`, `crpt-119hrpt1.capture.json`)

Images: `crpt-119hrpt1-p1.png`, `crpt-119hrpt1-p3.png`. Capture: 44 nodes
(4 `native`, 40 `markup`), of the HTML `<pre>` rendition; compared by text.

Matched: the report title (`title`, and `paragraph` n0009 in the body);
"[House Report 119-1]" and "[From the U.S. Government Publishing Office]"
(`banner`, HTML-only); the "=====" and "_______" rules (`rule`); the date
line, "Mr. Austin Scott…", "[To accompany H. Res. 53]", and every body
paragraph (`paragraph`).

Findings:

- **R1 WARNING.** The ruled vote tables (`-p3.png`: three tables "Majority
  Members / Vote / Minority Members / Vote", one more on p2) are each one
  `paragraph` (n0025, n0028, n0031, n0034) holding the dashed rules, the
  header row and the member rows as text. Core `table`/`row`/`cell` exists;
  the `<pre>` text is column-aligned with a dashed rule above and below the
  header, so the structure is detectable without a corpus. The design record
  declares "no table structure" for this family; the print reliably shows
  one.
- **R2 WARNING.** Every heading is a `paragraph`: the centred section heads
  ("R E P O R T", "SUMMARY OF PROVISIONS OF THE RESOLUTION", "EXPLANATION OF
  WAIVERS", "COMMITTEE VOTES", "SUMMARY OF THE AMENDMENTS TO H.R. 471 MADE IN
  ORDER", "TEXT OF AMENDMENTS…", `-p1.png`/`-p3.png`), the italic "Rules
  Committee record vote No. N" heads, and "SEC. 309. FIRE SAFE ELECTRICAL
  CORRIDORS." in the amendment text. Core `heading` exists; centring is
  visible in the `<pre>` as leading-space width. Declared gap, same status
  as R1.
- **R3 NIT.** The masthead box ("119th Congress } { Report / HOUSE OF
  REPRESENTATIVES / 1st Session } { 119-1", `-p1.png`) is `paragraph` n0007;
  it is front matter.
- **R4 NIT.** The numbered amendment summaries "1. Perry (PA)…" and
  "1. Carbajal (CA)…" (`-p3.png`) are one `paragraph` (n0036); no
  `list`/`item`.
- **R5 NIT.** The print's page numbers ("3") and print-shop footers
  ("59–008", "E:\HR\OC\HR001.XXX") are absent from the HTML (0 `[[Page`
  markers), so the family's `pageNumber` mapping described in the design
  record is untested by this document.

Verdict: **HOLDS WITH FIXES** (R1 fixed-column table rule; R2 centred and
all-caps heading rule) if captures of this family are to be cited for
structure; **HOLDS** as the declared blank-line block capture otherwise, in
which case the design record's "not to be cited for structure" caveat
should travel with the profile description.

### 6. Federal Register XML (`federal-register-xml`, `fr-2026-19200.capture.json`)

Image: `fr-2026-19200-p1.png` (one page; the third column's "City of Aspen"
notice is the next document and is correctly absent). Capture: 75 nodes,
all `native`.

Matched: page number "59123" (`pageNumber`, designation "59123");
"DEPARTMENT OF ENERGY", "Federal Energy Regulatory Commission", "[Docket
No. IC26-36-000]" (front-matter `text`); the subject (`title`); AGENCY:,
ACTION:, SUMMARY:, DATES:, ADDRESSES:, FOR FURTHER INFORMATION CONTACT:
(`section` > `heading` level 1 + `paragraph`s); SUPPLEMENTARY INFORMATION:
(`body` > `heading` level 1); the two footnotes at the column feet
(`footnote` n0039, n0041 with superscript spans tagged `SU`, and the
references in n0038 tagged `SU`); the burden table (`table` > `row`
`BOXHD` with 7 `cell`s `header: true` and two `ROW`s of 7 `cell`s,
`cell.row/column` consistent with the print's 7 columns); "Dated: September
15, 2026. / Debbie-Anne A. Reese, / Secretary." (`signature` >
`text` DATED/NAME/TITLE); "[FR Doc. 2026-19200 Filed…]" and "BILLING CODE
6717-01-P" (`text`). The empty `P` (n0032, `empty-leaf`) corresponds to
nothing printed.

Findings:

- **F1 NIT.** The running head "Federal Register / Vol. 91, No. 180 /
  Friday, September 18, 2026 / Notices" is print furniture absent from the
  XML; no node, correctly.
- **F2 NIT.** Run-in italic heads ("Title:", "OMB Control No.:",
  "Abstract:", "Type of Respondents:", "Estimate of Annual Burden",
  "Comments:", "Docket:") are `E` span tags inside `paragraph`, not
  `heading`; this matches the publisher's `<E>` markup (same shape as CFR
  C1).
- **F3 NIT.** The two bulleted address items ("• Mail via U.S. Postal
  Service Only:", "• All other delivery methods:") are `paragraph`s with the
  bullet in the text, as the publisher's `<P>`; core `list`/`item` unused.
- **F4 NIT.** The table's second row ("(1)", "(2)", "(1) * (2) = (3)"…) is
  `header: false` (a `ROW` in GPO's XML) while the print sets it inside the
  ruled header block; native, but a consumer building a header should know.
- **F5 NIT.** All seven headings are `level: 1` from `HED`; `ext.headLevel`
  is recorded on all seven but `HD1`/`HD2` nesting is not exercised here.
- **F6 NIT.** `FRDOC` and `BILCOD` are root-level `text` leaves beside
  `frontMatter` and `body`; the print sets them as the document's tail and
  core `backMatter` would name that.

Verdict: **HOLDS.**

## Profile schemas against what was seen

| Profile | Family kinds (seen / never seen) | Node `ext` fields (populated) | Visible structure with no kind | Notes |
| --- | --- | --- | --- | --- |
| `slip-opinion-pdf` | none declared | none (`ext` closed to `{}`) | opinion division and type, running head, page number, masthead, docket number, caption, opening formula, section break, closing formula, rules; (syllabus, footnotes, headnotes not in this document) | Core kinds could carry the furniture; nothing can carry opinion author/type. `profile.ext.classification` is free text |
| `cfr-reconstruction` | seen: `partHeading`, `contents`, `authority`, `sourceNote`, `cita`; never seen: `flushParagraph`, `blank` | `reconstructionNode`, `reconstructionKind` (86), `xmlPath` (33) | italic run-in heading (matches GPO inline `E`); left/right running-head parts | Fits the print; `flushParagraph`/`blank` need another fixture to be witnessed |
| `uslm-law` | seen: `amendingAction` (25), `sidenote` (3), `enactingFormula` (1); never seen: `toc`, `sourceCredit` | `identifier` (31), `numValue` (38), `role` (9) | legislative-history container (core `backMatter` available, unused); approval `action` line | U1; `level` unused |
| `bill-xml` | seen: `attestationGroup` (2); never seen: `toc` | `tag`, `elementId`, `bodyIndex` on 1 node; `matchPath`/`displayPath`/`sectionNumber` empty everywhere | resolving clause (not in the XML rendition) | Six required per-node fields, five empty on 25 of 26 nodes |
| `committee-report-html` | seen: `banner` (2), `rule` (3), `preformatted` (1) | none declared | headings, tables, masthead, numbered list (core kinds exist, converter unused); page numbers absent from the HTML | R1, R2 |
| `federal-register-xml` | never seen: `listOfSubjects`, `regText` (a notice has neither) | `headLevel` (7), `indent` (2), `cols` (1), `cdef` (1) | running head (not in XML); bullets (core `list` unused); FRDOC/BILCOD tail (core `backMatter` unused) | Fits the print; `regText`/`listOfSubjects`, `HD1+`, and multi-page `PRTPAGE` need a rule document to be witnessed |

Cross-family observations:

- `level` is set by one family (FR, always 1) and by CFR (subject headings,
  always 1) and never by USLM; the parent leaves it optional with no rule
  for who sets it. Either state a rule per profile or drop the field until a
  family has more than one level to show.
- `backMatter` is used by one family (bill attestation) and skipped by two
  that have back matter in print (USLM legislative history, FR
  FRDOC/BILCOD).
- Whitespace-only leaves are flagged `empty-leaf` in the markup families and
  unflagged in the slip opinion; `check_invariants` should treat a leaf whose
  `text.strip()` is empty the same way everywhere.
- Nothing seen contradicts the parent's text-partition contract: on every
  viewed page, every printed line of the document's own text is present in
  some leaf, and no leaf claims text the print lacks other than S3.

## Verdicts

| Profile | Verdict |
| --- | --- |
| `uslm-law` | HOLDS WITH FIXES: U1 (`legislativeHistory` → `backMatter`); recommended U2 invariant |
| `bill-xml` | HOLDS (thinly exercised; no finding above NIT) |
| `committee-report-html` | HOLDS WITH FIXES: R1 (tables), R2 (headings), or HOLDS only as a declared block capture not to be cited for structure |
| `federal-register-xml` | HOLDS |
| `cfr-reconstruction` | HOLDS |
| `slip-opinion-pdf` | DOES NOT FIT as a family profile: the print reliably shows opinion divisions with author and type and per-opinion pagination, and the profile can name none of it (S1); page furniture unclassified (S2), phantom whitespace lines (S3), page designation not the printed number (S4). Holds only as a raw page/line capture, which is what the design record calls it |

## Request log

`requests.jsonl`: 4 lines, 4 requests, all keyless, all accepted
(PLAW-119publ1.pdf 205,794 B `b3a9255e…`; BILLS-119hjres25enr.pdf 119,080 B
`5ec454c7…`; CRPT-119hrpt1.pdf 210,204 B `921bcbba…`; FR 2026-19200.pdf
206,989 B `ba90e1b0…`). Two documents used digest-verified local copies
(`local-sources.md`). Budget: 4 of 8.

## What this review cannot see

One document per family, so nothing here bounds coverage: the bill has no
ladder or `quoted-block`, the notice has no `REGTEXT`, `HD1` or second page,
the law has no TOC or source credit, and the slip opinion has no syllabus,
footnote or concurrence. The committee-report comparison is between a
typeset PDF and a `<pre>` rendition of the same text, so page furniture
differences there are rendition facts, not converter faults. Page-region
coordinates were checked against the images for the two PDF-text families
by band (running-head, body, page-number) and by page-break position, not
pixel by pixel.
