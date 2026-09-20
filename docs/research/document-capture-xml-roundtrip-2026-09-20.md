# Reversible XML for DocumentCapture

**G1 is closed for capture JSON/XML reversibility.** All seven retained
captures preserve every field through XML, including the Senate table cells.
XML costs 1,618,906 bytes against 685,709 JSON bytes: **933,197 extra bytes,
2.36× overall**. The run made **zero requests**. The
[vocabulary decision](../decisions.md#reversible-capture-xml-names-the-captures-structures)
preceded implementation in commit `7c33e74`; initial code and fixtures are in
`fe6876e`, with diagnostic fixes and expanded mutation tests in `0433fd9`.
Publisher-vocabulary output stays separate and unchanged.

## Format decided before implementation

Namespace: **`urn:spicy-docs:document-capture:xml:1`**. The root is
`DocumentCapture`, from `recordType`. All elements use this namespace;
format attributes are unqualified. Each value has a `type` attribute:
`object`, `array`, `string`, `integer`, `number`, `boolean`, or `null`.

- Object properties become elements with their exact property names when
  those match `[A-Za-z_][A-Za-z0-9_.-]*`. Other keys, including the schema's
  `$id` and publisher attribute names containing colons, use `property`
  with `name` holding a JSON string literal. This also preserves arbitrary
  extension keys, including empty keys and control characters. A property
  literally called `property` needs no `name` attribute.
- Arrays contain `item` elements in their original order. Empty arrays,
  empty objects, empty strings, null, false, zero, and absent properties
  remain distinct. No field is derived, omitted, or filled with a default.
- Ordinary strings are XML character data, with XML escaping. Strings
  containing carriage returns or characters XML 1.0 forbids use
  `encoding="json"` and an ASCII JSON string literal. PDF page separators
  are U+000C (form feed), so this rule is required by real captures. Decoding
  restores every code point; no whitespace or Unicode normalization occurs.
- Python JSON integers use `integer`; finite Python floats use `number`
  and their round-trip decimal spelling. These types preserve `1` versus
  `1.0`, float precision, and negative floating zero. Booleans have their
  own type. Non-finite floats and non-JSON Python types are refused.
  Unsupported-type diagnostics name the type and property path, never the
  value: `unsupported type Decimal at $/profile/ext/value; only JSON dict,
  list, str, int, finite float, bool and None values are supported`. Paths
  start at `$`, include array indices, and escape `~` and `/` in keys as
  `~0` and `~1` so property names remain unambiguous.
  The API works on parsed JSON values: original JSON indentation, escape
  spellings, duplicate keys, and number lexemes are outside that input.
- Decoding refuses duplicate properties, wrong namespaces, unknown format
  attributes/types, mixed content, and malformed scalar values. DTDs,
  comments, and processing instructions are refused; decoding reads only
  the supplied bytes and never follows a locator or schema URL.

The package API is `encode_capture(capture) -> bytes` and
`decode_capture(xml_bytes) -> dict` in
`src/spicy_docs/schemas/document_capture/xml.py`. It checks the format and
`DocumentCapture` version 1 identity. Parent/profile validation and Rulespec's
invariants remain separate checks; serialization preserves a capture's
stated facts without repairing them.

No value normalization was needed. Equality compares all object keys,
array positions, scalar types, string code points, and exact finite float
values, including signed zero. Escaping is reversed before comparison.

Implementation refinement: surrogate code points in Python strings or keys
are refused. They are not Unicode scalar values, and JSON decoding combines
a raw surrogate pair into a single code point, breaking exact Python string
equality. Ordinary supplementary characters such as emoji remain supported.
Cycles, nesting beyond Python's recursion limit, and integers beyond its
decimal conversion limit also refuse. These refusals affect none of the
retained captures.

## Measured inputs and byte cost

The first six inputs are under
`docs/research/document-capture-schema-2026-09-19/`; the seventh is under
`tests/fixtures/document_capture_pdf_tables/`. Their full filenames and
SHA-256 digests below identify the exact JSON bytes. The seven profiles live
under the schema directory; the captures themselves live at these paths.

| Capture filename | JSON bytes | XML bytes | Decoded JSON bytes | Extra XML bytes | XML / JSON |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bills-119hjres25enr.capture.json` | 18,638 | 39,067 | 18,638 | 20,429 | 2.10× |
| `cfr-2025-title30-vol3-sec716-2.capture.json` | 186,831 | 447,833 | 186,831 | 261,002 | 2.40× |
| `crpt-119hrpt1.capture.json` | 127,644 | 302,859 | 127,644 | 175,215 | 2.37× |
| `fr-2026-19200.capture.json` | 62,503 | 134,539 | 62,503 | 72,036 | 2.15× |
| `plaw-119publ1.capture.json` | 141,485 | 305,344 | 141,485 | 163,859 | 2.16× |
| `scotus-26a274_l537.capture.json` | 124,689 | 328,855 | 124,689 | 204,166 | 2.64× |
| `senate-page17.capture.json` | 23,919 | 60,409 | 23,919 | 36,490 | 2.53× |

| Capture filename | Input SHA-256 |
| --- | --- |
| `bills-119hjres25enr.capture.json` | `8296186d64fddedb0eaa4625006932f67f79e8940f98a264497b168b7ef24068` |
| `cfr-2025-title30-vol3-sec716-2.capture.json` | `e200e4490be487c64b81aabc018215433fba988174a5514c1c33d566488206e8` |
| `crpt-119hrpt1.capture.json` | `6271c316535f3079b3a72a959681988392458d69ff9513fefca03f6c1f6c572e` |
| `fr-2026-19200.capture.json` | `4539ffa6e4b978274d07922e0959d14bf2d1c5f76cb739e7c55698ad44a602e8` |
| `plaw-119publ1.capture.json` | `765abe4904fb74be3173c5b89f5ded16076edb4032ef55fb2f572cbbe07f2cff` |
| `scotus-26a274_l537.capture.json` | `559985811a6870abfd0146da93e73bbbd4f06847e7380f6dfec2a228ea4f1f49` |
| `senate-page17.capture.json` | `50359aed976149f8168d78aab46537c9a1cfdf14ed2db42a4cc5dde36a41fceb` |

All seven pass parent/profile validation and Rulespec invariants before and
after decoding. Full recursive equality checks property presence, array
positions, scalar types and values, including signed float zero. Re-encoding
each decoded object also yields identical XML bytes. Reserializing the
decoded JSON with the input's compact formatting happens to reproduce each
input digest; byte-identical JSON formatting is not the API guarantee.
The XML is compact UTF-8, including its declaration and final newline; the
extra bytes buy explicit types and opening/closing property tags. Compression
and throughput were not measured.

The Senate capture is the existing adapter's output for the committed
163,971-byte one-page cut, SHA-256
`20d77a2462a333f8d05bc9ef80feff8493dd5d5cb8c7146245cf76174e67798b`.
Its [fixture record](../../tests/fixtures/document_capture_pdf_tables/README.md)
pins the full PDF and cut provenance and supplies the regeneration command.
It contains 39 nodes, 46 spans, one table, three rows and 19 cells, including
empty cells, missing positions, missing boxes and unresolved observed text.
Tests additionally regenerate it from that PDF and round-trip the fresh
capture with its own time, paths and converter provenance intact.

## Proof that can fail

Twenty-five mutations to encoded XML fail full equality: node order,
extension value, span offset, span ownership, span record order, a node's
span-reference order, heading attachment, footnote attachment, span style,
cell box, schema pin, capture time, artifact digest and locator, rendition,
converter, profile pin, parent, depth, ordinal, decision, exact text, cell
position, unresolved reason and issue. Each case requires its exact expected
comparison path and reason. Parent and attachment cases reassign an existing
non-root parent reference to another existing parent; the root's null parent
stays intact. Heading and footnote cases use the committed Federal Register
capture, and the style case toggles the Senate capture's `Span.style.bold`.

Eleven injected encoder faults separately make the **unmodified positive
fixture tests** fail. The corrected node-order injection checks for a list;
the bill metadata's integer `nodes` field passes through unchanged. The probe
requires each fixture's expected comparison path and reason, checks expected
passes, and rejects errors or skipped tests. Its 77 fixture executions yield
**57 expected comparison failures, 20 expected passes, and zero probe errors**:

| Encoder fault | Positive fixture results |
| --- | --- |
| Swap two nodes | 7 failed |
| Add an extension property | 7 failed |
| Move offsets | 7 failed |
| Drop a cell's source box | 1 failed, 6 passed; only Senate has cell source boxes |
| Swap span ownership between nodes | 7 failed |
| Swap two span records | 7 failed |
| Swap two span references within a node | 7 failed |
| Reassign a non-root parent reference | 7 failed |
| Reattach a heading | 3 failed, 4 passed; CFR, Federal Register and public law have headings |
| Reattach a footnote | 1 failed, 6 passed; only Federal Register has footnotes |
| Toggle a span's bold style | 3 failed, 4 passed; CFR, slip opinion and Senate have span styles |

The six other captures include table positions where stated; those are
distinct from PDF cell source boxes. Tests compare every property the pinned
parent defines. A schema-valid supplemental Senate case covers twelve
properties absent from the real inputs: `Issue.node`, `cell.rowSpan` and
`columnSpan`, `Node.ref` and its two fields, `Span.sha256`, and all five
`UnresolvedRegion` fields. This case is test data, not a measured publisher
observation. Scalar tests distinguish null, empty values, booleans, integers,
floats, signed zero, nested extensions, unusual keys and exact Unicode.

No fields needed normalization. The CFR's two and slip opinion's four
form-feed spans require `encoding="json"`; decoding restores U+000C exactly.
Carriage returns, other XML-forbidden scalar values, and ambiguous property
names are also tested. Unsupported types, non-finite numbers, surrogate code
points, duplicate properties, wrong namespaces and malformed XML refuse.

## Reproduce and limits

The [retained receipt](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/document-capture-xml-roundtrip-2026-09-20/)
contains `measured/measurement.json`, all input/output bytes, schema/profile
pins, codec/tool digests, `mutation_probe.py`, `mutations.json`, eleven
failing-test logs with JUnit reports, and the refreshed `final-gate.log`.
The mutation receipt pins the codec, tests, probe and all seven input files.
The probe injects faults only in subprocess memory. Commands:

```sh
UV_OFFLINE=1 uv run --frozen python -m tools.analysis.measure_document_capture_xml --output /tmp/capture-xml-rerun
UV_OFFLINE=1 uv run --frozen python - < /Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/document-capture-xml-roundtrip-2026-09-20/mutation_probe.py
UV_OFFLINE=1 ./scripts/check
```

The measurement output directory must be new. The refreshed gate passed both
ruff checks and **7,135 tests, five skipped, 46 deselected**, with five existing
PyMuPDF deprecation warnings. The receipt retains the exact commands and
result lines.

This proves capture-value preservation, not publisher XML reconstruction,
PDF byte reconstruction, correct extraction, all-family coverage, or the
presence of metadata never captured. The two external 80-page Senate runs
from G2 were not inputs; the bounded committed table capture and a fresh
adapter result were. G3 and other source-completeness gaps remain separate.
Rulespec's schemas/profiles and CFR publisher XML did not change; publishing
this mapping through a future Rulespec release was not part of this task.
