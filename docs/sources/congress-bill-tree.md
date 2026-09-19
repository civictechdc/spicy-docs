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

**Status: decided here, for a maintainer to move into `docs/decisions.md`.**

SpicyDocs depends on `civictechdc/DeltaTrack`, pinned by commit sha in
`[tool.uv.sources]`. BillTrax's `submodules/DeltaTrack` and its TypeScript fork
(`src/lib/bill-tree.ts`, `financial.ts`, `diff.ts`, `section-diff.ts`'s fallback
core, `python-diff.ts`, `scripts/diff_service.py`) **are to be deleted**.

The reason is the measurement, not a preference.
[The value inventory](../research/billtrax-value-inventory-2026-09-19.md) §4
recommended a port because the vendored directory was "not a git submodule",
carried no pin, and had no upstream remote to pin *to* — its own git history was
BillTrax's. That was true of the directory and false of the project. The
canonical repository has since moved to the same Civic Tech DC organisation as
SpicyDocs and SpicyRegs, and at `c636448` (2026-09-13) it is:

- an installable package (`deltatrack` 0.1.0, hatchling, `src/deltatrack`) whose
  engine dependency is `pypdfium2` alone — not the `httpx`/`python-dotenv` set
  the vendored `pyproject.toml` declared for a fetcher it did not contain;
- 12,479 lines across 25 modules, against the vendored snapshot's 2,846;
- covered by 120 test files and a corpus. The suite was run once at the pinned
  revision through its own runner (`uv sync`, then
  `uv run pytest -q -m "not browser and not network"`): **3,822 passed, 34
  skipped, 15 xfailed, 0 failed, 67 s**. The 34 skips print their reasons; they
  are corpus shells, baseline-regeneration modes, and three gitignored local
  fixtures;
- already carrying every divergence and bug the inventory told this port to fix
  by hand, plus the `resolution-body` gap it told this port to close.

So the port's premise was a stale snapshot. Porting 1,439 lines by hand, to
reach a place 12,479 maintained lines already occupy, preserves effort and
nothing else.

A git pin rather than a PyPI range because nothing is published to PyPI yet:
`deltatrack` is an unclaimed name on the index, so a version specifier would
resolve to nothing at best and to an unrelated package at worst. Move the pin to
a release when upstream publishes one, and drop the `[tool.uv.sources]` entry at
that point.

## What upstream already decides, measured at `c636448`

Every row was checked against the pinned revision, most of them as a test in
`tests/test_section_diff.py`.

| Inventory item | Upstream at `c636448` | Where |
| --- | --- | --- |
| §4.4 D1 — CDATA dropped from bodies | **Present.** `extract_text_content` walks `itertext`; expat reports CDATA as character data, so it reaches the body. | `bill_tree.py:328` |
| §4.4 D2 — U+FEFF splits a word in JS, not in Python | **Present, as the Python behaviour.** Not decided explicitly; a BOM inside a text node stays in the body. 0 of 40 sampled files carry one, so this is untested by the corpus. | `bill_tree.py:328` |
| §4.4 D3 — `enum` read as `textContent`, one trailing dot | **Present.** Direct `.text`, full `rstrip('.')`. An enum carrying markup does not re-key the section. | `bill_tree.py:896` |
| §4.4 D4 — `" "` vs `""` join asymmetry | **Resolved the other way, and this is a behaviour change.** Upstream now joins **both** appropriations text and section text with `" "`. The vendored snapshot joined section text with `""`, which is what every stored `bill_sections.body` was produced with. | `bill_tree.py:1136`, `:1192` |
| §4.4 D5 — amendment chain found only at fixed depth | **Present.** `.//engrossed-amendment-body/amendment/amendment-block`. | `bill_tree.py:175` |
| §4.4 D6 — `getElementsByTagName` filtered by parent | **Present.** Direct-child `findall`. | `bill_tree.py:1507`, `:1554`, `:1563` |
| §4.5 — `$[\d,]+` merges an abutting percentage | **Present.** `\$\d{1,3}(?:,\d{3})+\|\$\d+`. | `amounts.py:47` |
| §4.5 — stateful global-regex `test()` | **Present.** `has_amendment_annotation` is a plain `re.search`. | `amounts.py:114` |
| §4.5 — `JSON.stringify` of a comparator-less sort | **Present.** `Counter(old) != Counter(new)`. | `diff_bill.py:173` |
| §4.5 — hand-rolled LCS emitting no `delete`/`insert` | **Present.** `SequenceMatcher(autojunk=False)` opcodes. | `diff_bill.py:74` |
| §4.3 — three-stage `real_quick_ratio`/`quick_ratio`/`ratio` bail-out | **Present, at the move matrix** rather than at word-segment rendering, which upstream does not have. | `similarity.py:78`, `:97` |
| Decision 7 — `resolution-body` | **Present**, with paired committee-amendment variants refused rather than guessed. | `bill_tree.py:156` |

Two further things upstream has that neither BillTrax copy did: it recovers the
bill's own Congress, type and number correctly for all eight bill types (the
vendored `([A-Z])\.` regex read `H. J. RES. 25` as type `j`), and it carries
`division_key` separately from `division_label` so a display change to the label
cannot silently rewire which sections the diff compares.

### To raise upstream

Not patched locally. Each is a thing BillTrax learned that upstream has no
equivalent for; the file:line is upstream's, at `c636448`.

- **A collision-group cap.** BillTrax's `GREEDY_PAIR_GROUP_CAP = 200`
  (`section-diff.ts:26`) bounds the O(p×q) similarity matrix inside one
  match-path group, falling back to body-equality pairing above it. Upstream's
  `_match_collision_group` (`diff_bill.py:803`) has no cap; its retrieval gates
  each candidate with `real_quick_ratio`/`quick_ratio`, which bounds the cost per
  pair but not the number of pairs.
- **An asymmetric-pair guard.** `SECTION_COUNT_THRESHOLD = 10`
  (`section-diff.ts:40`) came from a measured 120-second SIGKILL on the 118th
  NDAA: an enrolled bill with 988 sections against a public law with 1 ran the
  whole removed×added matrix against a single huge blob. Upstream's round 2
  (`diff_bill.py:1468`) runs unconditionally.
- **A body-size cap on inline word segments.** `BODY_CAP = 30_000`
  (`diff_service.py:31`). Upstream has no word-segment rendering at all, so this
  has no home there yet — worth raising with the feature rather than alone.
- **Hyphen-tolerant matching tokens.** `canonicalToken`
  (`section-diff.ts:104`) folds `cyber-security` and `cybersecurity` to one key,
  which matters when one side of a comparison came from a PDF. Upstream's
  `similarity.py:73` compares raw `split()` tokens; its only hyphen handling is
  the PDF page-break rejoin in `amounts.py:59`, a different problem.
- **The `" "` versus `""` join change (D4).** Upstream moved section text to a
  space join. Anyone holding `bill_sections` rows produced by the vendored
  snapshot has bodies that will not compare equal to freshly parsed ones. Worth
  a note upstream that the change is observable in stored output, and worth a
  reparse here before any such rows are trusted.
- **A version that is not read from a file name.** `normalize_bill`
  (`bill_tree.py:1470`) derives `BillTree.version` from `xml_path.stem` after
  splitting on `_`. A caller holding bytes has to encode the version into a
  temporary file name to pass it, which this adapter does. A keyword argument
  would remove the temp file from every byte-oriented caller, upstream's own
  `compare/xml.py:_build` included.
- **An entry point that takes a parsed tree.** The same function parses the file
  itself, so a caller that must gate the bytes first — as this repository's rule
  requires — parses the document twice. `normalize_bill` accepting an
  `ET.Element` root, with the path form calling it, would close both this and
  the point above.
- **The XML path imports the PDF stack.** `bill_tree.py:8` imports from
  `parsers/pdf_anchors`, which loads `pypdfium2`. Reading one bill's XML
  therefore pulls a native PDF library into the process and emits its SWIG
  deprecation warnings. Upstream's own `[project.dependencies]` comment says the
  engine's dependency list "is what a consumer of the engine actually gets", and
  a consumer who only reads XML gets more than they asked for.

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
