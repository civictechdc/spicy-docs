# XML and HTML source events

Use `spicy_docs.sources.markup` when you need decoded text linked to original
source bytes. These core readers require no optional backend or network access.
They return observations; the caller decides which text is visible, which tags
are headings, and how to lay out paragraphs or tables.

```python
from spicy_docs.sources.markup import read_xml_events

source = b"<p>A<![CDATA[B]]> &amp; C</p>"
read = read_xml_events(source)
for event in read.events:
    if event.kind == "text":
        original = source[event.byte_start : event.byte_end]
        print(event.text, original, event.is_literal)
```

The result contains ordered events, an element count, the first element's
literal name, and its expanded XML name. `root_expanded_name` is `None` for HTML.

| Event field | Meaning |
| --- | --- |
| `kind` | `start`, `empty`, `end`, `text`, `comment`, `pi`, or `declaration` |
| `name` | XML qualified name or HTMLParser's lowercase tag name, when present |
| `attributes` | Ordered parsed attributes; duplicate HTML attributes and valueless attributes survive |
| `namespace_declarations` | XML declarations on this start element, separate from ordinary attributes |
| `text` | Decoded character data or parser-supplied comment/processing-instruction content |
| `byte_start` | Position in the original captured bytes |
| `byte_end` | Exclusive end of a text event's source span; absent for other event kinds |
| `is_literal` | Whether that exact source span equals `text.encode("utf-8")` |

XML empty elements produce a start and an end event; the end position is the
parser's synthetic closing position. HTML `<p/>` produces `empty`; `<br>`
produces `start`. Structural positions are anchors, not full markup spans.
XML declarations expose version, declared encoding, and standalone choice as
attributes; absent optional declaration fields remain absent. An accepted
DOCTYPE has `name="doctype"` and attributes for its literal `name`, `system`,
and `public` values when present. Its position is Expat's declaration anchor,
not a full source span.

Text spans exclude CDATA delimiters, comments, and processing instructions.
Character references keep their full original spelling; a reference decoded
to an empty string still has an event and a nonempty source span. Adjacent
literal text is coalesced independently of feed chunks and parser callbacks.
Changed entities, normalized XML line endings, and intervening markup remain
separate. If a caller later trims or normalizes a text event, it must check the
emitted bytes again before using exact sub-range offsets.

XML honors its encoding declaration, including supported UTF-16 and Latin-1
inputs. Positions still address original bytes. A UTF-16 text span generally
has `is_literal=False` because it is compared to decoded UTF-8 output. XML must
be namespace-valid: an undeclared prefix refuses. DTDs refuse by default. Choose
`allow_external_doctype=True` for sources such as congressional bill XML that
declare an external DTD. That declaration remains inert: no external resources
are fetched. Internal subsets, entity declarations, and unresolved entities
still refuse under that explicit choice.

HTML must be UTF-8. It uses the standard library's tolerant HTML grammar,
including malformed closing tags. This reader does not construct a browser DOM,
infer missing tags, suppress head/script/style, or insert a break for `<br>`.
The caller retains those policies. Source bytes retain lexical spelling that
the parser normalizes, such as HTML tag case and attribute quotes.

Empty HTML returns no events, zero elements, and absent root names; empty XML
refuses. All bounds must still be positive integers for an empty HTML read.

Defaults are 64 MiB of input, 1,000,000 emitted events, and nesting depth 256.
Set `max_bytes`, `max_events`, and `max_depth` explicitly for other bounded
inputs. A malformed or over-limit read raises `MarkupReadError` and returns no
partial result. The parser retains the supplied body and bounded event list;
these guards are not a CPU or process-memory sandbox.

The positioned reader improves on former DocSpec spans: CDATA delimiters and
HTML comments/processing instructions no longer extend preceding text spans,
and callback boundaries no longer split ordinary literal runs. Applications
adopting it must version their mapping configuration and qualify the resulting
evidence. Display formatting remains the application's decision.
