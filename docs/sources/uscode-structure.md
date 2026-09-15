# Read retained U.S. Code structure

SpicyDocs reads publisher structure once so applications can reuse it. Give
these readers retained XML or annual XHTML bytes. Their callbacks return
literal identifiers, headings and source positions; your application saves the
rows and the original input.

Use the [U.S. Code acquisition readers](uscode.md) first when you need to
prove a title's identity or an archive's membership. These raw readers also
accept fragments and make no claim about a complete edition.

## XML sections, chapters and section parts

```python
from spicy_docs.sources.uscode.structure import scan_uscode_structure

sections, parts, chapters = [], [], []
counts = scan_uscode_structure(
    retained_xml,
    on_section=sections.append,
    on_section_part=parts.append,
    on_chapter=chapters.append,
)
```

For large inputs, write each observation from the callback instead of keeping
lists. Callbacks run when an element closes. Treat their output as provisional
until the scan succeeds; later malformed XML invalidates the read.

Each observation retains its expanded XML tag, every attribute, ancestors,
direct `num` and `heading` text, and their attributes. Its `source_xpath` is a
namespace-independent element position: `/*[1]/*[2]` selects the root's second
element child. Comments and text nodes do not change that position.

Structural elements belong to the OLRC U.S. Code namespace or have no namespace.
A foreign namespace's `section` is not a U.S. Code section. This intentionally
tightens RefSpec's former localname-only inventory; a foreign element alone
cannot establish that a citation target exists. Reference observations still
retain foreign markup and its full namespace for the receiver to interpret.

The reader preserves these distinctions:

- An absent `status` remains `None`; it does not become `current`.
- The complete `identifier` survives alongside its whitespace-separated
  pieces. Recognized coordinates keep their case and Unicode dashes; unknown
  pieces stay present with `kind=None`.
- Ranges such as `s1...1j` and `ch1...3` retain both endpoints without expansion.
- Chapter identifiers may include intermediate subtitles and parts.
- Appendix identifiers carry their literal title suffix and `appendix=True`.
  Ancestor elements also preserve an appendix context where one is present.
- A section part means an identifier one path component below `/s…`. Its
  actual element may be `paragraph`, `subsection` or another source tag.
- Longer markers precede `s` (section): `st` (subtitle), `sch` (subchapter),
  `sp`/`spt` (subpart) and `sd` (subdivision). `/stI/ch1` identifies a chapter,
  while `/s1/ch1` and `/sa/ch1` retain section-part coordinates. The
  [USLM 1.0 guide, section 12.4](https://github.com/usgpo/uslm/blob/main/USLM-User-Guide.md#124-referencing-nomenclature)
  defines case-insensitive markers; the reader also recognizes OLRC's `spt`
  spelling. The guard preserves the raw case of each captured coordinate.
- Section and chapter elements without identifiers remain observations,
  including structures quoted inside notes. Applications choose which qualify
  for an existence or citation index.

The default input limit is 128 MiB. XML safety and depth limits come from the
shared XML scanner. A direct number or heading exceeding 65,536 characters
refuses the read.

## Annual section labels

```python
from spicy_docs.sources.uscode.annual import scan_uscode_annual_sections

observations = []
scan_uscode_annual_sections(retained_xhtml, on_section=observations.append)
```

Every `itempath` comment survives, including non-section paths and bracketed
stubs. Section labels yield literal exact, range or unparsed pieces. The reader
does not expand lists or ranges into unstated section numbers.

An observation pairs the itempath with its preceding `documentid` comment,
once. A following itempath without a new document comment reports a missing
key. Repeated and empty `usckey` fields remain visible and produce issue codes.
The full comments and other document fields survive; `usckey` is never decoded
into a legal status.

Headings retain their source field name, HTML, visible text and attributes.
Positions are half-open **byte spans in the original input**, including when
invalid UTF-8 requires replacement decoding. That case reports `invalid_utf8`;
the retained bytes remain available through the spans. An unclosed heading
field reports an issue, and an unclosed comment refuses the scan.

RefSpec decides what attests a section, whether to exclude bracketed stubs or
appendices, and how to normalize identifiers. SpicyDocs supplies the observations
needed to make and check those decisions.
