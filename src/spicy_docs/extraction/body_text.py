"""One text derivation per fetched rendition, so every caller reads one text.

``sources.govinfo.bodies.BODY_PREFERENCE`` decides *which* rendition a caller
fetches; this module decides what that rendition's bytes mean as text. There
is one derivation per rendition and no second stripper:

- ``xml`` -- ``markup-reader``, over ``reading.markup.read_xml_events``.
- ``htm`` -- ``markup-reader``, over ``reading.markup.read_html_events``.
- ``txt`` -- ``text-rendition-cleanup``, the shared rules below and nothing
  else.
- ``pdf`` -- ``pdf-extraction-gpo-normalized``: ``DocumentExtractor`` with
  ``NativeText``, then ``gpo_normalize.normalize_gpo_pages``.

It lives in ``extraction`` because the PDF branch *is* extraction and because
``gpo_normalize`` -- the only other text-derivation step in this repository --
already lives here; both branches of the shared glyph rule then sit in one
package. It imports no ``sources`` module: the fetched body is read
structurally (:class:`FetchedBody`), so ``sources`` keeps depending on
``extraction`` and not the other way round. ``RENDITION_MEDIA_TYPES`` restates
the media types ``sources.govinfo.bodies.PACKAGE_BODY_FORMATS`` states for the
same four names, and ``tests/test_body_text.py`` pins the two equal rather
than letting one import the other.

**What the non-PDF renditions actually carry**, measured 2026-09-19 over four
keyless GovInfo ``htm`` bodies (CRPT-119hrpt1, -119hrpt105, -113hrpt135,
-113srpt77), one ``txt`` body (CDIR-2026-02-20, the only collection measured
that offers one) and three BILLS ``xml`` bodies. Only what was counted above
zero has a rule; see ``RENDITION_CLEANUP_RULES`` for the table and
``docs/sources/govinfo-bodies.md`` for the per-file numbers.

- The ``htm`` body is GPO's plain text inside ``<html><title>..</title>
  <body><pre>``. There is no HTML formatting to read: the four measured
  bodies contain no tag but that wrapper and GPO's own ``<all>`` and
  ``<graphic(s)>`` locator markers, which carry no text and so leave nothing
  behind. Whitespace inside a ``<pre>`` is the document's layout -- it is what
  keeps an appropriations account row's label, leader dots and amount on one
  line -- so the markup reader's text is taken verbatim and **no blank line is
  dropped**: ``report_blocks.parse_agency_blocks`` decides a header has a body
  by whether the lines under it are blank.
- The ``txt`` body is the same text with CRLF line endings (27,717 of them in
  CDIR-2026-02-20) and no wrapper at all.
- A BILLS ``xml`` body declares an external DOCTYPE (``<!DOCTYPE bill PUBLIC
  ... "bill.dtd">``), which ``read_xml_events`` refuses unless a caller says
  otherwise, so this module allows it explicitly. Nothing is ever fetched for
  it: the reader never loads an external resource and still refuses every
  entity declaration.
- None of those eight bodies carries a ``[[Page N]]`` marker, a form feed, a
  ``VerDate`` footer or a non-breaking space. Those are PDF artifacts, handled
  in the PDF branch by ``normalize_gpo_pages``; no rule is written for them
  here, because there is nothing measured to write one against.

For body bytes ``B`` and its derived text ``T``: every branch is ``O(B)`` time
and ``O(B + T)`` space, one pass per rule. This module makes no network
request and writes no file.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from spicy_docs.reading.markup import MarkupRead, read_html_events, read_xml_events

from .gpo_normalize import GpoCleanupRecord, normalize_gpo_glyphs, normalize_gpo_pages
from .model import PageResult

#: The derivation each rendition gets. Keys are
#: ``sources.govinfo.bodies.PACKAGE_BODY_FORMATS``'s own names.
RENDITION_DERIVATIONS: dict[str, str] = {
    "xml": "markup-reader",
    "htm": "markup-reader",
    "txt": "text-rendition-cleanup",
    "pdf": "pdf-extraction-gpo-normalized",
}

#: The media types each rendition may arrive as, restated from
#: ``PACKAGE_BODY_FORMATS`` rather than imported (see the module docstring).
RENDITION_MEDIA_TYPES: dict[str, tuple[str, ...]] = {
    "htm": ("text/html",),
    "xml": ("application/xml", "text/xml"),
    "txt": ("text/plain",),
    "pdf": ("application/pdf",),
}

#: HTML elements whose text is document metadata, not body text. Measured:
#: ``<title>`` is present in all four GovInfo ``htm`` bodies and restates the
#: report's own printed title (591, 703, 80 and 77 characters); keeping it
#: would put a second, differently-wrapped copy of the heading above the
#: document's first line. No measured body carries a ``<script>`` or
#: ``<style>``, so neither is named here.
METADATA_ELEMENTS = frozenset({"title"})

_PDF_MEDIA_TYPE = "application/pdf"


class BodyTextError(ValueError):
    """A rendition cannot be turned into text under its own derivation."""


@dataclass(frozen=True, slots=True)
class RenditionCleanupRule:
    """One named rule, the artifact it removes and the renditions it runs on."""

    name: str
    artifact: str
    renditions: tuple[str, ...]


#: Every rule the non-PDF branches apply, each measured above zero on a real
#: publisher response (module docstring). The PDF branch's own rules are
#: ``gpo_normalize.METADATA_RULES``; nothing is duplicated between the two.
RENDITION_CLEANUP_RULES: tuple[RenditionCleanupRule, ...] = (
    RenditionCleanupRule(
        "metadata_element",
        "HTML <title>: document metadata restating the printed heading",
        ("htm",),
    ),
    RenditionCleanupRule(
        "element_line_break",
        "An XML element boundary, kept as a line break so text from two elements never runs together",
        ("xml",),
    ),
    RenditionCleanupRule(
        "whitespace_only_line",
        "XML pretty-print indentation between elements, which is formatting and not content; "
        "never applied to htm, whose blank lines are the document's own layout",
        ("xml",),
    ),
    RenditionCleanupRule(
        "line_ending",
        "CRLF/CR line endings (27,717 in CDIR-2026-02-20.txt)",
        ("xml", "htm", "txt"),
    ),
    RenditionCleanupRule(
        "end_of_text_marker",
        "GPO's trailing U+001A SUB terminator (1 each in the CRPT-113hrpt135 and -113srpt77 htm bodies)",
        ("xml", "htm", "txt"),
    ),
    RenditionCleanupRule(
        "gpo_quote_pair",
        "GPO's ``/'' typewriter quote pairs, collapsed to one double quote so the htm and PDF "
        "renditions of one document spell a quotation the same way",
        ("xml", "htm", "txt"),
    ),
    RenditionCleanupRule(
        "trailing_space",
        "Trailing spaces left by GPO's fixed-width columns (19,077 lines in CDIR-2026-02-20.txt); "
        "leading spaces are the layout and are kept",
        ("xml", "htm", "txt"),
    ),
)


@dataclass(frozen=True, slots=True)
class RenditionCleanup:
    """What the markup and text branches read and removed, rule by rule.

    Markup counts are zero for a ``txt`` body, which has no markup to read;
    ``element_line_breaks`` and ``whitespace_only_lines`` are zero outside the
    XML branch, and ``metadata_element_chars`` outside the HTML branch. Every
    field is a count of what was found, so a hosted row can say how its text
    was made without holding the bytes.

    ``quote_pairs_collapsed`` counts the typewriter quote pairs the rendition
    spelled -- two backticks opening, two apostrophes closing -- which is how
    GPO writes a quotation everywhere but its PDF. A PDF's curly-doubled
    spelling is collapsed by the same shared rule but is not counted here; it
    belongs to the PDF branch, whose record is a ``GpoCleanupRecord``.
    """

    markup_events: int
    markup_elements: int
    text_events: int
    metadata_element_chars: int
    element_line_breaks: int
    whitespace_only_lines: int
    line_endings_normalized: int
    end_of_text_markers: int
    quote_pairs_collapsed: int
    trailing_space_lines: int


@dataclass(frozen=True, slots=True)
class BodyText:
    """One rendition's parser-ready text and the account of how it was made.

    ``pages`` is the per-page text for a PDF, in reading order, and ``None``
    for every other rendition: a GovInfo ``htm``, ``xml`` or ``txt`` body
    states no page boundary (measured: no form feed and no ``[[Page N]]``
    marker in any of the eight bodies sampled), so page attribution would be
    invented. ``record`` is a :class:`RenditionCleanup` for the markup and
    text branches and a ``GpoCleanupRecord`` for the PDF branch.
    """

    text: str
    pages: tuple[str, ...] | None
    rendition: str
    media_type: str
    byte_size: int
    derivation: str
    record: GpoCleanupRecord | RenditionCleanup


class _BodyIdentity(Protocol):
    media_type: str
    byte_size: int


class _BodyCapture(Protocol):
    body: bytes


class FetchedBody(Protocol):
    """The three facts ``body_text`` needs from a fetched body.

    ``sources.govinfo.body_acquisition.GovInfoPackageBody`` satisfies this, and
    so would a bill-text body that states the same three things, which is why
    it is structural rather than an import: ``extraction`` stays below
    ``sources``.
    """

    format: str
    body: _BodyIdentity
    body_capture: _BodyCapture


class _Extractor(Protocol):
    def extract(self, source: bytes, *, media_type: str) -> Iterator[PageResult]: ...


def _checked_rendition(rendition: object) -> str:
    if not isinstance(rendition, str) or rendition not in RENDITION_DERIVATIONS:
        supported = ", ".join(RENDITION_DERIVATIONS)
        raise BodyTextError(f"rendition must be one of {supported}")
    return rendition


def _checked_media_type(rendition: str, media_type: str | None) -> str:
    """Accept the rendition's own media types, or name the disagreement.

    A body whose media type does not match the rendition it claims is the
    publisher answering with something else; the acquirer already refuses it,
    and this refuses it again for a caller holding bytes from elsewhere.
    """
    allowed = RENDITION_MEDIA_TYPES[rendition]
    if media_type is None:
        return allowed[0]
    exact = media_type.partition(";")[0].strip().casefold()
    if exact not in allowed:
        raise BodyTextError(f"{rendition} body media type is {exact or 'absent'}, not one of {', '.join(allowed)}")
    return exact


def _cleanup(raw: str) -> tuple[str, dict[str, int]]:
    """The rules every non-PDF rendition shares, with what each one found.

    Each rule is counted against the text as that rule sees it, so two rules
    never claim the same character: trailing spaces are counted after the line
    endings are normalized, or every CRLF line would also read as one.
    """
    text = normalize_gpo_glyphs(raw)
    counts = {
        "line_endings_normalized": raw.count("\r"),
        "end_of_text_markers": text.count("\x1a"),
        # One pair is one collapsed quotation mark, whichever way GPO spelled
        # it; normalize_gpo_glyphs has already collapsed them, so they are
        # counted on the way in.
        "quote_pairs_collapsed": raw.count("``") + raw.count("''"),
        "trailing_space_lines": sum(1 for line in text.split("\n") if line.strip() and line != line.rstrip()),
    }
    text = text.replace("\x1a", "")
    return "\n".join(line.rstrip() for line in text.split("\n")), counts


def _markup_text(read: MarkupRead, *, xml: bool) -> tuple[str, dict[str, int]]:
    """Walk one markup read's text in document order.

    For XML an element boundary closes the current line, so text from two
    elements never runs together and the document's own nesting survives as
    line breaks; the indentation between elements is formatting and its
    whitespace-only lines go. For HTML the text is taken verbatim: a GovInfo
    body is a ``<pre>`` block whose whitespace *is* the layout.
    """
    parts: list[str] = []
    text_events = metadata_chars = breaks = depth = 0
    for event in read.events:
        if not xml and event.name in METADATA_ELEMENTS:
            # Only a container swallows text: a self-closing ``<title/>`` has
            # no end tag, so counting it open would swallow the whole body.
            if event.kind == "start":
                depth += 1
            elif event.kind == "end":
                depth = max(depth - 1, 0)
        if event.kind == "text" and event.text is not None:
            if depth:
                metadata_chars += len(event.text)
                continue
            text_events += 1
            parts.append(event.text)
        elif xml and event.kind in {"start", "empty", "end"} and parts and not parts[-1].endswith("\n"):
            parts.append("\n")
            breaks += 1
    text, counts = _cleanup("".join(parts))
    blank = 0
    if xml:
        lines = text.split("\n")
        kept = [line for line in lines if line]
        blank = len(lines) - len(kept)
        text = "\n".join(kept)
    counts |= {
        "markup_events": len(read.events),
        "markup_elements": read.element_count,
        "text_events": text_events,
        "metadata_element_chars": metadata_chars,
        "element_line_breaks": breaks,
        "whitespace_only_lines": blank,
    }
    return text, counts


def _pdf_text(data: bytes, extractor: _Extractor | None) -> tuple[str, tuple[str, ...], GpoCleanupRecord]:
    if extractor is None:
        from .api import DocumentExtractor, NativeText

        extractor = DocumentExtractor(NativeText())
    raw = tuple(result.text for result in extractor.extract(data, media_type=_PDF_MEDIA_TYPE))
    if not raw:
        raise BodyTextError("pdf body yielded no page")
    pages, record = normalize_gpo_pages(raw)
    # One "\n" per page boundary, the same join report_blocks._flatten uses,
    # so a caller that passes `text` and one that passes `pages` agree.
    return "\n".join(pages), pages, record


def rendition_text(
    data: bytes,
    *,
    rendition: str,
    media_type: str | None = None,
    byte_size: int | None = None,
    extractor: _Extractor | None = None,
) -> BodyText:
    """Derive parser-ready text from one rendition's exact bytes.

    ``rendition`` is one of ``xml``, ``htm``, ``txt`` or ``pdf``; the
    derivation it gets is ``RENDITION_DERIVATIONS[rendition]`` and is never
    inferred from the bytes. ``media_type`` is checked against the rendition
    when given. ``byte_size`` defaults to ``len(data)`` and exists so a caller
    holding the publisher's own stated size can record that instead.

    ``extractor`` replaces the PDF branch's default
    ``DocumentExtractor(NativeText())`` -- for a test, or for a document whose
    pages need another strategy. It is imported only when a PDF arrives, so
    reading a text rendition loads no PDF library.
    """
    if not isinstance(data, bytes) or not data:
        raise BodyTextError("body must be nonempty bytes")
    name = _checked_rendition(rendition)
    exact_media_type = _checked_media_type(name, media_type)
    size = len(data) if byte_size is None else byte_size
    if name == "pdf":
        text, pages, gpo_record = _pdf_text(data, extractor)
        return BodyText(
            text=text,
            pages=pages,
            rendition=name,
            media_type=exact_media_type,
            byte_size=size,
            derivation=RENDITION_DERIVATIONS[name],
            record=gpo_record,
        )
    if name == "txt":
        try:
            raw = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise BodyTextError("txt body must be UTF-8") from error
        text, counts = _cleanup(raw)
        counts |= {
            "markup_events": 0,
            "markup_elements": 0,
            "text_events": 0,
            "metadata_element_chars": 0,
            "element_line_breaks": 0,
            "whitespace_only_lines": 0,
        }
    else:
        xml = name == "xml"
        # A BILLS XML body declares an external DOCTYPE; allowing it is a
        # statement that the declaration is inert, not a fetch: the reader
        # never loads the resource and still refuses every entity.
        read = read_xml_events(data, allow_external_doctype=True) if xml else read_html_events(data)
        text, counts = _markup_text(read, xml=xml)
    return BodyText(
        text=text,
        pages=None,
        rendition=name,
        media_type=exact_media_type,
        byte_size=size,
        derivation=RENDITION_DERIVATIONS[name],
        record=RenditionCleanup(**counts),
    )


def body_text(body: FetchedBody, *, extractor: _Extractor | None = None) -> BodyText:
    """Derive text from a fetched body, reading its rendition off the body itself.

    Takes anything that states the three facts :class:`FetchedBody` names --
    ``GovInfoPackageBody`` does -- so the chosen format, its media type and
    its exact bytes come from the fetch that proved them rather than from a
    caller's guess. All the work is :func:`rendition_text`'s.
    """
    for attribute in ("format", "body", "body_capture"):
        if not hasattr(body, attribute):
            raise BodyTextError(f"body must state {attribute}; see FetchedBody")
    return rendition_text(
        body.body_capture.body,
        rendition=body.format,
        media_type=body.body.media_type,
        byte_size=body.body.byte_size,
        extractor=extractor,
    )


__all__ = [
    "METADATA_ELEMENTS",
    "RENDITION_CLEANUP_RULES",
    "RENDITION_DERIVATIONS",
    "RENDITION_MEDIA_TYPES",
    "BodyText",
    "BodyTextError",
    "FetchedBody",
    "RenditionCleanup",
    "RenditionCleanupRule",
    "body_text",
    "rendition_text",
]
