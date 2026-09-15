# eCFR authority metadata

`spicy_docs.sources.cfr.authority.scan_ecfr_authority_notes` reads retained XML
bytes in one pass. It accepts API or bulk XML and retained fragments. Acquisition
checks the selected title; this reader captures what the supplied XML says.

| Callback | Source observations |
| --- | --- |
| `on_part` | Every `DIV5 TYPE="PART"`, including unnamed parts and parts without notes. |
| `on_authority` | Every `AUTH`, including empty, repeated, nested and orphan notes. |
| `on_heading` | `HEAD` directly under a structural `DIV1`–`DIV9`. |
| `on_source` | Every `SOURCE`, retaining its actual scope. |

Each observation retains expanded element names, literal decoded attributes,
root-to-parent ancestry and an element-only XPath. Text observations also expose
the nearest actual part and division. An unnamed nearest part stays unnamed.
Unnumbered `DIV` elements can wrap tables; they remain in ancestry without being
treated as numbered structural divisions.

`text` contains descendant text after XML entity decoding and newline handling.
`text_runs` separates that text at element boundaries; joining without a separator
reproduces `text`. A consumer can add spaces between runs for display. Parser
chunks, entities, comments and processing instructions do not introduce extra
run boundaries. These values are not original XML bytes or rendered body text.

```python
from spicy_docs.sources.cfr.authority import scan_ecfr_authority_notes

notes = []
result = scan_ecfr_authority_notes(retained_xml, on_authority=notes.append)
# Retain result.input_sha256 and result.input_bytes with the original XML.
```

Callbacks run before the entire input is known to be valid. Publish their results
only after a successful return. Malformed XML, unsafe declarations and exceeded
limits refuse the scan. Exceptions raised by a callback remain caller errors.
The default byte limit is 16 MiB; callers may explicitly raise it up to 256 MiB.
Observation count, nesting and simultaneously buffered text are bounded too.
The text budget excludes input bytes and records retained by callbacks.

This reader does not select a preferred authority note, promote a subpart note
to part scope, normalize citations, or decide legal meaning. `PARAUTH` and
`SECAUTH` are separate authority forms outside this explicit `AUTH` scope.
It does not replace the body text reader.

The source vocabulary follows the
[GPO eCFR XML guide](https://github.com/usgpo/bulk-data/blob/main/ECFR-XML-User-Guide.md):
AUTH (§3.8), DIV (§§3.21–3.30), HEAD/HED (§§3.58–3.60), PARAUTH (§3.78),
PSPACE (§3.82), SECAUTH (§3.91) and SOURCE (§3.95). The source excerpts in
`tests/fixtures/cfr/ecfr-authority-*.xml` retain exact byte spans followed by
explicit closing tags. `authority-provenance.json` records their input pins,
capture URLs, offsets and transformations.
