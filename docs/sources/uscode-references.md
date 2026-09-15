# Read U.S. Code references and source credits

`scan_uscode_references` reads retained XML and passes literal observations to
your callbacks. Keep the input bytes and their digest beside saved results.
Use [the U.S. Code acquisition routes](uscode.md) to fetch and check a title's
identity first. This reader also accepts XML fragments without title metadata.

```python
from spicy_docs.sources.uscode_references import scan_uscode_references

references, credits = [], []
counts = scan_uscode_references(
    xml_bytes,
    on_reference=references.append,
    on_source_credit=credits.append,
)
```

For large titles, callbacks can write to temporary output instead of lists.
Commit that output only after the scan returns successfully. Malformed trailing
XML can fail after earlier callbacks received observations.

Each reference includes the original unqualified `href`, all element attributes and its
ancestors. Empty, fragment, relative and unfamiliar hrefs survive. A `ref`
without `href` also survives, including its `idref`; `None` and `""` remain
distinct. References arrive in element start order.

Each source credit includes its exact decoded descendant text, attributes and
ancestors. Whitespace, unusual prose, empty credits and missing section
identifiers survive. Credits arrive in element close order. A nested section
without an identifier remains the nearest section; the reader does not borrow
an outer section's identifier.

`element.source_xpath` uses positions among all element siblings:
`/*[1]/*[2]` selects the root's second element child. Comments and processing
instructions do not count. Expanded namespace names remain in `element.tag`
and attribute names. These paths locate XML elements, not byte or text offsets.
The local names `ref` and `sourceCredit` select observations in any namespace;
callers can inspect the expanded names to apply stricter namespace policies.

The reader uses the shared XML scanner, with no document tree or external
entity loading. Defaults bound input at 128 MiB, depth at 256, total reference
and credit observations at one million, and text buffered across open credits
at 4,194,304 characters. Nested credit text counts once per open credit.
Only requested credit text is buffered; caller-owned output has separate costs.

SpicyDocs records what the XML states. RefSpec keeps citation classification,
target resolution, historical labels, whitespace and dash normalization, and
the rules that select an enacting law from a source credit.
