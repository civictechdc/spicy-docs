# Document capture schemas, 1.0

The family profiles that compose Rulespec's `DocumentCapture v1` parent
schema, with the parent and the rulespec `SourceFragment` schema vendored
beside them and pinned by digest in `PINS.json`. A capture validates against
the parent and its family profile and records both pins. The design record is
[`docs/research/document-capture-schema-2026-09-19.md`](../../../../../docs/research/document-capture-schema-2026-09-19.md);
the worked conversions are produced by `tools/analysis/document_capture.py`
and checked offline by `tests/test_document_capture.py`.

| File | Origin | Why it is here |
| --- | --- | --- |
| `document-capture-v1.schema.json` | rulespec `release-records/schemas/document-capture-v1.schema.json`, branch `capture-schema-2026-09-19` | A consumer verifies a capture with no Rulespec checkout, the way DocSpec decision 0001 row 13 ships its schemas inside the bundle; the digest in `PINS.json` is the contract and a differing copy refuses |
| `rulespec/source-fragment.schema.json` | rulespec `compiled/json-schema/core/source-fragment.schema.json`, compiled from the tracked `constraints/core/source-fragment.cue` at `c8a371da` | The two leaf fragments each conversion renders are validated against Rulespec's own shape, not a restatement of it |
| `profiles/<family>.schema.json` | This repository | One per family; each is `allOf: [{$ref: parent}, own narrowing]` and narrows only `profile.name`, `profile.version`, `profile.ext`, node `kind` inside its namespace and node `ext` |
| `PINS.json` | This repository | The `$id` and sha256 of every file above |

Profile `$id`s are URNs (`urn:spicy-docs:schema:document-capture:1.0:profile:<name>`)
because they name a schema; nothing serves them.

## The families

| Profile | Rendition | Structure comes from | Family kinds |
| --- | --- | --- | --- |
| `uslm-law` | USLM XML | The publisher's elements (`native`) | `amendingAction`, `sidenote`, `toc`, `enactingFormula`, `sourceCredit` |
| `bill-xml` | Bill DTD XML | The publisher's elements, joined to DeltaTrack's `BillNode`s on the element id | `attestationGroup`, `toc` |
| `committee-report-html` | GovInfo HTML | One `<pre>` split into blank-line blocks (`markup`) | `preformatted`, `banner`, `rule` |
| `federal-register-xml` | FR XML | The publisher's elements; `GPOTABLE` rows and cells carry cell geometry | `listOfSubjects`, `regText` |
| `cfr-reconstruction` | Extracted PDF lines | `spicy_docs.reconstruction`'s nodes with their `decision` (`reconstructed`) | `flushParagraph`, `cita`, `blank`, `partHeading`, `contents`, `authority`, `sourceNote` |
| `slip-opinion-pdf` | Extracted PDF lines | Pages and lines only (`pdf-text`); the no-reference case | none |

Changing the parent moves its digest, every profile's `x-parent` pin, every
committed capture's `schema` pin and this directory's `PINS.json` in one
change; `tests/test_document_capture.py` fails otherwise.
