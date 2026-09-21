"""Annual XHTML archives: title identity from ``AUTHORITIES-*`` comments and section-label observations.

The two readers share nothing but the input shape; the header reader proves
what one member is, the section reader observes what one member states.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

from .core import (
    _CONTROL,
    ANNUAL_HEADER_BYTES,
    DEFAULT_MAX_XML_BYTES,
    UsCodeSource,
    UsCodeSourceError,
    _body,
    _limit,
)

_COMMENT = re.compile(rb"<!--(?P<value>.*?)-->", re.DOTALL)
_MARKER = re.compile(rb"\s*(?P<kind>documentid|itempath):(?P<value>.*)\Z", re.DOTALL)
_DOCUMENT_FIELD = re.compile(r"(?<!\S)([A-Za-z][A-Za-z0-9_-]*):")
_HEAD_START = re.compile(rb"<!--\s*field-start:(?P<name>[A-Za-z0-9_-]*head)\s*-->")
_SECTION_LABEL = re.compile(r"(?P<bracket>\[)?(?P<label>Secs?\.)\s+(?P<value>.*)", re.DOTALL)
_TOKEN = re.compile(r"[0-9][0-9A-Za-z.‐‑‒–—―−\x96\x97-]*")


def _comments(body: bytes) -> Iterator[re.Match[bytes]]:
    # A single advancing cursor also bounds malformed inputs containing many
    # openers: regex searching would retry the same unterminated suffix.
    cursor = 0
    while (start := body.find(b"<!--", cursor)) != -1:
        end = body.find(b"-->", start + 4)
        if end == -1:
            raise UsCodeSourceError("U.S. Code annual XHTML has an unclosed comment")
        cursor = end + 3
        comment = _COMMENT.match(body, start, cursor)
        assert comment is not None
        yield comment


@dataclass(frozen=True, slots=True)
class AnnualSectionPiece:
    raw: str
    kind: Literal["section", "range", "unparsed"]
    section: str | None = None
    range_start: str | None = None
    range_end: str | None = None


@dataclass(frozen=True, slots=True)
class AnnualSectionHeading:
    field_name: str
    html: str
    text: str
    attributes: tuple[tuple[str, str | None], ...]
    byte_span: tuple[int, int]


@dataclass(frozen=True, slots=True)
class AnnualSectionObservation:
    """One itempath and its own document comment; positions are original byte spans.

    Non-section itempaths also survive with ``section_label=None``. The caller
    retains the input bytes; spans are half-open and select complete comments
    or the heading's HTML, never offsets in a replacement-decoded string.
    """

    itempath: str
    itempath_comment: str
    itempath_span: tuple[int, int]
    document_comment: str | None
    document_comment_span: tuple[int, int] | None
    document_fields: tuple[tuple[str, str], ...]
    usckey: str | None
    section_label: str | None
    bracketed: bool
    parts: tuple[AnnualSectionPiece, ...]
    heading: AnnualSectionHeading | None
    issues: tuple[str, ...]


def _decode(value: bytes, issues: list[str]) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        if "invalid_utf8" not in issues:
            issues.append("invalid_utf8")
        return value.decode("utf-8", "replace")


def _parts(label: str) -> tuple[AnnualSectionPiece, ...]:
    result = []
    for raw in label.split(","):
        value = raw.strip()
        span = re.fullmatch(r"(\S+)\s+to\s+(\S+)", value)
        if span and _TOKEN.fullmatch(span[1]) and _TOKEN.fullmatch(span[2]):
            result.append(AnnualSectionPiece(raw, "range", range_start=span[1], range_end=span[2]))
        elif _TOKEN.fullmatch(value):
            result.append(AnnualSectionPiece(raw, "section", section=value))
        else:
            result.append(AnnualSectionPiece(raw, "unparsed"))
    return tuple(result)


class _HeadingText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.attributes: tuple[tuple[str, str | None], ...] = ()
        self.found_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.found_heading and tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.attributes = tuple(attrs)
            self.found_heading = True

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _heading(body: bytes, start: int, end: int, issues: list[str]) -> AnnualSectionHeading | None:
    field = _HEAD_START.search(body, start, end)
    if field is None:
        return None
    closing = re.compile(rb"<!--\s*field-end:" + re.escape(field["name"]) + rb"\s*-->").search(body, field.end(), end)
    if closing is None:
        issues.append("heading_field_unclosed")
        return None
    span = (field.end(), closing.start())
    html = _decode(body[span[0] : span[1]], issues)
    reader = _HeadingText()
    reader.feed(html)
    reader.close()
    return AnnualSectionHeading(field["name"].decode("ascii"), html, "".join(reader.parts), reader.attributes, span)


def _observation(
    body: bytes,
    item: re.Match[bytes],
    document: re.Match[bytes] | None,
    end: int,
) -> AnnualSectionObservation:
    issues: list[str] = []
    comment = _decode(item.group(), issues)
    marker = _MARKER.fullmatch(item["value"])
    assert marker is not None
    itempath = _decode(marker["value"].rstrip(), issues)
    document_comment = _decode(document.group(), issues) if document else None
    fields = []
    if document is not None:
        text = _decode(document["value"], issues)
        markers = list(_DOCUMENT_FIELD.finditer(text))
        for index, found in enumerate(markers):
            stop = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            fields.append((found[1], text[found.end() : stop].strip()))
    keys = [value for name, value in fields if name == "usckey"]
    if len(keys) != 1:
        issues.append("missing_usckey" if not keys else "repeated_usckey")
    elif not keys[0]:
        issues.append("empty_usckey")
    tail = itempath.rsplit("/", 1)[-1].strip()
    section = _SECTION_LABEL.fullmatch(tail)
    return AnnualSectionObservation(
        itempath,
        comment,
        item.span(),
        document_comment,
        document.span() if document else None,
        tuple(fields),
        keys[0] if len(keys) == 1 else None,
        section["label"] if section else None,
        tail.startswith("["),
        _parts(section["value"]) if section else (),
        _heading(body, item.end(), end, issues),
        tuple(issues),
    )


def scan_uscode_annual_sections(
    body: bytes,
    *,
    on_section: Callable[[AnnualSectionObservation], None],
    max_bytes: int = DEFAULT_MAX_XML_BYTES,
) -> int:
    """Visit annual itempath comments without excluding or expanding any printed label.

    A document comment belongs only to its next itempath. A subsequent itempath
    without its own document comment therefore reports a missing key. Full
    annual title/archive admission remains in ``spicy_docs.sources.uscode``;
    this raw reader also accepts bounded retained fragments.
    """
    if not callable(on_section):
        raise UsCodeSourceError("U.S. Code annual callback must be callable")
    _limit(max_bytes)
    _body(body, max_bytes, "U.S. Code annual XHTML")
    document = None
    item_document = None
    item = None
    count = 0
    for comment in _comments(body):
        marker = _MARKER.fullmatch(comment["value"])
        if marker is None:
            continue
        if item is not None:
            on_section(_observation(body, item, item_document, comment.start()))
            count += 1
            item = None
        if marker["kind"] == b"documentid":
            document = comment
        else:
            item, item_document = comment, document
            document = None
    if item is not None:
        on_section(_observation(body, item, item_document, len(body)))
        count += 1
    return count


# --------------------------------------------------------------------------- #
# annual historical archives
# --------------------------------------------------------------------------- #

#: Every comment an annual title member states about itself. All ten are present
#: in all 1,781 title members of the 31 retained zips.
ANNUAL_FIELDS = (
    "AUTHORITIES-PUBLICATION-NAME",
    "AUTHORITIES-PUBLICATION-ID",
    "AUTHORITIES-PUBLICATION-YEAR",
    "AUTHORITIES-LAWS-ENACTED-THROUGH-DATE",
    "SEARCHABLE-LAWS-ENACTED-THROUGH-DATE",
    "AUTHORITIES-USC-TITLE-NAME",
    "AUTHORITIES-USC-TITLE-ENUM",
    "AUTHORITIES-USC-TITLE-STATUS",
    "CONVERSION-PROGRAM",
    "CONVERSION-DATETIME",
)
_ANNUAL_COMMENT = re.compile(r"\s*(?P<name>[A-Z][A-Z0-9-]*):(?P<value>.*)", re.DOTALL)


@dataclass(frozen=True, slots=True)
class AnnualTitleMetadata:
    """What one annual XHTML title member says about itself, in the publisher's spelling."""

    source: UsCodeSource
    publication_name: str
    publication_id: str
    publication_year: str
    laws_enacted_through: str
    laws_enacted_through_stated: str
    title_name: str
    title_enum: str
    title_status: str
    conversion_program: str
    conversion_datetime: str
    identity_basis: tuple[str, ...] = ("publication-year:native", "title-enum:native")


class _AnnualHeaderReader(HTMLParser):
    """Read only the identity comments the generator writes above ``<body>``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}
        self.repeated: set[str] = set()

    def handle_comment(self, data: str) -> None:
        match = _ANNUAL_COMMENT.fullmatch(data)
        if match is None or match["name"] not in ANNUAL_FIELDS:
            return
        name = match["name"]
        if name in self.fields:
            self.repeated.add(name)
        self.fields[name] = match["value"].strip()


def _annual_header(body: bytes) -> dict[str, str]:
    # Identity sits in the first kilobyte; the body beyond it is not decoded at
    # all, because the 1994 edition is not valid UTF-8 (0xFF at 14,644,597 in
    # 1994usc42.htm) and reading 75 MB to learn a year would be waste besides.
    reader = _AnnualHeaderReader()
    reader.feed(body[:ANNUAL_HEADER_BYTES].decode("utf-8", "replace"))
    reader.close()
    if reader.repeated:
        raise UsCodeSourceError("U.S. Code annual title repeats an identity comment")
    missing = [name for name in ANNUAL_FIELDS if not reader.fields.get(name)]
    if missing:
        raise UsCodeSourceError(f"U.S. Code annual title lacks an identity comment: {missing[0]}")
    for name, value in reader.fields.items():
        if not value.isascii() or _CONTROL.search(value):
            raise UsCodeSourceError(f"U.S. Code annual title identity comment is not printable ASCII: {name}")
    return reader.fields


def validate_annual_title_html(
    body: bytes, *, year: int | None = None, max_bytes: int = DEFAULT_MAX_XML_BYTES
) -> AnnualTitleMetadata:
    """Prove one annual member's own edition and title from its ``AUTHORITIES-*`` comments.

    ``year`` checks the stated publication year when the caller has one to check
    against. It is optional because the publisher's own archives carry members
    that state an earlier year: the eliminated Title 50 Appendix is reissued
    unchanged, so 2016 and 2017 both ship a member stating 2015.
    """
    _limit(max_bytes)
    data = _body(body, max_bytes, "U.S. Code annual title")
    if not data.lstrip()[:15].lower().startswith(b"<!doctype html"):
        raise UsCodeSourceError("U.S. Code annual title does not begin with an XHTML doctype")
    if b"</html>" not in data[-4096:]:
        raise UsCodeSourceError("U.S. Code annual title is not closed by </html>")
    fields = _annual_header(data)
    stated_year = fields["AUTHORITIES-PUBLICATION-YEAR"]
    if not stated_year.isdigit() or len(stated_year) != 4:
        raise UsCodeSourceError("U.S. Code annual title publication year is not a four-digit year")
    if year is not None and stated_year != str(year):
        raise UsCodeSourceError("U.S. Code annual title publication year differs from the request")
    return AnnualTitleMetadata("annual-title", *(fields[name] for name in ANNUAL_FIELDS))
