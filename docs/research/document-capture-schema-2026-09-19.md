# A document capture schema for the platform

*2026-09-19. Design record for the `DocumentCapture v1` shape. Reviewed the
same day by an architecture review of both branches and a visual review of the
six profiles against the print rendition of each family's document; this
record is the version after those reviews, and says at each point what they
changed. The two reviews are summarized under "What the reviews changed" and
the visual review is retained in full beside this file.*

## The home

The parent schema lives in Rulespec and the family profiles live in
SpicyDocs. The owner ruled this on 2026-09-19, and the ruling is recorded in
[rulespec `docs/decisions.md`](../../../rulespec/docs/decisions.md) under
that date: DocSpec has become a processing pipeline only, SpicyDocs handles
acquisition and parsing, and the reusable capture shape is a parent schema
structure in Rulespec composed per document family in SpicyDocs. The parent
is
[`rulespec/release-records/schemas/document-capture-v1.schema.json`](../../../rulespec/release-records/schemas/document-capture-v1.schema.json)
with its composition rule in
[`rulespec/spec/document-capture.md`](../../../rulespec/spec/document-capture.md);
the six profiles are
[`src/spicy_docs/schemas/document_capture/1.0/profiles/`](../../src/spicy_docs/schemas/document_capture/1.0/),
each `allOf`-composing the parent and pinning it by digest. Three Rulespec
files are vendored beside them and pinned in `PINS.json`: the parent, the
profile meta-schema that states the composition rule as data, and
`rulespec_artifacts.document_capture`, the one implementation of the
invariants JSON Schema cannot see. All three ship in the `rulespec-artifacts`
wheel's `_data` and as a module; the wheel pinned here predates them, so they
are copies with a digest test that turns into a byte-equality test the moment
the wheel carries them, and the copies go away at that bump. That is the
architecture review's answer to the first of the questions left to the user
below: ship data, delete code. The boundary this
respects is the one the 2026-08-02 Rulespec decision drew: Rulespec owns
generic container mechanics and the `SourceFragment` vocabulary that every
leaf binds to, and builds no document pipeline; the converters that produce
captures are SpicyDocs code, beside the readers, extractors and
reconstruction they reuse.

For the record, the ledgers read differently before the ruling. The
stack-level [`DECISIONS.md`](../../../DECISIONS.md) assigns DocSpec the
platform source catalog under RefSpec REF-048, and rulespec's 2026-08-02
entry extends that to "document parsing, exact captured text, durable
structural passages, and model-input segmentation", forbidding a parallel
pipeline in Rulespec; the 2026-09-06 entry then lets Rulespec segment by
meaning for its standalone workflow. On that reading the user's lean toward
Rulespec conflicted with REF-048 for "durable structural passages". But
DocSpec never defined such a passage: `grep -rn passage DocSpec/docs
DocSpec/src` finds only the phrase-matching processor, and the
`structuralNode` record planned in DocSpec decision 0001 (row 7, with
`structuralParentId`, `depth`, `ordinal` and `headingPath`) is unimplemented
as of 2026-09-19 (`bounded_segmentation.py` carries a `_heading_path` helper
and nothing else). The shapes that do exist are SpicyDocs'
`reconstruction/evidence.py` and DocSpec's `Segment`, and both are reused
below. The ruling resolves the conflict by assigning the shape to Rulespec
and the parsing to SpicyDocs; this document keeps that reading as history and
follows the ruling.

## What is reused, what is new, and why

Where an existing shape already does part of this, the capture binds to it
or carries it. Where it defines something new, the reason the existing one
could not carry it is stated.

| Need | Reused from | How | New, and why |
| --- | --- | --- | --- |
| Address a leaf so any product can cite it | rulespec `rkaf:SourceFragment` (`spec/rkaf-core.md` §4.2; `compiled/json-schema/core/source-fragment.schema.json`, vendored) | Every leaf renders as two fragments: one into the capture's text stream in `rkaf:unicode-codepoint`, which is the unit the carrier-local URN fixes, so every contiguous leaf gets `urn:rkaf:fragment:…` for free; one into the publisher's artifact in its own coordinates — a namespace-agnostic `oa:XPathSelector`, one `rkaf:utf8-byte` position selector **per byte run**, an RFC 8118 `page=N&viewrect=` `oa:FragmentSelector` **in points** for a page region, `rkaf:uslm-section` for the enclosing USLM identifier. `rkaf:sourceArtifactDigest` and `rkaf:fragmentContentDigest` are the artifact and span digests the capture already carries | Nothing. The capture is a producer of fragments, never a redefinition of them; `EvidenceBinding` stays with whichever product makes an assertion. The three emphasized rules are the architecture review's: the first draft emitted a prefixed XPath that selected nothing, a byte hull that spanned markup, and permille labelled RFC 8118 |
| Evidence coordinates | DocSpec `domain/content.py` `EvidenceCoordinate` (`coordinate_system`, `source_digest`, half-open `start`/`end`, `page`, `region`) and `EvidenceMapping` (representation range to captured-file evidence, with a named `transformation`); decision 0001's `rendition-utf8-byte` and `rendition-byte` systems | A span's `source` is an `EvidenceCoordinate` in DocSpec's terms: `utf8-byte` over the captured file with a `literal` flag, or `page-region` with a page and box. A span with `literal: true` is DocSpec's identity byte-slice transformation; one with `literal: false` resolves to its whole run, DocSpec's own rule for entity-decoded text (`docs/shared-source-readers.md`) | The page box. Decision 0001 designed and dropped a `rendition-page-region` system "until a coordinate-emitting extractor is chosen, permille rule included"; SpicyDocs `extraction.model.Box` now emits one, so the capture carries the dropped design: integer permille, so the value is admissible to canonical identity JSON |
| Text-bearing units with byte spans | SpicyDocs `reading/markup.py` `MarkupEvent` (`byte_start`, `byte_end`, `is_literal`) | One span per text event; the leaf's enclosing element gives `source.path`, `source.element`, `source.attributes` and the element's byte range | Nothing |
| Reconstructed structure with the rule that placed it | SpicyDocs `reconstruction/evidence.py` (`EvidenceBlock`, `DocumentNode` with `evidence_refs` and `decision`, `UnresolvedRegion`, `ID_ORIGIN = "generated"`) and `serialize.py`'s sidecar `SourceMap` keyed by XML path | A reconstructed node is a `DocumentNode`: `decision`, `reviewStatus`, `designation` from `marker`, `derived.text` from the profile's assembled `text`, `ext.xmlPath` from the source map, unresolved regions carried as they are | The partition. `DocumentNode.evidence_refs` lets a parent and its children share one block (a section and its number and subject split one printed line); the capture splits that block into spans so each belongs to exactly one node, and a node with both its own lines and children keeps its lines in an implicit first `text` child, the way a markup container does |
| PDF pages, lines, styles and tables | SpicyDocs `extraction/model.py` (`PageResult`, `TextBlock`, `Box`, `TableObservation` with `cells` and `cell_boxes`) through `reconstruction.evidence.evidence_from_pages` | `page` and `line` nodes; `style` on spans from the extractor's spans; `cell` with `row`, `column`, `header` and a `source.box` for a detected table. The extractor document itself is `rendition.intermediate`, never the `artifact` | The page size. `evidence_from_pages` keeps each box in permille of the displayed page and drops the size that produced it, so a retained sidecar pinned to the PDF digest carries `pageSize` in points onto each `page` node; without it a permille box cannot be converted to the unit RFC 8118 names. The `TableObservation` route is still unexercised: the ruled table these six do contain is a `<pre>` text table, read by the committee-report rule, not by the extractor |
| Bill structure | `sources/congress/bill_tree.py` over the pinned DeltaTrack `parse_bill_tree` (`BillNode.match_path`, `display_path`, `element_id`, `section_number`) and its `discarded_elements` inventory | Structure is read from the publisher's elements; each element the engine flattened is joined on its id and carries the engine's paths in `ext`; engine nodes with no element (its synthesized front-matter nodes) are listed as unjoined and raised as issues | Nothing; DeltaTrack is a dependency (`docs/decisions.md`, "DeltaTrack is a pinned dependency") and the capture does not restate its tree |
| Law identity | `sources/govinfo/uslm.py` `validate_public_law_xml` and `UslmMetadata` | The profile's document `ext` and the artifact's `rkaf:uslm` identifier | Nothing |
| Federal Register body | `sources/federal_register/body_xml.py` locators; the body preference in `sources/govinfo/bodies.py` (`xml, uslm, htm, txt, pdf`) and the lesson "publish the XML body pointer, not the HTML one" | The XML rendition is the one captured; `derivation` records that its structure is native | Nothing |
| Report text blocks | `sources/agency_reports/report_blocks.py` (blank-line and header-pattern blocks with offsets) and `extraction/gpo_normalize.py` | The committee-report converter uses the same blank-line rule over the `<pre>` run, with exact byte offsets where the run is literal | Nothing new in rule; the capture keeps the page marker, banner and rule lines as nodes rather than stripping them, because stripping is what `gpo_normalize` does after evidence gates it, and a capture is the evidence |
| Anomalies recorded, not guessed | RefSpec `federal_register_thesaurus_2025.py` (unresolved and ambiguous statuses kept as data) | Empty elements become leaves with an `empty-leaf` issue; engine nodes without elements become issues; unplaced blocks become `unresolved` regions | Nothing |
| A closed, pinned schema | DocSpec decision 0001 row 13 (schemas ride inside the bundle, digest-pinned) and rulespec's digest conventions (`platform-artifacts.md`) | The parent is vendored into SpicyDocs and pinned in `PINS.json`; every capture records the parent and profile pins | Nothing |

## The shape

A capture is one plain JSON document. Trimmed from `bills-119hjres25enr.capture.json`:

```json
{
  "recordType": "DocumentCapture", "captureVersion": 1,
  "schema": {"$id": "https://rulespec.org/schemas/releases/document-capture-v1.schema.json", "sha256": "a090fbc8…"},
  "capture": {"id": "urn:document-capture:sha256:…", "capturedAt": "2026-09-19T…", "idOrigin": "generated", "idScheme": "document-order"},
  "artifact": {"iri": "urn:document-capture:artifact:sha256:…", "sha256": "…", "byteSize": 2751, "mediaType": "application/xml",
               "locator": {"url": "https://www.govinfo.gov/content/pkg/BILLS-119hjres25enr/xml/BILLS-119hjres25enr.xml", "path": "tests/fixtures/govinfo_bills/text-119hjres25enr.xml", "publisher": "GovInfo", "publisherId": "BILLS-119hjres25enr"},
               "retrievedAt": "2026-09-12",
               "identifiers": [{"scheme": "rkaf:hash-sha256", "value": "sha256:…"}, {"scheme": "rkaf:partner-defined", "value": "govinfo:BILLS-119hjres25enr"}]},
  "rendition": {"kind": "xml", "spanDefaults": {"coordinateSystem": "utf8-byte", "literal": true},
                "textStream": {"iri": "urn:document-capture:text-stream:sha256:…", "sha256": "…", "codePoints": 1335,
                "normalization": {"id": "markup-character-data", "statement": "The decoded character data of every text event … inside the root element …", "reversible": true}}},
  "converter": {"id": "spicy-docs/tools/analysis/document_capture.py#bill-xml", "version": "1",
                "implementation": {"repository": "spicy-docs", "revision": "…", "fileSha256": "…"},
                "dependencies": [{"name": "python", "version": "3.12.13"}, {"name": "spicy-docs", "version": "0.21.2"}, {"name": "deltatrack", "version": "0.1.0"}]},
  "profile": {"name": "bill-xml", "version": "1", "schema": {"$id": "urn:spicy-docs:schema:document-capture:1.0:profile:bill-xml", "sha256": "…"},
              "ext": {"rootTag": "resolution", "bodyTags": ["resolution-body"], "stage": "Enrolled-Bill", "deltatrack": { … }, "discardedElements": { … }}},
  "nodes": [
    {"id": "n0001", "kind": "document", "parent": null, "ordinal": 0, "depth": 0, "derivation": "native", "evidence": ["s0001", "s0002", …], "source": {"coordinateSystem": "xml-node-path", "path": "/resolution[1]", "element": "resolution", "attributes": { … }, "start": 150, "end": 2748}},
    …,
    {"id": "n0021", "kind": "paragraph", "parent": "n0019", "ordinal": 1, "depth": 3, "derivation": "native",
     "text": "That Congress disapproves the rule submitted by the Internal Revenue Service relating to …",
     "evidence": ["s0038", "s0039", "s0040"], "source": {"coordinateSystem": "xml-node-path", "path": "/resolution[1]/resolution-body[1]/section[1]/text[1]", "element": "text", "start": 2164, "end": 2469}}
  ],
  "evidence": [
    …,
    {"id": "s0039", "start": 1040, "end": 1140, "exact": "Gross Proceeds Reporting by Brokers That Regularly Provide Services Effectuating Digital Asset Sales",
     "source": {"start": 2266, "end": 2366}, "tags": ["quote"]}
  ],
  "unresolved": [], "issues": [{"code": "deltatrack-node-without-element", "detail": "front-matter front-matter-masthead is synthesized by the engine, not an element"}, …]
}
```

Three things in that sample are what the 2026-09-19 architecture review
changed. `artifact` is the publisher's bytes and nothing else, so a PDF
capture names the PDF here and its extractor output in
`rendition.intermediate`; a span states only what differs from
`rendition.spanDefaults`, which is why `s0039` carries two numbers rather
than five; and a span no longer restates a `sha256` a validator recomputes
from its own `exact`. `retrievedAt` is a date because the fixture README that
retained these bytes records a day, and inventing a midnight would claim a
precision nobody has.


The core vocabulary of node kinds is closed: `document`, `frontMatter`,
`body`, `backMatter`, `metadata`, `title`, `division`, `section`,
`heading`, `paragraph`, `list`, `item`, `quote`, `table`, `row`, `cell`,
`note`, `footnote`, `figure`, `signature`, `page`, `line`, `pageNumber`,
`runningHead`, `printFooter`, `text` and `label`. A family names anything
else as `<profile.name>:<Kind>` and its profile enumerates those. The
publisher's own element name always travels in `source.element`, so a
generic `text` leaf loses nothing: the capture says what the publisher
called it and declines to say more.

### The constraints and their reasons

| Constraint | Reason | Where it is enforced |
| --- | --- | --- |
| Structure only, never legal meaning | Capture is not interpretation (`AGENTS.md`: SpicyDocs acquires facts and evidence; downstream interprets). A node kind that meant "requirement" would be an extraction result wearing a capture's clothes | The closed core enum; the profile composition rule forbids new fields; `check_invariants` refuses a kind outside the core or the profile namespace |
| Provenance per document (artifact digest, rendition, locator, retrieval time, converter and version) and per node (`derivation`) | A capture is reproducible evidence only if its producer is named (DocSpec core model §5.2 retention contract); one document can mix native and reconstructed structure, so `derivation` is per node, not per document | Required fields in the parent; the converter records its git revision and file digest |
| Per-span coordinates and content digests | A citation must survive the artifact being replaced under it (`rkaf-core.md` §4.2: `sourceArtifactDigest` and `fragmentContentDigest` answer different questions) | `Span.source` required; `Span.sha256` is derivable and optional, and the invariant validator recomputes it and refuses a stated digest that differs |
| Unresolved regions survive with an issue | "Nothing is dropped" is the reconstruction package's rule and the RefSpec thesaurus reader's; a dropped run is a silent claim that the text was not there | `unresolved` required; a span owned by nothing fails `check_invariants` |
| Stable generated ids, marked as generated | The reconstruction package's `ID_ORIGIN` rule: no consumer may read a minted id as a publisher identifier; document-order ids are deterministic for one input through one converter version | `capture.idOrigin` and `idScheme` constants in the parent |
| Round trip under a stated, reversible normalization | A capture that cannot reproduce its rendition's text is a summary, not evidence. The normalization is stated per rendition kind and the check is re-derived with a second parser (the doctrine's "different tool family") | `textStream.normalization` required; `check_invariants` checks the partition; `measure` and `tests/test_document_capture.py` re-derive the stream with lxml (libxml2) for XML, the standard library's HTMLParser for HTML, and a plain JSON rejoin for the two retained extractor documents |
| One core, family parts in a declared `profile` block | A per-family branch in the core would make the sixth family a schema change; a profile is a file | `profile` required; the profile meta-schema refuses a profile that touches any parent field but `profile.*`, node `kind` in its namespace and node `ext`, and refuses it as data rather than by whitelist |
| Plain JSON, JSON Schema draft 2020-12, pinned by digest | A shape a consumer can validate with no product checkout (DocSpec 0001 row 13) | `schema` and `profile.schema` pins; `PINS.json`; both repositories' tests |
| Two coordinate units, each declared | The lesson "two products' identifiers never compare equal by accident": DocSpec counts UTF-8 bytes, rkaf's carrier-local URN counts code points. The stream is in code points and every rendition selector declares its unit | `Span.start`/`end` in code points; `source.coordinateSystem` per span; `rkaf:coordinateSystem` on every position selector |
| Containers carry no citable text | A citation lands on a leaf, so a leaf's `text` is the whole of what its spans say and a container's spans are whitespace or separators; a unit with its own lines and children keeps its lines in a first `text` child | The invariant validator: a node with children that carries `text`, or that owns non-whitespace text of its own, fails |
| Integer permille boxes | Rulespec's canonical identity JSON refuses floats; a capture is not an identity value, but its coordinates should be admissible to one | `Box` in the parent |

## The composition rule

A profile is `allOf: [{"$ref": <parent $id>}, <own narrowing>]`, carries
`x-parent` with the parent's `$id` and byte digest, and in its own narrowing
touches only `profile.name` (a constant), `profile.version` (a constant),
`profile.ext` (its closed document block), node `kind` and node `ext`. Its
node narrowing is exactly three clauses: an `if`/`then` binding kinds in its
own namespace to its enumerated list, a `not` pattern refusing every other
namespace's prefix, and its closed per-node `ext` block.

**The rule is data.** It is
[`document-capture-profile-v1.schema.json`](../../src/spicy_docs/schemas/document_capture/1.0/document-capture-profile-v1.schema.json),
a meta-schema closed at every level, validated with the `jsonschema` both
repositories already have. Only two bindings stay in code, because JSON
Schema cannot read one part of a document from another: the `x-parent` digest
is the parent's bytes, and the kind pattern, every enumerated kind and the
refusal pattern all carry the profile's own name. That code is Rulespec's
(`rulespec_artifacts.document_capture.check_profile_bindings`), not a second
copy here.

The first draft had a hand-written whitelist over `properties` keys in both
repositories. The architecture review ran seven tightenings a profile must not
make — `else` on a node clause, `required` or `additionalProperties: false`
or `not` on the narrowing, `required` on `profile`, a `then` loosening `kind`
to any string, `minItems` on `nodes` — and all seven passed both copies, five
of them changing what a capture validated as; a kind in another family's
namespace (`other:Foo`) validated cleanly against parent and profile
together. The two copies had already drifted from each other in signature.
Each probe is now a negative control in both repositories, and the foreign
prefix is refused by the profile itself rather than only by the invariant
checker.

## The families

| Profile | Rendition | Structure from | Family kinds | What it cannot see |
| --- | --- | --- | --- | --- |
| `uslm-law` | USLM XML | The publisher's elements: `section`, `subsection`… are `section` and `paragraph`, `num` is the `label` whose text becomes the parent's `designation`, `quotedContent` is a `quote`, `page` is `pageNumber` | `amendingAction`, `sidenote`, `toc`, `enactingFormula`, `sourceCredit` | Inline markup (`ref`, `quotedText`, `date`) folds into a leaf's spans as `tags`; a `page` marker inside a leaf folds too |
| `bill-xml` | Bill DTD XML | The publisher's elements; each element DeltaTrack flattened carries the engine's paths in `ext`, joined on the element id | `attestationGroup`, `toc` | The engine's three synthesized front-matter nodes have no element and are recorded as unjoined plus issues; `discarded_elements` is carried in `profile.ext` |
| `committee-report-html` | GovInfo HTML | The `<title>` and the one `<pre>` run, split into blank-line blocks. A block is a ruled column-aligned table, a centred-capitals or record-vote heading, or a `paragraph`, `pageNumber` (`[[Page N]]`), `banner` or `rule`; every block is `derivation: markup` and names the rule that placed it | `preformatted`, `banner`, `rule`, `heading` | Section nesting: the headings are flat, because the `<pre>` marks depth only by centring. A block ruled top and bottom whose rows do not split into its header's columns is refused and kept as text with a `table-columns-ambiguous` issue |
| `federal-register-xml` | FR XML | The publisher's elements: preamble blocks are `section`s with a level-1 `heading`, `HD SOURCE=HDn` gives heading levels, `GPOTABLE`/`BOXHD`/`ROW`/`CHED`/`ENT` give `table`/`row`/`cell` with `cell.row`, `cell.column`, `cell.header`, `FTNT` is `footnote`, `PRTPAGE` is `pageNumber` | `listOfSubjects`, `regText` | A `PRTPAGE` inside a `P` folds into the paragraph; `LI` inside a cell head is a line break, kept as a tag |
| `cfr-reconstruction` | Extracted PDF lines | `spicy_docs.reconstruction`'s nodes with `decision`, `reviewStatus`, `derived.text` and the serialized granule's `xmlPath`; every block is a span with page, box and style | `flushParagraph`, `cita`, `blank`, `partHeading`, `contents`, `authority`, `sourceNote` | Nothing the reconstruction did not: a paragraph interrupted by a page break is one non-contiguous leaf |
| `slip-opinion-pdf` | A slip opinion PDF through the retained extractor document | Pages and lines, plus the opinion division: the designator the print repeats in the running-head band (`Per Curiam`, `JACKSON, J., dissenting`) opens a container, the opening formula on that page must agree with it, and the printed page number is read from the same band | `syllabus`, `opinion`, `perCuriam`, `concurrence`, `dissent` | Paragraphs, the masthead, the docket line and the caption: the first-line indent that marks a paragraph (273 against 255 permille) is visible but unmeasured, so the body stays `line` nodes. A page whose two signals disagree, or whose designator is missing, records an issue and keeps the designator's answer |

## The worked conversions

Six documents, one converter, one shape. Produced by
`tools/analysis/document_capture.py`, retained in
[`document-capture-schema-2026-09-19/`](document-capture-schema-2026-09-19/README.md)
beside their input pins, re-checked offline by `tests/test_document_capture.py`
(61 tests, one skipped until the wheel bump). The receipt for the five keyless
requests is `~/Work/corpora/supply-2026-09-02/receipts/document-capture-schema-2026-09-19/`.

| Document | Family | Rendition | Artifact bytes | Capture bytes | Nodes | Leaves | Empty leaves | Non-contiguous leaves | Spans | Unresolved | Issues | Code points | Partition digest | Independent derivation | Schema, profile, invariants, fragments | Seconds |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |
| `plaw-119publ1` | `uslm-law` | xml | 23,379 | 141,485 | 321 | 216 | 0 | 0 | 325 | 0 | 1 | 8,660 | match | match, lxml.etree (libxml2) itertext | all pass | 0.0016 |
| `bills-119hjres25enr` | `bill-xml` | xml | 2,751 | 18,638 | 26 | 18 | 3 | 0 | 45 | 0 | 6 | 1,335 | match | match, lxml.etree (libxml2) itertext | all pass | 0.0003 |
| `crpt-119hrpt1` | `committee-report-html` | html | 13,953 | 127,779 | 217 | 170 | 0 | 0 | 625 | 0 | 1 | 13,900 | match | match, html.parser.HTMLParser(convert_charrefs=True) handle_data | all pass | 0.0011 |
| `fr-2026-19200` | `federal-register-xml` | xml | 10,224 | 62,503 | 76 | 59 | 2 | 0 | 209 | 0 | 5 | 8,758 | match | match, lxml.etree (libxml2) itertext | all pass | 0.0005 |
| `cfr-2025-title30-vol3-sec716-2` | `cfr-reconstruction` | pdf | 157,908 | 186,831 | 87 | 71 | 0 | 2 | 721 | 0 | 0 | 12,694 | match | match, json: evidence blocks rejoined by page | all pass | 0.0012 |
| `scotus-26a274_l537` | `slip-opinion-pdf` | pdf | 66,165 | 124,689 | 168 | 160 | 0 | 0 | 473 | 0 | 2 | 8,024 | match | match, json: evidence blocks rejoined by page | all pass | 0.0008 |

Reading the table:

- **Artifact bytes** are the publisher's own, which for the two PDF families
  means the PDF (157,908 and 66,165) rather than the extractor document the
  first draft put in that slot. The extractor documents (101,921 and 73,533)
  are `rendition.intermediate`, and the text stream is derived from them.
- **Partition digest** is the internal check: sha256 over the concatenated
  spans equals `textStream.sha256`. On its own that is a formatting
  assertion, since the converter wrote both sides.
- **Independent derivation** is the check that can fail: the stream is
  re-derived from the retained document by a different implementation of the
  stated normalization. For XML that is libxml2 through `lxml.etree`
  against the reader's expat; it matched on all three XML documents,
  including the USLM file with eight processing instructions and a comment
  inside the root. For HTML it is the standard library's `HTMLParser` with
  its own character-reference decoding; libxml2's HTML parser could not serve
  here because it drops inter-element whitespace, and a witness that
  normalizes cannot witness a whitespace-exact stream. For the two PDF
  families the re-derivation is a plain JSON rejoin of the retained blocks,
  which checks the partition and the separators and nothing about the
  extractor: the round trip is over the extractor document, never the PDF
  bytes, and the capture says so in its normalization statement.
- **Empty leaves** are the publisher's empty elements (`dc:date`,
  `current-chamber` and `enum` in the enrolled resolution; the `PRTPAGE`
  marker and an empty `P` in the notice). The rule is now one rule for every
  family: any leaf whose text is empty or whitespace carries an `empty-leaf`
  issue, whether the publisher wrote an empty element or an extractor emitted
  a line of spaces. In the slip opinion the 77 whitespace-only extractor
  lines are no longer leaves at all — their text belongs to the page
  container, the way a separator does — which is why that capture has 160
  leaves where the first draft had 237.
- **Non-contiguous leaves** are the two reconstructed CFR paragraphs the
  fixture README documents as carrying a page break; the fragment rendering
  gives them two position selectors and no carrier-local URN.
- **Issues** are what each document says about itself: three DeltaTrack nodes
  with no element and three empty elements in the resolution, five empty
  elements in the notice, GovInfo's repeated `139 STAT. 4` page label in the
  law, and two slip-opinion pages whose printed number the print sets on the
  running head's own baseline.
- **Seconds** are the tree-and-partition build alone. `Elem.has_structure` is
  memoized, the Federal Register cell geometry reads prebuilt indices and the
  bill join is a set, so nothing here is superlinear; the shared-block split
  scans one printed line per child.

### Where a capture's bytes go

The first draft of this record said the size was "every span repeats its
text, its digest and its coordinates, and every leaf repeats its spans'
text". That was wrong, and the architecture review decomposed it: the text
repetition was 7.5%, the indentation 23%, and about half the total was
derivable or constant. Four changes followed — compact serialization, hoisting
the span source fields that are constant for a document into
`rendition.spanDefaults`, dropping the span `sha256` a validator recomputes,
and making leaf `text` optional in the parent — and the captures are 26% to
48% smaller than the first draft's. Each row below is the same document
re-serialized with one thing removed, measured by
`size_decomposition` in the converter rather than asserted here.

| Document | Bytes now | Indenting would add | Exact text | Bytes per byte of text | Leaf `text` | Span `id` + `end` | Span `source` | Node `source` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `plaw-119publ1` | 141,485 | 48,278 | 8,831 | 16.0x | 10,910 | 10,400 | 11,701 | 49,568 |
| `bills-119hjres25enr` | 18,638 | 5,866 | 1,339 | 13.9x | 1,485 | 1,404 | 1,549 | 4,372 |
| `crpt-119hrpt1` | 127,779 | 50,465 | 13,900 | 9.2x | 14,637 | 20,148 | 22,190 | 8,327 |
| `fr-2026-19200` | 62,503 | 20,882 | 8,785 | 7.1x | 7,674 | 6,657 | 10,409 | 10,410 |
| `cfr-2025-title30-vol3-sec716-2` | 186,831 | 74,893 | 12,734 | 14.7x | 13,654 | 23,132 | 45,058 | 3,219 |
| `scotus-26a274_l537` | 124,689 | 57,887 | 8,124 | 15.3x | 9,395 | 15,002 | 29,306 | 14,295 |

What is left is not waste. A capture is 7 to 16 times its own text because it
carries, per span, where that text sits in the artifact, and per node, the
publisher's element path and attributes. Node `source` is the largest single
item for the markup families (35% of the USLM capture) and span `source` for
the PDF families (24% of the slip opinion), which is exactly the trade the
shape makes: coordinates are what makes a leaf citable. Leaf `text` is 7-11%
and is now optional in the parent, so a corpus-scale consumer can drop it and
have the validator rebuild it; these six keep it because a committed capture
is also something a person reads. The remaining structural choice — a span
table with no repeated `exact` — is still open and is still a contract
change, which is the point of the digest pin.

### Two fragments per document, resolved

Two leaves of every document are rendered as `rkaf:SourceFragment`s,
validated against rulespec's compiled `source-fragment.schema.json` and —
this is the check the first draft did not have — **resolved against the bytes
they name**. `tests/test_document_capture.py` evaluates every XPath against
the input with lxml and requires exactly one hit whose text contains the
leaf's, slices every byte range out of the artifact and requires it to carry
no markup and to decode to part of the leaf's text, and checks every page
region against the page's retained size. The USLM short-title leaf, from
`plaw-119publ1.fragments.json`:

```json
{
  "node": "n0042", "kind": "paragraph",
  "streamFragment": {
    "@type": "rkaf:SourceFragment",
    "oa:hasSource": "urn:document-capture:text-stream:sha256:f77fdbbb…",
    "oa:hasSelector": [
      {"@type": "oa:TextPositionSelector", "oa:start": 1010, "oa:end": 1059, "rkaf:coordinateSystem": "rkaf:unicode-codepoint"},
      {"@type": "oa:TextQuoteSelector", "oa:exact": "\u2003\u2003This Act may be cited as the \u201cLaken Riley Act\u201d."}],
    "rkaf:selectorKind": ["oa:TextPositionSelector", "oa:TextQuoteSelector"],
    "rkaf:fragmentIdentityScheme": "rkaf:published-fragment",
    "rkaf:sourceArtifactDigest": "sha256:f77fdbbb…", "rkaf:fragmentContentDigest": "sha256:723a5d22…"},
  "carrierLocalFragmentUrn": "urn:rkaf:fragment:urn%3Adocument-capture%3Atext-stream%3Asha256%3Af77fdbbb…:1010:1059:sha256-723a5d22…",
  "renditionFragment": {
    "@type": "rkaf:SourceFragment",
    "oa:hasSource": "urn:document-capture:artifact:sha256:ee0e7a5d…",
    "oa:hasSelector": [
      {"@type": "oa:XPathSelector", "rdf:value": "/*[local-name()='pLaw'][1]/*[local-name()='main'][1]/*[local-name()='section'][1]/*[local-name()='content'][1]"},
      {"@type": "rkaf:uslm-section", "rdf:value": "/us/pl/119/1/s1"},
      {"@type": "oa:TextPositionSelector", "oa:start": 3436, "oa:end": 3474, "rkaf:coordinateSystem": "rkaf:utf8-byte"},
      {"@type": "oa:TextPositionSelector", "oa:start": 3497, "oa:end": 3512, "rkaf:coordinateSystem": "rkaf:utf8-byte"},
      {"@type": "oa:TextPositionSelector", "oa:start": 3525, "oa:end": 3529, "rkaf:coordinateSystem": "rkaf:utf8-byte"},
      {"@type": "oa:TextQuoteSelector", "oa:exact": "\u2003\u2003This Act may be cited as the \u201cLaken Riley Act\u201d."}],
    "rkaf:selectorKind": ["oa:XPathSelector", "rkaf:uslm-section", "oa:TextPositionSelector", "oa:TextQuoteSelector"],
    "rkaf:fragmentIdentityScheme": "rkaf:published-fragment",
    "rkaf:sourceArtifactDigest": "sha256:ee0e7a5d…", "rkaf:fragmentContentDigest": "sha256:723a5d22…"}
}
```

The offsets, digests and quoted text in the retained file are exact; the
ellipses are this page's. Both changes in that rendition fragment are the
architecture review's. The XPath was `/pLaw[1]/main[1]/section[1]/content[1]`,
which selects nothing against a document with a default namespace; the
`local-name()` form selects the one element, and the recorded `source.path`
keeps the publisher's own spelling because `element_tree` now counts siblings
by local name, so the indices are the ones this form computes. The three byte
runs were one selector from 3436 to 3529: 93 bytes for 57 bytes of text,
because the leaf's text is interrupted twice by a `<shortTitle>` element, so
the position selector and the content digest described different regions.

A slip-opinion line renders its page region as
`page=1&viewrect=156.06,114.05,214.2,10.29` — points, the unit RFC 8118
defines, converted from the stored permille box by the page's retained
`pageSize` of 612 by 792. The first draft emitted permille under an RFC 8118
conformance claim, against an `application/json` source that RFC 8118 does not
address. A family whose page size is not retained emits
`rkaf:partner-defined` with the permille rule stated in `rdf:value` instead,
which is the honest form of the same coordinate.

### What the checks cannot see

The schema, invariant and resolved-selector checks establish that six real
documents fit one shape with no loss of text, and that every selector the
capture emits lands on the bytes it names. They do not establish that the
structure is right: a USLM `content` element read as a paragraph is the publisher's
word, but a committee report's blank-line block is this converter's
guess, and nothing here scores it. The reconstruction family inherits the
CFR benchmark's own measurement (`reconstruction-benchmark-2026-09-19.md`);
the other five families have no reference to score against and this record
claims none. Six documents also bound nothing about coverage: a bill with a
`quoted-block`, an FR rule with `REGTEXT` and `AMDPAR`, and a PDF with a
ruled table would each exercise a kind these six leave untouched.

## What the reviews changed

Two reviews read the draft on 2026-09-19: an architecture review of both
branches, and a visual review of the six profiles against the print rendition
of each family's own document. Neither is summarized away here — the visual
review is retained whole beside this file as
[`visual-review.md`](document-capture-schema-2026-09-19/visual-review.md) with
the fourteen pages it viewed under `png/` — but this is what each one moved.

### The architecture review

| Finding | What it found | What changed |
| --- | --- | --- |
| Composition checker | A whitelist over `properties` keys, in two copies that had already drifted; seven tightenings passed both, five changing what a capture validated as; `other:Foo` validated against parent and profile together | The rule is now the profile meta-schema, closed at every level, shipped in the wheel's `_data`. Both Python checkers are deleted. Each probe is a negative control in both repositories, and a profile refuses foreign prefixes itself |
| Rendition fragments do not resolve | USLM XPath 0 hits, bill XPath an undefined prefix, a multi-run leaf's byte range 93 bytes of markup for 57 of text | Namespace-agnostic XPath, one position selector per byte run, and a test that resolves every selector of every fragment against its input |
| The PDF artifact model | `artifact` was the extractor's JSON while `locator.url` named the PDF; `viewrect` in permille under an RFC 8118 claim; page size dropped by `evidence_from_pages` | `artifact` is the PDF, `rendition.intermediate` is the extractor document, `rendition.kind` is `pdf`, `page` nodes retain `pageSize` in points and the fragment is emitted in points |
| Test coverage | Stubbing any of the three validators left all 27 tests green; Rulespec shipped no invariant validator although its decision and spec claimed one | The validator is `rulespec_artifacts.document_capture`, and each of partition, ownership, kind namespace, leaf text, tree and digests has a mutation of a committed capture that must fail |
| No gate | `make test` never ran the Rulespec capture test | `make test-document-capture`, listed in `test:` |
| Provenance | A stale, unchecked fixture profile pin; `retrievedAt` on 2 of 6; `converter.revision` naming a commit without the converter | The pin is regenerated and asserted; every capture states when its bytes were read, to the precision its retention record has; the captures are regenerated after the commit that contains the converter |
| Scope leaks | `evidence-lines` was a SpicyDocs-internal artifact type in the Rulespec parent; the identifier-scheme enum duplicates rkaf §4.1 | `evidence-lines` became the intermediate slot; the spec says the enum is copied from rkaf-core §4.1 and re-pinned with it |
| Size | The stated cause was wrong: text repetition 7.5%, indentation 23%, about half derivable or constant | The decomposition above, measured by the converter, and four changes that took 26-48% off |
| Ledger | The ruling lived in one ledger with no forward pointer | A dated amendment on the 2026-08-02 entry, a row in the stack `DECISIONS.md`, and an entry in this repository's `docs/decisions.md` |
| The text stream's own identity | `oa:hasSource` named a text-stream IRI no `rkaf:Artifact` described | Spec §3 gives the materialization rule for it and for the intermediate |
| Big O | `has_structure` rescanned subtrees per level, the FR cell geometry was O(cells·(rows+cols)), the bill join O(n²), and the docstring claimed O(E) | Memoized, indexed, a set, and a docstring that says what the three non-linear steps are |

### The visual review

Every family was read against the print of its own document; fourteen pages
were viewed. Five families held; one did not.

| Family | Pages viewed | Visible elements | Matched | B / W / N | Verdict then | Now |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `slip-opinion-pdf` | 3 of 5 | 32 | 0 typed | 1 / 3 / 2 | DOES NOT FIT as a family profile | Fixed: opinion containers, furniture, whitespace lines, printed page numbers |
| `cfr-reconstruction` | 3 of 3 | 76 | 74 | 0 / 0 / 5 | HOLDS | Holds; the italic-font NIT is fixed |
| `uslm-law` | 4 of 4 | 91 | 90 | 0 / 1 / 4 | HOLDS WITH FIXES (U1) | Fixed: `legislativeHistory` is `backMatter`; the page-label error is an issue |
| `bill-xml` | 1 of 1 | 10 | 9 | 0 / 0 / 3 | HOLDS (thinly exercised) | Unchanged; still thinly exercised |
| `committee-report-html` | 2 of 4 | 23 | 11 | 0 / 2 / 5 | HOLDS WITH FIXES (R1, R2) | Fixed: four vote tables and eleven headings are read |
| `federal-register-xml` | 1 of 1 | 40 | 37 | 0 / 0 / 6 | HOLDS | Holds; `FRDOC`/`BILCOD` are now `backMatter` |

The blocker was S1: the slip opinion's print marks the opinion division three
ways — the designator the running head repeats on every page, the opening
formula, and the restart of the printed page number at each opinion — and the
profile could name none of it, so a capture of a five-page order with a
dissent said only "five pages of lines". The profile now has
`slip-opinion-pdf:syllabus`, `:opinion`, `:perCuriam`, `:concurrence` and
`:dissent` as containers with `ext` carrying `author`, `joinedBy` and a
`pageRange`. On the sample, the per curiam takes PDF pages 1-4 and
`JACKSON, J., dissenting` takes page 5; page 5's `designation` is `"1"`,
which is what it prints, with `ext.pdfOrdinal` 5 beside it. Two signals are
read and compared, and a page whose designator and formula disagree, or that
has no designator, records an issue rather than a guess. What is still not
classified is named: the masthead, docket line and caption stay `line` nodes,
and paragraphs are not reconstructed because the first-line indent that marks
one (273 against 255 permille) is visible but unmeasured.

Of the other findings: page furniture is separated by the fixed running-head
band (S2); the 77 whitespace-only extractor lines are no longer leaves, their
text belonging to the page container (S3); `page.designation` is the printed
number (S4); the CFR run-in headings' `style.italic` is read from the font
name, and a line whose runs disagree now states no flag at all rather than
`false` (C1); `legislativeHistory` maps to `backMatter` and the repeated
`139 STAT. 4` page label raises an issue (U1, U2); the Rules Committee's four
ruled vote tables become `table`/`row`/`cell` and its centred-capitals and
record-vote heads become headings (R1, R2); `backMatter` is used by every
family with printed back matter and `empty-leaf` is one rule everywhere (the
review's cross-family observations).

Two of the review's findings were not taken. The committee report's
`heading` nodes are flat, because the `<pre>` marks depth only by centring and
nothing in this document distinguishes a second level from a first beyond the
record-vote head; and the numbered amendment summaries (R4) stay paragraphs,
because "1." beginning a line is not enough to tell a list from a numbered
sentence without a corpus. Both are stated in the profile description rather
than left for a reader to discover.

## The shapes outside the stack

The brief asked how the capture compares with the shapes federal-document
consumers already use. None is a capture; each is a neighbour the capture
either carries or points at.

| Shape | What it holds | Relation to a capture |
| --- | --- | --- |
| unitedstates/congress bill-status JSON (`data.json`: `bill_id`, `bill_type`, `number`, `congress`, `titles`, `actions`, `sponsor`, `cosponsors`, `committees`, `subjects`, `summary`, `status`, `history`, `related_bills`) | Status metadata reshaped from GovInfo's BILLSTATUS XML (`tests/fixtures/govinfo_bills/status-119hr300.xml`) | Metadata about a bill, no body text, no coordinates. A capture of the bill's text would sit beside it, keyed by the same `bill_id`. The guessed govtrack address answered 404 and this row cites the project's documented shape, not a fetched example |
| GovInfo package summary JSON (`tests/fixtures/govinfo_bodies/summary-CRPT-119hrpt1.json`: `packageId`, `title`, `collectionCode`, `docClass`, `documentType`, `congress`, `session`, `chamber`, `dateIssued`, `lastModified`, `pages`, `suDocClassNumber`, `download.{modsLink, premisLink, zipLink}`, `granulesLink`, `detailsLink`) | Package metadata and rendition links | The `artifact.locator.publisherId` and the identifier the capture carries; the summary says which renditions exist, the capture says which one was read and what it contained |
| FederalRegister.gov document JSON (`inputs/fr-2026-19200.json`: `document_number`, `type`, `citation`, `publication_date`, `start_page`, `end_page`, `agencies`, `cfr_references`, `docket_ids`, `regulation_id_numbers`, `full_text_xml_url`, `body_html_url`, `raw_text_url`, `pdf_url`, `mods_url`, `html_url`, `json_url`, `topics`, `significant`, `toc_doc`, `toc_subject`) | Document metadata and four rendition pointers | The `federal-register-xml` profile's document `ext` carries the identity fields and the JSON's own digest; the capture is the `full_text_xml_url` rendition, structured |
| CourtListener opinion JSON (documented fields `plain_text`, `html`, `html_lawbox`, `html_columbia`, `html_with_citations`, `xml_harvard`, `download_url`, `local_path`, `sha1`, `type`; the search fixture `tests/fixtures/listings/courtlistener-search-opinions.json` shows `opinions[].{download_url, local_path, sha1, snippet, type}`) | Several renditions of one opinion as parallel text fields, one digest of the download | The closest neighbour in intent and the clearest contrast: parallel renditions with no coordinates and no structure. A capture would take one rendition and give it both. Not fetched; cited from the fixture and the published API documentation |
| Akoma Ntoso and USLM | Structural vocabularies with stable identifiers (`eId`; `identifier`) | Not competitors: a `native` capture keeps their elements as `source.element`, their identifiers in `ext`, and binds through rkaf's own `rkaf:aknt-eId` and `rkaf:uslm-section` selector kinds. A reconstruction *targets* such a vocabulary (the CFR profile serializes to GPO's), and the capture is the evidence-linked record beside that target, never a replacement for it |

## Closing

### The home and the boundary

The parent schema, the composition rule and the invariant validator are
Rulespec's, beside its other release-record schemas and inside its artifacts
wheel; the family profiles and the converters are SpicyDocs'. This respects the 2026-08-02 boundary as amended by the
2026-09-19 ruling: Rulespec owns generic container mechanics and the
fragment vocabulary and builds no document pipeline; SpicyDocs acquires and
parses; DocSpec processes what it is given. The user's lean toward Rulespec
is met for the shape and not for the parsing, which is the split the ruling
makes.

### What each product changes to adopt it

- **SpicyDocs.** `reconstruction` emits a capture: the `Serialized` result
  gains a capture beside its XML and source map, built the way
  `convert_cfr` builds one, so the CFR granule and the evidence-linked
  record travel together. The markup grammars in
  `tools/analysis/document_capture.py` move into `src/spicy_docs/capture/`
  as one module per family, with `reading.markup` and `extraction` unchanged
  underneath. The profile schemas stay where they are; the composition check
  and the invariant validator have already moved out, and the vendored copies
  of both go at the next `rulespec-artifacts` bump.
- **DocSpec.** A `Segment` over a capture's text stream is a range of spans:
  `representationStart`/`representationEnd` become code-point offsets into
  `textStream` (or UTF-8 byte offsets into its bytes, with the unit
  declared), `evidence` is the span's `source`, and the planned
  `structuralNode` with `structuralParentId`, `depth`, `ordinal` and
  `headingPath` is a capture node's `parent`, `depth`, `ordinal` and the
  heading leaves on its ancestor path. DocSpec's segments map to a capture;
  they are not one, and the capture does not replace `Representation`'s
  exact-bytes retention.
- **Rulespec.** Binds to it: a capture's leaves are the `SourceFragment`s an
  assertion's `EvidenceBinding` names, and the 2026-09-06 standalone
  workflow reads a capture as its local source document and segments it by
  meaning over the tree rather than over raw text. Rulespec adds the two
  schemas, the invariant validator in the artifacts wheel, the spec page, the
  decision and the test; no converter and no pipeline.
- **RefSpec.** Unaffected. Its vocabularies remain the terms an assertion
  assigns, and a capture carries none of them.

### The three biggest risks

1. **Structure is unscored outside the CFR.** Five of the six families have
   no reference corpus. A grammar error — a USLM `content` with nested
   structure read as a paragraph, an FR `LI` folded as a line break, a
   committee-report heading rule that fires on a capitalized sentence —
   validates, round-trips, resolves and is still wrong. The visual review is
   the first check that could catch one, and it caught four; but it read one
   document per family and says so. The CFR benchmark shows what a scored
   family costs: a paired corpus, frozen rules, a receipt. Each family needs
   one before its captures are cited, and the two new rule families (the
   slip-opinion designator, the committee-report table and heading) are the
   most exposed because they are the newest.
2. **Size at corpus scale.** A capture is 7 to 16 times its own text after
   the four size changes, and the largest remaining items are the coordinates
   that make it citable. For the 2,155 pinned public laws that is on the order
   of a gigabyte. The remaining lever is structural — a span table with no
   repeated `exact` — and it is a contract change, which the digest pin turns
   into a version rather than a drift.
3. **Three vendored Rulespec files.** The parent, the profile meta-schema and
   the invariant validator are copies here, pinned by digest, because the
   pinned wheel predates them. The digest test catches a drift, and a test
   that currently skips turns into byte equality the moment the wheel carries
   them — but until that bump, this repository runs Rulespec's rule from a
   copy. The bump is the one piece of this round that is deliberately not
   done: it belongs with a Rulespec release, not with a schema review.

### The decisions, restated on the new evidence

Six questions were left to the user in the first draft. Four now have answers
the reviews supply; two remain open, and are open for stated reasons.

1. **Does the composition checker ship in `rulespec-artifacts`?** *Answered:
   yes, and as data.* The rule is a meta-schema in the wheel's `_data`, the
   two bindings a schema cannot state are a Rulespec module, and both
   hand-written checkers are deleted. The architecture review's evidence was
   that the wheel already ships `platform-artifacts.md` and the fixture
   corpus this way, and that the two copies had already drifted.
2. **Whole captures or a span table?** *Still open, and now measurable.* The
   four cheap changes took 26-48% off without touching the contract. What
   remains is the coordinates, and the decomposition above says exactly what a
   span table would and would not save. Decide it against a corpus-scale
   consumer, not against these six.
3. **Does `slip-opinion-pdf` get a reconstruction profile?** *Answered: it
   needed one, and it has the part the print supports.* The visual review's
   blocker was that the family is defined by the opinion division and the
   profile could not name it. The division is now read from two signals the
   print states on every page. What a corpus would add is paragraph
   reconstruction and the syllabus, and that is still unmeasured; the sample
   has neither a syllabus nor a concurrence.
4. **Should `derivation` record the rendition preference rank?** *Still
   open.* Nothing in the reviews touched it. It stays a real question: a
   native HTML capture and one taken because XML was unavailable are
   different evidence, and today the capture does not say which.
5. **Is the parent's permille `Box` what DocSpec adopts?** *Answered
   differently than asked.* The box stays permille, because canonical identity
   JSON refuses floats — but the RFC 8118 conflict the review found means
   permille is an internal coordinate, not a fragment identifier. A `page`
   node's `pageSize` in points is what converts one to the other, and that is
   what DocSpec would need alongside any permille adoption.
6. **Do the committed captures stay?** *Answered: yes, smaller.* The
   directory is 816 KB now against 1.2 MB, they are the only behavioural evidence the six
   families have, and every negative control mutates one of them. Moving them
   to the receipt folder would leave the tests with nothing to refuse.
