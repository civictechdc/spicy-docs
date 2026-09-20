# Reversible XML for DocumentCapture

The [vocabulary decision](../decisions.md#reversible-capture-xml-names-the-captures-structures)
chooses capture-shaped XML for G1. Publisher-vocabulary output stays separate;
the CFR serializer is the existing example. Implementation and measurements
follow this decision using committed inputs only, with zero requests.

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
  are U+000C (form feed), so this rule is required by real captures. JSON
  escaping also preserves lone surrogates in extension values. Decoding
  restores every code point; no whitespace or Unicode normalization occurs.
- Python JSON integers use `integer`; finite Python floats use `number`
  and their round-trip decimal spelling. These types preserve `1` versus
  `1.0`, float precision, and negative floating zero. Booleans have their
  own type. Non-finite floats and non-JSON Python types are refused.
  The API works on parsed JSON values: original JSON indentation, escape
  spellings, duplicate keys, and number lexemes are outside that input.
- Decoding refuses duplicate properties, wrong namespaces, unknown format
  attributes/types, mixed content, and malformed scalar values. DTDs,
  comments, and processing instructions are refused; decoding reads only
  the supplied bytes and never follows a locator or schema URL.

The package API will be `encode_capture(capture) -> bytes` and
`decode_capture(xml_bytes) -> dict` in
`src/spicy_docs/schemas/document_capture/xml.py`. It checks the format and
`DocumentCapture` version 1 identity. Parent/profile validation and Rulespec's
invariants remain separate checks; serialization preserves a capture's
stated facts without repairing them.

No value normalization is planned. Equality must compare all object keys,
array positions, scalar types, string code points, and exact finite float
values, including signed zero. Escaping is reversed before comparison.
