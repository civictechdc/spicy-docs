# Reconstruction

`spicy_docs.reconstruction` builds a publisher's own structured vocabulary
from a rendition that has none, and marks everything it produces as derived.

**Retrieve, then reconstruct, then interpret; never in the other order.** A
body is taken in the publisher's most structured rendition first — XML, then
HTML, then text, then PDF ([`sources.govinfo.bodies.BODY_PREFERENCE`](sources/govinfo-bodies.md)).
This package runs only where retrieval has nothing structured to give. What it
produces is a **derivative**: every serialized file travels with a source map
back to the evidence lines it was built from, every node names the rule or the
model call that placed it, and a hosted row derived from it says
`derivation = reconstructed`. [Interpretation](interpretation.md) runs after,
over facts and findings, and names its own rule; reconstruction rewrites
nothing either — it assembles and classifies the extractor's own text and
reports where it could not.

Install it with the `reconstruct` extra. Only schema validation needs it
(`lxml`); the rest of the package is standard library, and the one function
that needs it names the extra when it is absent, the way
[`bill_tree.py`](sources/congress-bill-tree.md) names `bill-diff`.

```sh
uv sync --frozen --extra reconstruct
```

## The modules

| Module | Responsibility |
| --- | --- |
| `profiles` | One frozen, versioned profile per target vocabulary: applicability, a schema bundle pinned by digest, the rules as a table, the serializer, the validation rules, fixture references. The registry answers by family or by applicability. |
| `evidence` | The evidence-linked document model. `EvidenceBlock` is one printed line as extracted; `DocumentNode` is one decision over a run of blocks; `UnresolvedRegion` is what no rule placed, kept with its issue. |
| `parse` | The deterministic structural parser: one pass, `O(B)` for `B` blocks, every node carrying its evidence and the rule that placed it, plus the `classify_and_attach` seam. |
| `serialize` | Deterministic XML in the target vocabulary, and a sidecar source map from XML path to evidence ids. |
| `validate` | Five separate findings and the acceptance gates as a pure function over them. |

`tools/analysis/reconstruction_benchmark.py` is the paired corpus builder and
scorer; see [its measurement](research/reconstruction-benchmark-2026-09-19.md).

## The profile record

A profile is data, the way `interpretation.bill_stage.STAGE_RULES` is data: a
reviewer reads the ladder rather than the control flow, and every node the
parser places names one of its rules. Three kinds of rule stay distinct
because they carry different authority when a real document disagrees with
them.

| Kind | Authority | What a disagreement means |
| --- | --- | --- |
| `schema` | The pinned DTD or XSD requires it | A violation is a schema finding, never something the parser works around |
| `guide` | The publisher's user guide states it as convention | The guide and a real section can disagree; when they do, **the section is evidence and the guide is convention** |
| `heuristic` | This repository measured it on a real rendition | It earns its place only by the benchmark, and it cites the document that showed it |

The `cfr` profile, version 1, has 4 schema rules from
[`CFRMergedXML.xsd`](../src/spicy_docs/reconstruction/schemas/cfr/README.md)
(pinned by digest, shipped in the package), 6 guide rules from GPO's
[CFR XML user guide](https://github.com/usgpo/bulk-data/blob/main/CFR-XML_User-Guide.md)
(pinned by the sha256 of the markdown it was read from), and 26 heuristics,
each citing the section it was derived against.

The guide is convention in a way that matters here: it names
`GPOTABLE`/`BOXHD`/`CHED`/`ROW`/`ENT` for a table, but a page image states no
cell boundary *in its text stream*, so the parser leaves a table region
**unresolved** rather than inventing a structure the guide would accept.
`extraction.model.TableObservation` (gap B5) now carries the geometry PyMuPDF
detects on the retained page, kept beside the text and never merged into it;
resolving these regions from that observation is the next measurement this
package should make, and it is deliberately not a rule yet. And the guide gives the
vocabulary but not the paragraph ladder — `(a)`, `(1)`, `(i)`, `(A)` — so
`marker_hierarchy` is a heuristic citing the OFR drafting handbook and the
section it was confirmed on, not a guide rule.

## The evidence model

Blocks come from what `extraction` already retains — a PDF's `PageResult`
pages, with the boxes `pages.py` normalized and the span fonts it kept in
`raw`; or the markup reader's events; or a text rendition's lines. Nothing is
extracted twice and nothing is dropped: page furniture, running heads and
neighbouring sections are blocks like any other, and classifying them is the
parser's job.

One transformation applies on the way in, because a justified column reaches
the extractor as word fragments: `line_assembly` joins consecutive lines that
share a vertical band and advance rightwards, and each block records how many
fragments it joined, so the rule is auditable rather than invisible.

Every id the package mints is marked `generated`, so no consumer can read one
as a publisher identifier.

## Serialization, and where the provenance goes

The output is CFRGRANULE > SECTION with SECTNO, SUBJECT, P, HD, CITA, NOTE, E
and PRTPAGE — the elements the guide names and the schema admits — and
**nothing of this repository's own travels in that vocabulary**: no id, no
confidence, no rule name, no evidence reference becomes an attribute. The
provenance goes in a separate source map keyed by each element's XML path
(`/CFRGRANULE/SECTION[1]/P[3]`), so the file stays one the publisher's own
schema accepts while every element can still be audited back to the lines
behind it.

Paragraph nesting is deliberately *not* emitted as nested elements: a real
granule sets `(a)`, `(1)`, `(i)` and `(A)` as sibling `P` elements in reading
order, and the schema's `SECTION` is a flat mixed choice. The tree the parser
derived is carried by the source map and checked by the structural finding
instead.

`FDSYS` — the title, volume, edition date and ancestry — is publisher metadata
that *retrieval* supplies (the MODS, or the request's own coordinates). It is
written only from facts a caller passes in and never derived from a page
image.

## The five checks

They are separate findings because they fail for different reasons and a
caller acts on each differently. One collapsed score would hide which.

| Finding | What it establishes | What it cannot see |
| --- | --- | --- |
| `schema_validity` | The output satisfies the profile's pinned schema, read from this package with a local catalog and **no network** | Nothing about whether the content is right |
| `content_fidelity` | Every element's text came from the evidence its source map names for it | Whether evidence was left out — that is coverage's job |
| `structural_fidelity` | The expected section is there and the marker ladder is sound | Whether the publisher's own XML nests it the same way |
| `coverage` | Every evidence block is classified or listed as unresolved, with out-of-scope evidence separated from loss | Whether a classification is correct |
| `acceptance` | The §3.3 gates over the other four | Anything it was not given a reference for — an undecided gate is reported `undecided`, never met |

Two deliberate refusals are worth knowing about. Schema validation does **not**
follow the document's own `noNamespaceSchemaLocation`: what a document claims
about its schema must never decide what it is validated against. And the
comparison normalization is a named table whose effect is counted per rule,
because an equality that a wide normalization made true is a formatting
assertion, not a verification.

## The gates, and the first numbers against them

The proposal's [§3.3](research/closing-the-gaps-2026-09-19.md) states
engineering targets, not results. Measured on the first bounded slice — 40
paired CFR sections from four titles and four editions, 84 requests, the XML
hidden from reconstruction
([full measurement](research/reconstruction-benchmark-2026-09-19.md)):

| Gate | Target | First run |
| --- | --- | --- |
| All accepted XML passes its pinned schema | all | 40 of 40 |
| Text precision on born-digital material | ≥ 99.9% | 99.93% |
| Text recall | ≥ 99.9% | 99.96% |
| Hierarchy F1 on supported structures | ≥ 0.98 | 1.0000 (23 of 40 sections have a paragraph ladder at all) |
| No unresolved change to a number, date, negation or provision marker | 0 documents | 2 of 40 |
| Every region accounted for | all | 40 of 40 |
| Accepted without review in the declared slice | ≥ 70% | 82% (33 of 40) |
| Cost per accepted document | reported | No model call was made; 28 ms of reconstruction per document |

**Read those numbers with the document's own caveats.** Six parser rules were
derived while this corpus was being read, and three of the documents that
motivated them are in the blind split — so the blind column is a development
column until a run whose rules were fixed beforehand. Forty clean documents
still permit roughly a 7% error rate at a one-sided 95% bound. The audit grows
with the claim.

Where it falls short is named rather than averaged away: four of the seven
unaccepted documents are a paragraph designation GPO sets run-in after an
italic heading, where the print gives the parser nothing to place it by and it
flags rather than guesses; two are an en dash where the published XML has a
hyphen, a disagreement between two renditions of one document; one is a
centred small-capital subject-group heading the parser has no rule for.

## What reconstruction does not do

It does not promise byte recovery of lost XML, does not carry GovInfo's
signature onto derived files, does not interpret legal effect or consolidate
amendments, does not force reports into a legislative schema, does not OCR
scans in the pilot, and does not take private documents.

## Decision

*For the maintainer to move to [`decisions.md`](decisions.md), or to reject.*

The pilot's first gate is met on text, hierarchy, schema and coverage, and is
short on two of §3.3's conditions: two documents in forty carry a critical
discrepancy, and acceptance without review is 82% against a 70% target but on
a corpus whose blind split was spent during development. Three things follow,
and a maintainer should rule on each:

1. **Whether the CFR benchmark has answered its question.** It was the
   controlled experiment, not the deployment corpus. If 99.93%/99.96% on 40
   paired sections is enough to proceed, the next work is the `bill_dtd`
   profile on pre-113th HTML, which is what the pilot exists for. If it is
   not, the next run is 500 sections on editions this one never touched, with
   no rule changed while it reads them.
2. **Whether an en dash is a critical discrepancy.** The print sets
   `Pub. L. 95–87`; the XML spells it with a hyphen. Both documents are the
   publisher's. Treating it as critical is defensible and it is what the
   current gate does; treating it as a stated rendition difference would move
   two documents of forty across the line. The decision belongs to whoever
   owns what "unresolved change to a number" means.
3. **Whether `classify_and_attach` should ever be wired.** No model was called
   in this run and nothing needed one: every unresolved region in forty
   sections belonged to a neighbouring part, not to the section asked for. The
   seam is declared and tested with abstention; the case for connecting it has
   not yet been made by a measurement.
