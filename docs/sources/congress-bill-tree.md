# Read a bill's sections and diff two versions

Give SpicyDocs the XML bytes of a bill text version. It returns the version's
content-bearing sections, the publisher identity on each, and a count of every
element the flattening dropped. Give it two of those and it returns the rows the
section-diff tables hold, each one saying why its two sections were paired.

The engine is [DeltaTrack](https://github.com/civictechdc/DeltaTrack), the
sibling Civic Tech DC package. SpicyDocs depends on it; it does not contain a
copy of it.

Install the `bill-diff` extra. From this checkout, use
`uv sync --frozen --extra bill-diff`, then run this with `uv run --frozen python`:

```python
from spicy_docs.interpretation.section_diff import diff_sections
from spicy_docs.sources.congress.bill_tree import parse_bill_tree

introduced = parse_bill_tree(introduced_xml_bytes, version="ih")
engrossed = parse_bill_tree(engrossed_xml_bytes, version="eh")

print(introduced.root_tag, introduced.body_tags, introduced.stage)
for node in introduced.sections:
    print(node.match_path, node.section_number, node.element_id)

diff = diff_sections(introduced, engrossed, from_version="ih", to_version="eh")
print(dict(diff.summary))
for item in diff.items:
    print(item.seq, item.op, item.similarity, item.pairing_rule)
```

Without the extra, both modules still import and `parse_bill_tree` refuses by
naming it. `engine_available()` answers the question directly, which is what the
tests skip on.

## Input shape

One GPO bill text version, as bytes. Measured over a 40-file sample on
2026-09-19 ([raw data](../research/billtrax-raw-data-2026-09-19.md) §2):

| Fact | Measured |
| --- | --- |
| Root element | `bill` 10 · `resolution` 29 · `amendment-doc` 1; the root tag equals the DOCTYPE name in every file |
| Version on the root | `@bill-stage` 10 · `@resolution-stage` 29 · absent on `amendment-doc` |
| DOCTYPE | 40/40 carry a PUBLIC id **and a relative SYSTEM id** (`bill.dtd`, `res.dtd`, `amend.dtd`) |
| CDATA, BOM, U+FEFF | 0/40 each |
| Distinct elements | 100 across the sample; 19 to 72 per file |
| Largest file | 9.4 MB |

The bytes go through [`reading/xml.py`](../../src/spicy_docs/reading/xml.py),
which bounds them at 24 MiB, refuses entity declarations and references, and
accepts the external DOCTYPE **without resolving it**. That last part is not a
formality: every file names a DTD *beside itself*, so a resolving parser issues
an unbudgeted request per document.

## Supported bodies

| Body | Handled | Note |
| --- | --- | --- |
| `legis-body` | yes | Every top-level one, in document order. A reported bill carrying a committee substitute prints two complete texts; upstream walks both. |
| `resolution-body` | yes | Joint, concurrent and simple resolutions share this shape. |
| `engrossed-amendment-body/amendment/amendment-block` | yes | Found at any depth. |
| Two `resolution-body` or two `preamble` | **refused, loudly** | A reported-stage resolution can carry the committee amendment as paired struck and added blocks. Choosing between them is an amendment-display decision, not a parse decision, so the document refuses rather than silently rendering the superseded text. |

**Why this matters.** The two copies this replaces handled only `legis-body` and
the amendment chain. 29 of the 40 sampled files carry `resolution-body` and no
`legis-body`; resolutions are 3,416 of the 21,947 XML files in the 119th
Congress (15.6%), and the only appropriations-structured document in the sample
was one of them. Both former parsers threw on all 29, and BillTrax's caller
caught the throw and silently degraded to splitting the plain-text column.

## The element inventory

`parse_bill_tree` returns three counts beside the engine's nodes:
`element_counts` (every element), `kept_elements` and `discarded_elements`. They
sum, by construction, and the total is checked against a regex count of the
start tags in the raw bytes — a different tool family from the parse under test,
so the two agreeing is evidence rather than the parser confirming itself.

An element counts as read when it sits inside an element whose `id` reached a
node, when its own text is one of the strings or lines a node carries, or when
it is a container whose children are all read and which adds no text of its own.

**What the count cannot see**, because a measurement that reports agreement with
itself is not a verification:

- It measures whether an element's words survive *somewhere*, not whether the
  engine read that element.
- Rule 1 is a subtree account: an element inside a node whose text the
  extractor skipped still counts as read.
- Two elements carrying the same words are indistinguishable, and only one of
  them may have been read.

The error therefore runs toward **over**-reporting, deliberately. A title's own
`<header>` and `<enum>` appear as dropped because their text reaches the output
only fused into a composed label like `TITLE I—Active Components`. The earlier
version of this rule credited those composed labels, which marked every
`<toc-entry>` read — GPO spells a table-of-contents entry exactly like the title
it names — and then, by the container rule, the whole `<toc>`. A whole structure
disappearing from the report of what was dropped is the failure this count
exists to prevent, so the safe direction was chosen and is pinned by a test.

Read a name in `discarded_elements` as "nothing downstream can get these words
back as a field", not as "the engine never looked at it". On the captured
fixtures the names that appear are the Dublin Core block, `sponsor`,
`cosponsor`, `committee-name`, `action`, `action-date`, `attestation`, `toc`,
`toc-entry` and container numbering.

## Decision: DeltaTrack is a dependency, not a port

See ["DeltaTrack is a pinned dependency, not a
port"](../decisions.md#deltatrack-is-a-pinned-dependency-not-a-port) in
`docs/decisions.md`.

## What upstream already decides, measured at `c636448`

Every row was checked against the pinned revision, most of them as a test in
`tests/test_section_diff.py`.

| Inventory item | Upstream at `c636448` | Where |
| --- | --- | --- |
| §4.4 D1 — CDATA dropped from bodies | **Present.** `extract_text_content` delegates to `_itertext_block_spaced`, which accumulates `element.text` and each child's `tail`; expat reports CDATA as character data, so it reaches the body. | `bill_tree.py:297-321`, via `:328` |
| §4.4 D2 — U+FEFF splits a word in JS, not in Python | **Present, as the Python behaviour.** Not decided explicitly; a BOM inside a text node stays in the body. 0 of 40 sampled files carry one, so this is untested by the corpus. | `bill_tree.py:297-321` |
| §4.4 D3 — `enum` read as `textContent`, one trailing dot | **Present.** Direct `.text`, full `rstrip('.')`. An enum carrying markup does not re-key the section. | `bill_tree.py:929-930` |
| §4.4 D4 — `" "` vs `""` join asymmetry | **Resolved the other way, and this is a behaviour change.** Upstream now joins **both** appropriations text and section text with `" "`. The vendored snapshot joined section text with `""`, which is what every stored `bill_sections.body` was produced with. | `bill_tree.py:1136`, `:1192` |
| §4.4 D5 — amendment chain found only at fixed depth | **Present.** `.//engrossed-amendment-body/amendment/amendment-block`. | `bill_tree.py:175` |
| §4.4 D6 — `getElementsByTagName` filtered by parent | **Present.** Direct-child `findall`. | `bill_tree.py:1507`, `:1554`, `:1563` |
| §4.5 — `$[\d,]+` merges an abutting percentage | **Present.** `\$\d{1,3}(?:,\d{3})+\|\$\d+`. | `amounts.py:47` |
| §4.5 — stateful global-regex `test()` | **Present.** `has_amendment_annotation` is a plain `re.search`. | `amounts.py:114` |
| §4.5 — `JSON.stringify` of a comparator-less sort | **Present.** `Counter(old) != Counter(new)`. | `diff_bill.py:173` |
| §4.5 — hand-rolled LCS emitting no `delete`/`insert` | **Present.** `SequenceMatcher(autojunk=False)` opcodes. | `diff_bill.py:105` |
| §4.3 — three-stage `real_quick_ratio`/`quick_ratio`/`ratio` bail-out | **Present, at the move matrix** rather than at word-segment rendering, which upstream does not have. | `similarity.py:78`, `:97` |
| Decision 7 — `resolution-body` | **Present**, with paired committee-amendment variants refused rather than guessed. | `bill_tree.py:156` |

Two further things upstream has that neither BillTrax copy did: it recovers the
bill's own Congress, type and number correctly for all eight bill types (the
vendored `([A-Z])\.` regex read `H. J. RES. 25` as type `j`), and it carries
`division_key` separately from `division_label` so a display change to the label
cannot silently rewire which sections the diff compares.

### To raise upstream

Not patched locally. Each is a thing BillTrax learned that upstream has no
equivalent for; the file:line is upstream's, at `c636448`. Each claim below
was independently re-derived and measured against that pin — not copied from
BillTrax's own comments — in
[`docs/research/deltatrack-upstream-issues-2026-09-19.md`](../research/deltatrack-upstream-issues-2026-09-19.md),
which also has the suggested issue titles and bodies; they are not repeated
here.

- **A collision-group cap.** BillTrax's `GREEDY_PAIR_GROUP_CAP = 200`
  (`section-diff.ts:26`) bounds the O(p×q) similarity matrix inside one
  match-path group, falling back to body-equality pairing above it. Upstream's
  `_match_collision_group` (`diff_bill.py:803`, dispatched at `:958`) has no
  cap; its retrieval gates each candidate with `real_quick_ratio`/`quick_ratio`,
  which bounds the cost per pair but not the number of pairs. Measured directly
  against upstream's own `match_nodes`: cost holds flat at ~95 µs per pair
  across group sizes 25 through 300 (98.7 µs/pair at 25 per side, 97.1 µs/pair
  at 300), so a single 300-section `match_path` group costs **8.736 s** with no
  ceiling — clean O(N²), each doubling of group size costing ~4×. No existing
  issue covers group-size capping.
- **Hyphen-tolerant matching tokens.** `canonicalToken`
  (`section-diff.ts:104`) folds `cyber-security` and `cybersecurity` to one key,
  which matters when one side of a comparison came from a PDF. Upstream's
  `text_similarity` (`similarity.py:73`) compares raw `split()` tokens at the
  operative line, `similarity.py:75`; its only hyphen handling is the PDF
  page-break rejoin, `PAGE_HYPHEN_RE` (`amounts.py:68`), a different problem.
  How often a hyphen split actually flips a pairing on real bills is not
  measured; upstream's open #706 (different change categories depending on
  whether a bill was compared from XML or PDF) is the symptom class this would
  contribute to.
- **A version keyword and a parsed-tree entry point (one issue).**
  `normalize_bill` (`bill_tree.py:1470`) derives `BillTree.version` from
  `xml_path.stem` after splitting on `_` (`bill_tree.py:1316-1320`), and parses
  the file itself, so a caller holding bytes — as this repository's rule
  requires it to gate first — has to both encode the version into a temp file
  name and parse the document twice. **Upstream's own byte-oriented caller pays
  this cost**: `compare/xml.py:84-96`'s `_build` writes `start.xml`/`end.xml`
  into a `tempfile.TemporaryDirectory` so `normalize_bill` can read them, and
  since neither name contains `_`, `version` comes back `""` on every web
  upload — `_build_from_trees` (`compare/xml.py:39-60`) has to carry
  `start_label`/`end_label` as a separate workaround to put it back. A
  `version` keyword on `normalize_bill`, plus an overload taking an
  already-parsed `ET.Element` root (the diff stage already has one,
  `_build_from_trees` at `compare/xml.py:39`; the parse stage does not), would
  let upstream's own upload path drop both the temp directory and the label
  workaround, and let a byte-holding caller stop parsing each document twice.
  Adjacent: upstream's open #698 (the XML pipeline's intermediate-dictionary
  detour) and open #676 (the epic motivating an outside consumer not needing a
  privileged path).
- **The XML path imports the PDF stack.** `bill_tree.py:8` imports
  `_RUNIN_QUOTED_LINE` and `_match_runin_subsection` from `parsers/pdf_anchors`,
  which imports `parsers/pdf_text`, which imports `pypdfium2` and
  `pypdfium2.raw` at module scope (`pdf_text.py:28-29`). Reading one bill's XML
  therefore pulls a native PDF library into the process — measured at **69 ms**
  for `import deltatrack.bill_tree`, with both modules left resident in
  `sys.modules`. Upstream's own `[project.dependencies]` comment
  (`pyproject.toml:51`) says the engine's dependency list "is what a consumer
  of the engine actually gets," and an XML-only consumer gets more than that.
  The two imported helpers are a compiled regex and a run-in subsection
  matcher, neither PDF-specific, so moving them to a module both parsers
  import — or inlining them in `bill_tree` — would decouple the XML path from
  PDFium without changing either parser's behavior.

#### Already addressed upstream

**The asymmetric-pair guard.** `SECTION_COUNT_THRESHOLD = 10`
(`section-diff.ts:40`) came from a measured 120-second SIGKILL on the 118th
NDAA: an enrolled bill with 988 sections against a public law with 1.
Checked directly against upstream at the pin: `diff_bill.py:1468`'s round 2
does run unconditionally, but it delegates scoring to `move_candidates`
(`similarity.py:97`), which gates every pair on `real_quick_ratio`
(`similarity.py:143`) — a length-ratio bound that prunes extreme asymmetry
hardest, not least. The exact 988×1 shape costs **0.014 s** and yields **0
candidates** before `quick_ratio` or `ratio` ever runs; that gate predates the
pin substantially (present since `4b23e65`, 2026-07-09). BillTrax's own
attribution of the 120 s SIGKILL to "the Python DeltaTrack engine" does not
reproduce against this engine at this pin. The residual population the length
gate cannot prune — many×many at similar lengths — is real and is already
tracked as upstream's open #356 (measured there at 1192×1700 = 5.65 s of
5.84 s total).

#### Not worth raising

- **A body-size cap on inline word segments** (`BODY_CAP = 30_000`,
  `diff_service.py:31`). Upstream has no word-segment rendering at all — a
  grep for `word_segment` across its `src/` returns nothing — so there is no
  feature for the cap to attach to. Revisit only if the feature is proposed
  upstream.
- **The `" "` versus `""` join change (D4).** Accurate as stated (see the D4
  row above), but it describes a consumer-side migration — spicy-docs's own
  stale `bill_sections` rows need a reparse — not an upstream defect;
  upstream's behavior is the intended one. Upstream's open #676 is explicit
  that a downstream consumer's stored-row concerns are being retired from its
  tracker.

## Financial rows carry a claim upstream declines to publish

`financial_changes` has `from_amount`, `to_amount` and `delta` columns. Upstream
removed exactly that pairing from both of its published contracts (#671, #687):
pairing a figure on one side with a figure on the other and publishing the
difference is a claim about an *account*, and an appropriations paragraph mixes
top-line appropriations, sub-allocations, "not to exceed" ceilings and
loan-guarantee commitment limitations with nothing distinguishing them. The
account model that would justify the claim is upstream's #115.

`match_amounts` remains public and tested upstream, so this adapter offers the
pairing in `FinancialChange.pairs` — with `from_amounts`, `to_amounts` and
`amounts_changed` beside it, which are multiset facts that need no account model
to be true. A row means "these two figures sit at the same place in the word
alignment of the two texts". It does not mean they are the same account. Do not
sum `delta` across rows and call it a funding change.

**Two gates make that caveat structural rather than advisory**, because a
populated field nothing reads presents as available, which is what #671/#687
closed by deleting the field outright:

- `diff_sections(..., pair_amounts=True)` is required. Off by default, a caller
  takes the account claim by name.
- Even then, a section whose `amounts_changed` is false contributes no rows.
  Before this gate, a self-diff of the appropriations fixture produced eight
  rows of `delta` 0 — findings that were really just "each figure equals
  itself".

The pairing is also the one cost this adapter adds that upstream's published
path does not pay: `match_amounts` runs `SequenceMatcher(autojunk=False)` over
both bodies' words, O(w²) per section with the popular-element heuristic
switched off — that heuristic is what would drop a repeated `$1,000` out of the
alignment. Measured on one section pair, 8,000 words of distinct wording pairs
in 0.007 s, but 8,000 words of repetitive appropriations phrasing takes 0.46 s
and 16,000 words 1.88 s. Repetitive is what appropriations text *is*, so the two
gates are what keep this off the common path.

One column is filled that BillTrax never filled: `label` carries the section
heading. `financial.ts` set it to `""` at every construction site, so the column
held nothing in every row ever written.

## Fixtures

Captured publisher bytes are in
[`tests/fixtures/govinfo_bills/`](../../tests/fixtures/govinfo_bills/README.md),
including one complete unchanged resolution. The division, appropriations and
two-stage shapes are **constructed**, because no sample whose bytes this
repository retains carries them; see
[their README](../../tests/fixtures/congress_bill_tree/README.md) for what each
one reproduces and from which measurement.
