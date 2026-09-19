# A document capture schema for the platform

*2026-09-19. Design record for the `DocumentCapture v1` shape. Under
architecture review; nothing here is adopted until the review says so.*

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
each `allOf`-composing the parent and pinning it by digest. The boundary this
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
| Address a leaf so any product can cite it | rulespec `rkaf:SourceFragment` (`spec/rkaf-core.md` §4.2; `compiled/json-schema/core/source-fragment.schema.json`, vendored) | Every leaf renders as two fragments: one into the capture's text stream in `rkaf:unicode-codepoint`, which is the unit the carrier-local URN fixes, so every contiguous leaf gets `urn:rkaf:fragment:…` for free; one into the rendition artifact in its own coordinates (`oa:XPathSelector` and `rkaf:utf8-byte` positions for markup, an RFC 8118 `page=N&viewrect=` `oa:FragmentSelector` for a page region, `rkaf:uslm-section` for the enclosing USLM identifier). `rkaf:sourceArtifactDigest` and `rkaf:fragmentContentDigest` are the artifact and span digests the capture already carries | Nothing. The capture is a producer of fragments, never a redefinition of them; `EvidenceBinding` stays with whichever product makes an assertion |
| Evidence coordinates | DocSpec `domain/content.py` `EvidenceCoordinate` (`coordinate_system`, `source_digest`, half-open `start`/`end`, `page`, `region`) and `EvidenceMapping` (representation range to captured-file evidence, with a named `transformation`); decision 0001's `rendition-utf8-byte` and `rendition-byte` systems | A span's `source` is an `EvidenceCoordinate` in DocSpec's terms: `utf8-byte` over the captured file with a `literal` flag, or `page-region` with a page and box. A span with `literal: true` is DocSpec's identity byte-slice transformation; one with `literal: false` resolves to its whole run, DocSpec's own rule for entity-decoded text (`docs/shared-source-readers.md`) | The page box. Decision 0001 designed and dropped a `rendition-page-region` system "until a coordinate-emitting extractor is chosen, permille rule included"; SpicyDocs `extraction.model.Box` now emits one, so the capture carries the dropped design: integer permille, so the value is admissible to canonical identity JSON |
| Text-bearing units with byte spans | SpicyDocs `reading/markup.py` `MarkupEvent` (`byte_start`, `byte_end`, `is_literal`) | One span per text event; the leaf's enclosing element gives `source.path`, `source.element`, `source.attributes` and the element's byte range | Nothing |
| Reconstructed structure with the rule that placed it | SpicyDocs `reconstruction/evidence.py` (`EvidenceBlock`, `DocumentNode` with `evidence_refs` and `decision`, `UnresolvedRegion`, `ID_ORIGIN = "generated"`) and `serialize.py`'s sidecar `SourceMap` keyed by XML path | A reconstructed node is a `DocumentNode`: `decision`, `reviewStatus`, `designation` from `marker`, `derived.text` from the profile's assembled `text`, `ext.xmlPath` from the source map, unresolved regions carried as they are | The partition. `DocumentNode.evidence_refs` lets a parent and its children share one block (a section and its number and subject split one printed line); the capture splits that block into spans so each belongs to exactly one node, and a node with both its own lines and children keeps its lines in an implicit first `text` child, the way a markup container does |
| PDF pages, lines, styles and tables | SpicyDocs `extraction/model.py` (`PageResult`, `TextBlock`, `Box`, `TableObservation` with `cells` and `cell_boxes`) through `reconstruction.evidence.evidence_from_pages` | `page` and `line` nodes; `style` on spans from the extractor's spans; `cell` with `row`, `column`, `header` and a `source.box` for a detected table | Nothing; the `TableObservation` route is unexercised by the six documents (none has a ruled table) and is a risk below |
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
  "schema": {"$id": "https://rulespec.org/schemas/releases/document-capture-v1.schema.json", "sha256": "90515b95…"},
  "capture": {"id": "urn:document-capture:sha256:…", "capturedAt": "2026-09-19T22:48:34+00:00", "idOrigin": "generated", "idScheme": "document-order"},
  "artifact": {"iri": "urn:document-capture:artifact:sha256:…", "sha256": "…", "byteSize": 2751, "mediaType": "application/xml",
               "locator": {"url": "https://www.govinfo.gov/content/pkg/BILLS-119hjres25enr/xml/BILLS-119hjres25enr.xml", "path": "tests/fixtures/govinfo_bills/text-119hjres25enr.xml", "publisher": "GovInfo", "publisherId": "BILLS-119hjres25enr"},
               "identifiers": [{"scheme": "rkaf:hash-sha256", "value": "sha256:…"}, {"scheme": "rkaf:partner-defined", "value": "govinfo:BILLS-119hjres25enr"}]},
  "rendition": {"kind": "xml", "textStream": {"iri": "urn:document-capture:text-stream:sha256:…", "sha256": "…", "codePoints": 1335,
                "normalization": {"id": "markup-character-data", "statement": "The decoded character data of every text event … inside the root element …", "reversible": true}}},
  "converter": {"id": "spicy-docs/tools/analysis/document_capture.py#bill-xml", "version": "1",
                "implementation": {"repository": "spicy-docs", "revision": "56c988b3…", "fileSha256": "…"},
                "dependencies": [{"name": "python", "version": "3.12.13"}, {"name": "spicy-docs", "version": "0.21.2"}, {"name": "deltatrack", "version": "0.1.0"}]},
  "profile": {"name": "bill-xml", "version": "1", "schema": {"$id": "urn:spicy-docs:schema:document-capture:1.0:profile:bill-xml", "sha256": "…"},
              "ext": {"rootTag": "resolution", "bodyTags": ["resolution-body"], "stage": "Enrolled-Bill", "deltatrack": {"version": "0.1.0", "nodes": 4, "joined": ["H9640A741EA66463CBF5B8E71B5C8BA43"], "unjoined": [ … ]}, "discardedElements": { … }}},
  "nodes": [
    {"id": "n0001", "kind": "document", "parent": null, "ordinal": 0, "depth": 0, "derivation": "native", "evidence": ["s0001", "s0002", "s0015", "s0016", …], "source": {"coordinateSystem": "xml-node-path", "path": "/resolution[1]", "element": "resolution", "attributes": {"resolution-stage": "Enrolled-Bill", …}, "start": 150, "end": 2748}},
    …,
    {"id": "n0019", "kind": "section", "parent": "n0018", "ordinal": 0, "depth": 2, "derivation": "native", "designation": "", "evidence": [],
     "source": {"coordinateSystem": "xml-node-path", "path": "/resolution[1]/resolution-body[1]/section[1]", "element": "section", "attributes": {"id": "H9640A741EA66463CBF5B8E71B5C8BA43", …}, "start": 2037, "end": 2479},
     "ext": {"matchPath": [], "displayPath": [], "tag": "section", "elementId": "H9640A741EA66463CBF5B8E71B5C8BA43", "sectionNumber": "", "bodyIndex": 0}},
    {"id": "n0020", "kind": "label", "parent": "n0019", "ordinal": 0, "depth": 3, "derivation": "native", "text": "", "evidence": [], "source": { … "element": "enum" …}, "issues": [{"code": "empty-leaf", "detail": "enum carries no text"}]},
    {"id": "n0021", "kind": "paragraph", "parent": "n0019", "ordinal": 1, "depth": 3, "derivation": "native",
     "text": "That Congress disapproves the rule submitted by the Internal Revenue Service relating to Gross Proceeds Reporting by Brokers That Regularly Provide Services Effectuating Digital Asset Sales (89 Fed. Reg. 106928 (December 30, 2024)), and such rule shall have no force or effect.",
     "evidence": ["s0038", "s0039", "s0040"], "source": {"coordinateSystem": "xml-node-path", "path": "/resolution[1]/resolution-body[1]/section[1]/text[1]", "element": "text", "start": 2164, "end": 2469}}
  ],
  "evidence": [
    …,
    {"id": "s0039", "start": 1040, "end": 1140, "exact": "Gross Proceeds Reporting by Brokers That Regularly Provide Services Effectuating Digital Asset Sales", "sha256": "…",
     "source": {"coordinateSystem": "utf8-byte", "start": 2266, "end": 2366, "literal": true}, "tags": ["quote"]}
  ],
  "unresolved": [], "issues": [{"code": "deltatrack-node-without-element", "detail": "front-matter front-matter-masthead is synthesized by the engine, not an element"}, …]
}
```

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
| Per-span coordinates and content digests | A citation must survive the artifact being replaced under it (`rkaf-core.md` §4.2: `sourceArtifactDigest` and `fragmentContentDigest` answer different questions) | `Span.sha256` required; `check_invariants` re-derives it |
| Unresolved regions survive with an issue | "Nothing is dropped" is the reconstruction package's rule and the RefSpec thesaurus reader's; a dropped run is a silent claim that the text was not there | `unresolved` required; a span owned by nothing fails `check_invariants` |
| Stable generated ids, marked as generated | The reconstruction package's `ID_ORIGIN` rule: no consumer may read a minted id as a publisher identifier; document-order ids are deterministic for one input through one converter version | `capture.idOrigin` and `idScheme` constants in the parent |
| Round trip under a stated, reversible normalization | A capture that cannot reproduce its rendition's text is a summary, not evidence. The normalization is stated per rendition kind and the check is re-derived with a second parser (the doctrine's "different tool family") | `textStream.normalization` required; `check_invariants` checks the partition; `measure` and `tests/test_document_capture.py` re-derive the stream with lxml (libxml2) for XML, the standard library's HTMLParser for HTML, and a plain JSON rejoin for evidence lines |
| One core, family parts in a declared `profile` block | A per-family branch in the core would make the sixth family a schema change; a profile is a file | `profile` required; `check_profile_composition` refuses a profile that touches any parent field but `profile.*`, node `kind` in its namespace and node `ext` |
| Plain JSON, JSON Schema draft 2020-12, pinned by digest | A shape a consumer can validate with no product checkout (DocSpec 0001 row 13) | `schema` and `profile.schema` pins; `PINS.json`; both repositories' tests |
| Two coordinate units, each declared | The lesson "two products' identifiers never compare equal by accident": DocSpec counts UTF-8 bytes, rkaf's carrier-local URN counts code points. The stream is in code points and every rendition selector declares its unit | `Span.start`/`end` in code points; `source.coordinateSystem` per span; `rkaf:coordinateSystem` on every position selector |
| Containers carry no citable text | A citation lands on a leaf, so a leaf's `text` is the whole of what its spans say and a container's spans are whitespace or separators; a unit with its own lines and children keeps its lines in a first `text` child | `check_invariants` ("text presence disagrees with leafness") |
| Integer permille boxes | Rulespec's canonical identity JSON refuses floats; a capture is not an identity value, but its coordinates should be admissible to one | `Box` in the parent |

## The composition rule

A profile is `allOf: [{"$ref": <parent $id>}, <own narrowing>]`, carries
`x-parent` with the parent's `$id` and byte digest, and in its own narrowing
touches only `profile.name` (a constant), `profile.version` (a constant),
`profile.ext` (its closed document block), node `kind` (an `if` on
`^<name>:` then an enum) and node `ext` (its closed per-node block). It never
restates a parent field. The rule is stated in rulespec
`spec/document-capture.md` §4 and checked by the same fifteen-line function
in both repositories: `tools/test_document_capture_schema.py` in rulespec,
`tools/analysis/document_capture.py` here. The duplicate is the cost of the
ownership split, and one of the decisions left to the user below is whether
it moves into `rulespec-artifacts` so SpicyDocs imports it.

## The families

| Profile | Rendition | Structure from | Family kinds | What it cannot see |
| --- | --- | --- | --- | --- |
| `uslm-law` | USLM XML | The publisher's elements: `section`, `subsection`… are `section` and `paragraph`, `num` is the `label` whose text becomes the parent's `designation`, `quotedContent` is a `quote`, `page` is `pageNumber` | `amendingAction`, `sidenote`, `toc`, `enactingFormula`, `sourceCredit` | Inline markup (`ref`, `quotedText`, `date`) folds into a leaf's spans as `tags`; a `page` marker inside a leaf folds too |
| `bill-xml` | Bill DTD XML | The publisher's elements; each element DeltaTrack flattened carries the engine's paths in `ext`, joined on the element id | `attestationGroup`, `toc` | The engine's three synthesized front-matter nodes have no element and are recorded as unjoined plus issues; `discarded_elements` is carried in `profile.ext` |
| `committee-report-html` | GovInfo HTML | The `<title>` and the one `<pre>` run, split into blank-line blocks: `paragraph`, `pageNumber` (`[[Page N]]`), `banner`, `rule`; blocks are `derivation: markup` | `preformatted`, `banner`, `rule` | No heading, section or table structure: the rendition has none, and this converter does not reconstruct |
| `federal-register-xml` | FR XML | The publisher's elements: preamble blocks are `section`s with a level-1 `heading`, `HD SOURCE=HDn` gives heading levels, `GPOTABLE`/`BOXHD`/`ROW`/`CHED`/`ENT` give `table`/`row`/`cell` with `cell.row`, `cell.column`, `cell.header`, `FTNT` is `footnote`, `PRTPAGE` is `pageNumber` | `listOfSubjects`, `regText` | A `PRTPAGE` inside a `P` folds into the paragraph; `LI` inside a cell head is a line break, kept as a tag |
| `cfr-reconstruction` | Extracted PDF lines | `spicy_docs.reconstruction`'s nodes with `decision`, `reviewStatus`, `derived.text` and the serialized granule's `xmlPath`; every block is a span with page, box and style | `flushParagraph`, `cita`, `blank`, `partHeading`, `contents`, `authority`, `sourceNote` | Nothing the reconstruction did not: a paragraph interrupted by a page break is one non-contiguous leaf |
| `slip-opinion-pdf` | Extracted PDF lines | Pages and lines only; the no-reference case | none | Everything: no running head, syllabus or opinion boundary is classified, because no rule was measured for it. This is honest, and it is the family that shows what a capture is without a reconstruction profile |

## The worked conversions

Six documents, one converter, one shape. Produced by
`tools/analysis/document_capture.py`, retained in
[`document-capture-schema-2026-09-19/`](document-capture-schema-2026-09-19/README.md)
beside their input pins, re-checked offline by `tests/test_document_capture.py`
(27 tests). The receipt for the five keyless requests is
`~/Work/corpora/supply-2026-09-02/receipts/document-capture-schema-2026-09-19/`.

| Document | Family | Rendition | Artifact bytes | Capture bytes | Nodes | Leaves | Empty leaves | Non-contiguous leaves | Spans | Unresolved | Issues | Code points | Partition digest | Independent derivation | Schema, profile, invariants, fragments | Seconds |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |
| `plaw-119publ1` | `uslm-law` | xml | 23,379 | 234,059 | 320 | 216 | 0 | 0 | 325 | 0 | 0 | 8,660 | match | match, lxml.etree (libxml2) itertext | all pass | 0.0009 |
| `bills-119hjres25enr` | `bill-xml` | xml | 2,751 | 30,648 | 26 | 18 | 3 | 0 | 45 | 0 | 6 | 1,335 | match | match, lxml.etree (libxml2) itertext | all pass | 0.0003 |
| `crpt-119hrpt1` | `committee-report-html` | html | 13,953 | 172,209 | 44 | 41 | 0 | 0 | 461 | 0 | 0 | 13,900 | match | match, html.parser.HTMLParser(convert_charrefs=True) handle_data | all pass | 0.0005 |
| `fr-2026-19200` | `federal-register-xml` | xml | 10,224 | 107,420 | 75 | 59 | 2 | 0 | 209 | 0 | 1 | 8,758 | match | match, lxml.etree (libxml2) itertext | all pass | 0.0005 |
| `cfr-2025-title30-vol3-sec716-2` | `cfr-reconstruction` | evidence-lines | 101,921 | 319,633 | 87 | 71 | 0 | 2 | 721 | 0 | 0 | 12,694 | match | match, json: evidence blocks rejoined by page | all pass | 0.0009 |
| `scotus-26a274_l537` | `slip-opinion-pdf` | evidence-lines | 73,533 | 241,496 | 243 | 237 | 0 | 0 | 473 | 0 | 0 | 8,024 | match | match, json: evidence blocks rejoined by page | all pass | 0.0008 |

Reading the table:

- **Partition digest** is the internal check: sha256 over the concatenated
  spans equals `textStream.sha256`. On its own that is a formatting
  assertion, since the converter wrote both sides.
- **Independent derivation** is the check that can fail: the stream is
  re-derived from the retained artifact by a different implementation of the
  stated normalization. For XML that is libxml2 through `lxml.etree`
  against the reader's expat; it matched on all three XML documents,
  including the USLM file with eight processing instructions and a comment
  inside the root. For HTML it is the standard library's `HTMLParser` with
  its own character-reference decoding; the first run differed by one
  character, the newline after `</html>`, which the reader excludes and the
  library does not, and the normalization statement now says "inside the
  root element" and the check honors it. libxml2's HTML parser could not
  serve here because it drops inter-element whitespace, and a witness that
  normalizes cannot witness a whitespace-exact stream. For evidence lines the
  re-derivation is a plain JSON rejoin of the retained blocks, which checks
  the partition and the separators and nothing about the extractor: for a
  PDF the round trip is over the retained extractor output, never the PDF
  bytes, and the capture says so in its normalization statement.
- **Empty leaves** are the publisher's empty elements (`dc:date`,
  `current-chamber` and `enum` in the enrolled resolution; the `PRTPAGE`
  marker and an empty `P` in the notice), each with an `empty-leaf` issue.
  The two **non-contiguous leaves** are the reconstructed paragraphs the
  fixture README documents as carrying a page break; the fragment rendering
  gives them two position selectors and no carrier-local URN.
- **Capture bytes** run seven to twelve times the artifact for markup and
  about three times for evidence lines. Every span repeats its text, its
  digest and its coordinates, and every leaf repeats its spans' text; that
  is the price of a document that validates and cites on its own, and it is
  the first risk below.
- **Seconds** are the tree-and-partition build alone, one pass over the
  events. Nothing here is superlinear; the shared-block split scans one
  printed line per child.

Two leaves of every document are rendered as `rkaf:SourceFragment`s and
validated against rulespec's compiled `source-fragment.schema.json`,
including the typed `TextPositionSelector` and `TextQuoteSelector` shapes.
The USLM section 1 paragraph, from `plaw-119publ1.fragments.json`:

```json
{
  "node": "n0042", "kind": "paragraph",
  "streamFragment": {
    "@type": "rkaf:SourceFragment",
    "oa:hasSource": "urn:document-capture:text-stream:sha256:f77fdbbb…",
    "oa:hasSelector": [
      {"@type": "oa:TextPositionSelector", "oa:start": 1010, "oa:end": 1059, "rkaf:coordinateSystem": "rkaf:unicode-codepoint"},
      {"@type": "oa:TextQuoteSelector", "oa:exact": "  This Act may be cited as the “Laken Riley Act”."}],
    "rkaf:selectorKind": ["oa:TextPositionSelector", "oa:TextQuoteSelector"],
    "rkaf:fragmentIdentityScheme": "rkaf:published-fragment",
    "rkaf:sourceArtifactDigest": "sha256:f77fdbbb…", "rkaf:fragmentContentDigest": "sha256:723a5d22…"},
  "carrierLocalFragmentUrn": "urn:rkaf:fragment:urn%3Adocument-capture%3Atext-stream%3Asha256%3Af77fdbbb…:1010:1059:sha256-723a5d22…",
  "renditionFragment": {
    "@type": "rkaf:SourceFragment",
    "oa:hasSource": "urn:document-capture:artifact:sha256:ee0e7a5d…",
    "oa:hasSelector": [
      {"@type": "oa:XPathSelector", "rdf:value": "/pLaw[1]/main[1]/section[1]/content[1]"},
      {"@type": "rkaf:uslm-section", "rdf:value": "/us/pl/119/1/s1"},
      {"@type": "oa:TextPositionSelector", "oa:start": 3436, "oa:end": 3529, "rkaf:coordinateSystem": "rkaf:utf8-byte"},
      {"@type": "oa:TextQuoteSelector", "oa:exact": "  This Act may be cited as the “Laken Riley Act”."}],
    "rkaf:selectorKind": ["oa:XPathSelector", "rkaf:uslm-section", "oa:TextPositionSelector", "oa:TextQuoteSelector"],
    "rkaf:fragmentIdentityScheme": "rkaf:published-fragment",
    "rkaf:sourceArtifactDigest": "sha256:ee0e7a5d…", "rkaf:fragmentContentDigest": "sha256:723a5d22…"}
}
```

The offsets, digests and quoted text in the retained file are exact; the
ellipses are this page's. The `rkaf:uslm-section` selector names the
enclosing USLM unit and the position selectors narrow within it. A slip
opinion line renders one RFC 8118 `page=1&viewrect=273,398,477,17`
fragment selector in permille; a reconstructed paragraph renders one per
printed line it rests on.

### What the checks cannot see

The schema and invariant checks establish that six real documents fit one
shape with no loss of text. They do not establish that the structure is
right: a USLM `content` element read as a paragraph is the publisher's
word, but a committee report's blank-line block is this converter's
guess, and nothing here scores it. The reconstruction family inherits the
CFR benchmark's own measurement (`reconstruction-benchmark-2026-09-19.md`);
the other five families have no reference to score against and this record
claims none. Six documents also bound nothing about coverage: a bill with a
`quoted-block`, an FR rule with `REGTEXT` and `AMDPAR`, and a PDF with a
ruled table would each exercise a kind these six leave untouched.

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

The parent schema and its composition rule are Rulespec's, beside its other
release-record schemas; the family profiles and the converters are
SpicyDocs'. This respects the 2026-08-02 boundary as amended by the
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
  moves out once Rulespec ships it.
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
  meaning over the tree rather than over raw text. Rulespec adds the
  schema, the spec page, the decision and the test; nothing else.
- **RefSpec.** Unaffected. Its vocabularies remain the terms an assertion
  assigns, and a capture carries none of them.

### The three biggest risks

1. **Size.** A capture is seven to twelve times its markup artifact. At
   corpus scale (the 10k DocSpec checkpoint, the 2,155 pinned public laws)
   that is gigabytes of repeated text and digests. The remedy is a compact
   serialization or a span table without repeated `exact` text, and either
   changes the contract; the digest pin makes that a version, not a drift.
2. **Structure is unscored outside the CFR.** Five of the six families have
   no reference. A grammar error (a USLM `content` with nested structure
   read as a paragraph, an FR `LI` folded as a line break) would validate
   and round-trip and still be wrong. The CFR benchmark shows what a scored
   family costs: a paired corpus, frozen rules, a receipt. Each family needs
   one before its captures are cited.
3. **Two copies of the composition rule and one vendored parent.** The
   check lives in both repositories by hand, and the parent is a copy pinned
   by digest. A change to either that is not carried to the other will be
   caught by a test, but the ownership split guarantees the drift will
   happen; the fix is for `rulespec-artifacts` to ship the checker and the
   parent so SpicyDocs imports both.

### Decisions left to the user

- Whether the composition checker and the parent schema ship in
  `rulespec-artifacts`, so SpicyDocs imports rather than vendors them.
- Whether captures are stored whole (as here) or as a span table plus a
  node table, which halves the bytes and changes the contract.
- Whether the `slip-opinion-pdf` family gets a reconstruction profile (a
  scored `bill_dtd`-style ladder for opinions) or stays the no-reference
  case, and which corpus would score it.
- Whether `derivation` should also record the rendition preference rank
  the body was taken at (`xml, uslm, htm, txt, pdf`), so a consumer can tell
  a native HTML capture from one taken because XML was unavailable.
- Whether the parent's `Box` in permille is the coordinate system DocSpec
  adopts for its deferred `rendition-page-region`, closing that row of
  decision 0001, or whether DocSpec chooses its own.
- Whether the six `docs/research/document-capture-schema-2026-09-19/`
  captures (1.2 MB) stay committed as fixtures or move to the receipt folder
  with only their digests retained here.
