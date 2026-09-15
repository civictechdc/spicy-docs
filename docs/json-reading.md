# JSON source values and record positions

Use `spicy_docs.sources.json_input` for captured UTF-8 JSON. It retains source
values and refuses duplicate decoded keys and non-finite number constants.
RulespecArtifacts owns canonical encoding and artifact identity; these readers
do not encode, normalize, or publish artifacts.

```python
from spicy_docs.sources.json_input import read_json_records

source = b' [ {"value":1.00e+2}, null ] '
read = read_json_records(
    source,
    source="Example records",
    error_type=ValueError,
    number_policy="decimal",
    max_bytes=1024,
)
for span in read.records:
    print(source[span.byte_start : span.byte_end])
```

`JsonRecordRead.value` is the decoded root. Its `records` tuple contains a
`JsonRecordSpan` for each top-level array member. A non-array root has one span;
an empty array has none. An empty input refuses. Nested arrays and objects stay
within their containing record. Unknown keys, nulls, empty values, source order,
large integers, and decoded escaped surrogate code units remain source facts.

Each span has half-open `char_start`/`char_end` positions in the decoded source
text and `byte_start`/`byte_end` positions in the original UTF-8 bytes. The span
includes the complete JSON value and excludes surrounding whitespace and array
delimiters. Original number spelling, escapes, and internal whitespace survive
in that exact source slice. Character positions count Python Unicode characters,
not bytes or positions within a decoded string value.

Choose the number policy explicitly:

| Policy | Decoded numbers | Refusals |
| --- | --- | --- |
| `integer` | Python integers, including values above common artifact limits | Decimal and exponent notation, even `1e0`; non-finite constants |
| `decimal` | Python integers and `Decimal` for decimal/exponent notation | Non-finite constants and unsupported decoder exponents |
| `finite-float` | Python integers and finite binary floats | Non-finite constants and float overflow |

Finite floats can round or underflow, and integer `-0` becomes `0`. Original
source bytes retain those number lexemes. Keeping escaped surrogate code units
does not establish that a value is suitable for another format or domain.
Invalid UTF-8 and a UTF-8 byte-order mark refuse.

`max_bytes` is required. Defaults are 100,000 JSON values and depth 64; use
explicit positive `max_nodes` and `max_depth` values for other bounded sources.
The root counts as one value at depth zero; array members and object values
count separately, including unknown fields. Object key strings do not add
nodes. The complete input must pass before any result returns.

Top-level array members decode once, with cumulative bounds checked before
their values and spans are retained. Byte positions use disjoint source slices,
without an integer offset for every character. A single nested record still
must be decoded before its node/depth check, and the standard decoder can
refuse its own recursion or numeric limits first. Input bounds are not a
process-memory or CPU sandbox.

Use `load_bounded_json` when positions are unnecessary. Existing
`load_integer_json`, `load_decimal_json`, and `load_finite_json` retain their
source-specific diagnostics for callers that already bound acquisition. All
readers share the same duplicate-key and number callbacks. The record reader
adds source positions; it does not adopt a second JSON grammar.
