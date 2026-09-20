# Document capture schemas, 1.0

The family profiles that compose Rulespec's `DocumentCapture v1` parent
schema, with the Rulespec files they depend on vendored beside them and
pinned by digest in `PINS.json`. A capture validates against the parent and
its family profile and records both pins. The design record is
[`docs/research/document-capture-schema-2026-09-19.md`](../../../../../docs/research/document-capture-schema-2026-09-19.md);
the worked conversions are produced by `tools/analysis/document_capture.py`
and checked offline by `tests/test_document_capture.py`.

| File | Origin | Why it is here |
| --- | --- | --- |
| `document-capture-v1.schema.json` | rulespec `release-records/schemas/document-capture-v1.schema.json`, branch `capture-schema-2026-09-19` | A consumer verifies a capture with no Rulespec checkout, the way DocSpec decision 0001 row 13 ships its schemas inside the bundle; the digest in `PINS.json` is the contract and a differing copy refuses |
| `document-capture-profile-v1.schema.json` | rulespec `release-records/schemas/document-capture-profile-v1.schema.json` | The composition rule, as data. Every profile here validates against it, so a profile that reaches a parent field fails validation rather than passing a whitelist |
| `rulespec/document_capture.py` | rulespec `packages/rulespec-artifacts/src/rulespec_artifacts/document_capture.py` | The one implementation of the invariants JSON Schema cannot state, and of the two profile bindings the meta-schema cannot state. Vendored as bytes, never re-implemented |
| `rulespec/source-fragment.schema.json` | rulespec `compiled/json-schema/core/source-fragment.schema.json`, compiled from the tracked `constraints/core/source-fragment.cue` at `c8a371da` | The two leaf fragments each conversion renders are validated against Rulespec's own shape, not a restatement of it |
| `profiles/<family>.schema.json` | This repository | One per family; each is `allOf: [{$ref: parent}, own narrowing]` and narrows only `profile.name`, `profile.version`, `profile.ext`, node `kind` inside its namespace and node `ext` |
| `PINS.json` | This repository | The `$id` and sha256 of every file above |

**These three Rulespec files are vendored, not ours.** They ship in the
`rulespec-artifacts` wheel's `_data` and as a module; the wheel pinned here
(1.0.13) predates all three, so they are copied and pinned until the next
wheel bump. `tools/analysis/document_capture.py` imports
`rulespec_artifacts.document_capture` when the installed wheel carries it and
falls back to the vendored file otherwise, and
`test_the_vendored_copies_equal_the_wheel_when_the_wheel_carries_them`
asserts byte equality the moment it does. At that point the copies and the
fallback go away together.

Profile `$id`s are URNs (`urn:spicy-docs:schema:document-capture:1.0:profile:<name>`)
because they name a schema; nothing serves them.

## The families

| Profile | Rendition | Structure comes from | Family kinds |
| --- | --- | --- | --- |
| `uslm-law` | USLM XML | The publisher's elements (`native`), `legislativeHistory` mapping to core `backMatter` | `amendingAction`, `sidenote`, `toc`, `enactingFormula`, `sourceCredit` |
| `bill-xml` | Bill DTD XML | The publisher's elements, joined to DeltaTrack's `BillNode`s on the element id | `attestationGroup`, `toc` |
| `committee-report-html` | GovInfo HTML | One `<pre>` split into blank-line blocks (`markup`); a block is a ruled column-aligned table, a centred-capitals or record-vote heading, or a paragraph, page marker, banner or rule | `preformatted`, `banner`, `rule`, `heading` |
| `federal-register-xml` | FR XML | The publisher's elements; `GPOTABLE` rows and cells carry cell geometry; `FRDOC`/`BILCOD` become core `backMatter` | `listOfSubjects`, `regText` |
| `cfr-reconstruction` | A section PDF through the retained extractor document | `spicy_docs.reconstruction`'s nodes with their `decision` (`reconstructed`) | `flushParagraph`, `cita`, `blank`, `partHeading`, `contents`, `authority`, `sourceNote` |
| `slip-opinion-pdf` | A slip opinion PDF through the retained extractor document | Pages and lines, with the opinion division read from the designator in the running-head band and the opening formula | `syllabus`, `opinion`, `perCuriam`, `concurrence`, `dissent` |
| `senate-expenditures-pdf` | Selected retained Senate expenditure PDF pages | The shared line adapter plus `PageResult.tables`; every observed cell survives, with exact stream spans when reconciled | None; uses core `table`, `row`, `cell` |

The Senate profile adds no core kinds and changes no existing profile. None of
the original six describes this family. Its closed extension fields retain the
package and file, selected pages, raw page-text digest, table dimensions and
ordinal, and `observedText` for each cell. The adapter lives beside the original
converter in `tools/analysis/document_capture_pdf_tables.py`; the new profile
composes the same pinned parent under the same meta-schema.

An empty string is a present empty cell; a position with neither text nor box
has no cell node. A nonempty observation without a box remains with a
`pdf-cell-box-missing` issue. Text reconciliation never edits the line stream:
an exact match on the same page transfers existing spans to the cell. Repeated
matches require cell-local line geometry; remaining ambiguity, overlapping
claims, and text absent from the stream become `pdf-cell-text-unresolved`
issues with `reviewStatus: needs_review`. The verbatim observation remains in
`ext.observedText`. The parent's `unresolved` array cannot hold these cases
because each region requires an existing span; inventing one would break the
text partition. `rowSpan`, `columnSpan` and `header` remain unstated because
`TableObservation` does not supply them.

For the PDF families the `artifact` is the PDF and the extractor document
is `rendition.intermediate`: a consumer that follows `artifact.locator.url`
and checks `artifact.sha256` lands on the bytes the publisher issued.

Changing the parent moves its digest, every profile's `x-parent` pin, every
committed capture's `schema` pin and this directory's `PINS.json` in one
change; `tests/test_document_capture.py` fails otherwise.

## Reversible capture XML

`spicy_docs.schemas.document_capture.xml` supplies `encode_capture(dict) -> bytes`
and `decode_capture(bytes) -> dict` without optional dependencies. Namespace:
`urn:spicy-docs:document-capture:xml:1`. This represents the capture's fields,
including provenance, rather than a publisher vocabulary. It leaves the
schemas and existing publisher serializers unchanged.

```python
import json
from pathlib import Path
from spicy_docs.schemas.document_capture.xml import encode_capture, decode_capture

capture = json.loads(Path("document.capture.json").read_bytes())
xml = encode_capture(capture)
Path("document.capture.xml").write_bytes(xml)
restored = decode_capture(xml)
```

Run Python examples through `UV_OFFLINE=1 uv run --frozen python`. Serialization
checks the XML format and capture version; validate the capture separately
against its pinned parent/profile and Rulespec invariants. Unsupported values
raise `CaptureXmlError`. The [format and measurement record](../../../../../docs/research/document-capture-xml-roundtrip-2026-09-20.md)
defines exact escaping, numeric types and refusal rules. The full-value tests
in `tests/test_document_capture_xml.py` include every tracked `*.capture.json`
and a fresh Senate table adapter result.

## Family provenance findings

`spicy_docs.schemas.document_capture.provenance.check_provenance(capture)`
checks the family requirements in addition to parent/profile validation.
It reports missing acquisition evidence, full retrieval time, publisher URL,
paired GovInfo identity and MODS reference where applicable, PDF intermediates,
page dimensions, coordinate fields and decisions for derived nodes. It makes
no request. `check_artifact_binding` checks each stated locator against supplied
retained bytes/observations; `check_archive_member` verifies both byte objects.
See the [required fields, retained gaps and Rulespec handoff](../../../../../docs/research/document-capture-provenance-2026-09-20.md).

The profiles use permitted extension fields for pinned source records,
GovInfo pairs, rendition reasons and source-artifact relationships while the
shared parent work remains with Rulespec. Package-level pairs state a null
granule explicitly. Reduced or derived files never borrow the publisher URL
of their original as a direct locator. The Senate cut's `derivedFrom` and the
USLM member's `archiveMember` preserve the original's separate byte facts.
