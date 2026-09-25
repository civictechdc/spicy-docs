"""Validate a retained EDIS bulk ZIP against its index and selected attachment metadata.

The browser's ZIP and index were qualified with public document 894762 on
2026-09-25 (receipt ``edis-browser-recovery-2026-09-25``). Its index link href
names the member; its displayed filename omits the middle sequence number.
This reader preserves both spellings and every index column. It neither
extracts files nor creates download jobs. The caller retains the archive pin.
"""

from __future__ import annotations

import re
import stat
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO
from zipfile import BadZipFile, ZipInfo

from spicy_docs.reading.markup import read_html_events
from spicy_docs.reading.pdf_bytes import TRAILER_WINDOW, check_pdf_bytes
from spicy_docs.reading.zip_archive import inspect_archive_stream, seekable_stream
from spicy_docs.sources.usitc_edis.records import AttachmentRecord, UsitcEdisSourceError, check_edis_id

# Caller safety bounds, not exact publisher limits. The bulk guide allows 400
# attachments plus an index and describes its size limit as "1,500 Mb (1.5 Gb)".
DEFAULT_MAX_ENTRIES = 512
DEFAULT_MAX_DECODED_BYTES = 2 * 1024**3
DEFAULT_MAX_METADATA_BYTES = 4 * 1024**2
DEFAULT_MAX_INDEX_BYTES = 4 * 1024**2
_MEMBER = re.compile(r"([0-9]{1,12})-([0-9]+)-([0-9]{1,12})\.pdf")
_LABEL = re.compile(r"([0-9]{1,12})-([0-9]{1,12})\.pdf")
_REQUIRED_COLUMNS = {"DOCUMENT ID", "FILE NAME", "SECURITY"}


@dataclass(frozen=True, slots=True)
class EdisBulkIndexRow:
    """One index row with literal columns and the ZIP member it identifies."""

    document_id: int
    attachment_id: int
    member_name: str
    member_ordinal: int
    file_label: str
    fields: tuple[tuple[str, str], ...]
    pdf_version: str


@dataclass(frozen=True, slots=True)
class EdisBulkArchive:
    """Exact index bytes, parsed rows, and the shared CRC-verified member inventory."""

    index_member_ordinal: int
    index_bytes: bytes
    rows: tuple[EdisBulkIndexRow, ...]
    inventory: dict[str, Any]


def _index_rows(body: bytes, *, max_bytes: int, max_rows: int):
    """Read one explicit table; preserve column text, link text and href separately."""
    tables = 0
    in_table = False
    rows, row, cell = [], None, None
    text, links = [], []
    for event in read_html_events(body, max_bytes=max_bytes, max_events=max_rows * 256 + 256).events:
        name, kind = event.name, event.kind
        if name == "table" and kind == "start":
            tables += 1
            if tables != 1:
                raise UsitcEdisSourceError("EDIS bulk index must contain exactly one table")
            in_table = True
        elif name == "table" and kind == "end":
            if not in_table or row is not None:
                raise UsitcEdisSourceError("EDIS bulk index table is incomplete")
            in_table = False
        elif in_table:
            if kind == "empty" and name in {"table", "tr", "th", "td", "a"}:
                raise UsitcEdisSourceError("EDIS bulk index has an empty structural element")
            if name == "tr" and kind == "start":
                if row is not None:
                    raise UsitcEdisSourceError("EDIS bulk index row is incomplete")
                row = []
            elif name == "tr" and kind == "end":
                if row is None or cell is not None:
                    raise UsitcEdisSourceError("EDIS bulk index row is incomplete")
                rows.append(row)
                if len(rows) > max_rows + 1:
                    raise UsitcEdisSourceError("EDIS bulk index exceeds its row bound")
                row = None
            elif name in {"th", "td"} and kind == "start":
                if row is None or cell is not None:
                    raise UsitcEdisSourceError("EDIS bulk index cell is outside a row or nested")
                cell, text, links = name, [], []
            elif name in {"th", "td"} and kind == "end":
                if cell != name or row is None:
                    raise UsitcEdisSourceError("EDIS bulk index cell is incomplete")
                row.append((cell, "".join(text).strip(), tuple(links)))
                cell = None
            elif name == "a" and kind == "start" and cell is not None:
                hrefs = [value for key, value in event.attributes if key == "href"]
                if len(hrefs) != 1 or not hrefs[0]:
                    raise UsitcEdisSourceError("EDIS bulk index link must state exactly one href")
                links.append(hrefs[0])
            elif kind == "text" and cell is not None:
                text.append(event.text)
    if tables != 1 or in_table or row is not None or len(rows) < 2:
        raise UsitcEdisSourceError("EDIS bulk index must contain a complete table with attachment rows")
    header, *data = rows
    columns = tuple(value for _, value, _ in header)
    if (
        not all(tag == "th" and value and not hrefs for tag, value, hrefs in header)
        or len(set(columns)) != len(columns)
        or not _REQUIRED_COLUMNS <= set(columns)
    ):
        raise UsitcEdisSourceError("EDIS bulk index columns are missing or ambiguous")
    for cells in data:
        if len(cells) != len(columns) or any(tag != "td" for tag, _, _ in cells):
            raise UsitcEdisSourceError("EDIS bulk index row differs from its columns")
        fields = tuple((column, value) for column, (_, value, _) in zip(columns, cells, strict=True))
        hrefs = [href for column, (_, _, links) in zip(columns, cells, strict=True) for href in links]
        file_links = cells[columns.index("FILE NAME")][2]
        if len(hrefs) != 1 or len(file_links) != 1:
            raise UsitcEdisSourceError("EDIS bulk index row must link exactly one file")
        yield fields, file_links[0]


class _Edges:
    """One member's first bytes and final window, gathered during the inventory's single inflate pass."""

    def __init__(self) -> None:
        self.head = b""
        self.tail = b""

    def __call__(self, chunk: bytes) -> None:
        if len(self.head) < 8:
            self.head += chunk[: 8 - len(self.head)]
        self.tail = (self.tail + chunk)[-TRAILER_WINDOW:]

    def pdf_version(self) -> str:
        """Reuse the shared PDF proof on the bounded edges; the inventory's CRC covered every byte."""
        # Padding keeps the separate header outside the trailer window, even for
        # short PDFs. The shared checker reads only the header and this final window.
        return check_pdf_bytes(
            self.head + self.tail.rjust(TRAILER_WINDOW, b"\0"), error_type=UsitcEdisSourceError, label="EDIS bulk PDF"
        )


def inspect_bulk_archive(
    stream: BinaryIO,
    *,
    byte_size: int,
    expected_attachments: Sequence[AttachmentRecord],
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_decoded_bytes: int = DEFAULT_MAX_DECODED_BYTES,
    max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES,
    max_index_bytes: int = DEFAULT_MAX_INDEX_BYTES,
) -> EdisBulkArchive:
    """Validate one retained bulk ZIP; keep the caller's stream open.

    Supply all attachments expected in this ZIP, not merely a sample. Every
    index row must be Public, identify exactly one expected attachment and
    point to its exact ZIP member. Every member must be indexed or index.html.
    Declared attachment sizes are checked when present. The shared inventory
    inflates each member once, verifying complete sizes, CRCs and digests while
    the index bytes and each PDF's bounded edges are gathered from that same
    pass. Only index bytes, edges and metadata stay in memory.

    Bounds are caller limits, not claimed publisher capacities. Seekable input
    is reused; a nonseekable input is spooled once by the shared ZIP reader.
    No input is extracted, acquired or published here.
    """
    for name, bound in (
        ("byte_size", byte_size),
        ("max_entries", max_entries),
        ("max_decoded_bytes", max_decoded_bytes),
        ("max_metadata_bytes", max_metadata_bytes),
        ("max_index_bytes", max_index_bytes),
    ):
        if type(bound) is not int or bound < 1:
            raise UsitcEdisSourceError(f"EDIS bulk {name} must be a positive integer")
    expected = {}
    for attachment in expected_attachments:
        if not isinstance(attachment, AttachmentRecord):
            raise UsitcEdisSourceError("EDIS bulk expected attachments must be AttachmentRecord values")
        key = (check_edis_id(attachment.document_id), check_edis_id(attachment.id))
        if key in expected:
            raise UsitcEdisSourceError("EDIS bulk expected attachment identity repeats")
        expected[key] = attachment
    if not expected:
        raise UsitcEdisSourceError("EDIS bulk expected attachments must not be empty")
    edges: dict[int, _Edges] = {}
    index = bytearray()

    def observe(ordinal: int, info: ZipInfo) -> Callable[[bytes], None]:
        if info.orig_filename != "index.html":
            return edges.setdefault(ordinal, _Edges())
        # The inventory refuses decoded bytes beyond the declared size, so this bounds the index.
        if info.file_size > max_index_bytes:
            raise UsitcEdisSourceError("EDIS bulk index entry exceeds max_index_bytes")
        return index.extend

    try:
        with seekable_stream(stream, byte_size=byte_size) as original:
            original.seek(0, 2)
            if original.tell() != byte_size:
                raise UsitcEdisSourceError("EDIS bulk ZIP size differs from its selected byte size")
            inventory = inspect_archive_stream(
                original,
                byte_size=byte_size,
                max_entries=max_entries,
                max_decoded_bytes=max_decoded_bytes,
                max_metadata_bytes=max_metadata_bytes,
                observe=observe,
            )
    except (ValueError, BadZipFile, RuntimeError, zlib.error) as error:
        if isinstance(error, UsitcEdisSourceError):
            raise
        raise UsitcEdisSourceError(f"EDIS bulk ZIP could not be read: {error}") from error
    members = {}
    for member in inventory["members"]:
        name = member["name"]
        mode = stat.S_IFMT(member["externalAttributes"] >> 16)
        if (
            member["isDirectory"]
            or mode not in (0, stat.S_IFREG)
            or (name != "index.html" and _MEMBER.fullmatch(name) is None)
        ):
            raise UsitcEdisSourceError("EDIS bulk ZIP contains an unexpected or unsafe member")
        if name in members:
            raise UsitcEdisSourceError("EDIS bulk ZIP repeats a member name")
        members[name] = member
    if "index.html" not in members:
        raise UsitcEdisSourceError("EDIS bulk ZIP omitted index.html")
    index_bytes = bytes(index)
    seen, linked, rows = set(), set(), []
    for fields, href in _index_rows(index_bytes, max_bytes=max_index_bytes, max_rows=max_entries):
        values = dict(fields)
        name_match, label_match = _MEMBER.fullmatch(href), _LABEL.fullmatch(values["FILE NAME"])
        if name_match is None or label_match is None or href not in members:
            raise UsitcEdisSourceError("EDIS bulk index names an unsafe or missing PDF member")
        key = (check_edis_id(int(name_match[1])), check_edis_id(int(name_match[3])))
        if values["DOCUMENT ID"] != name_match[1] or key != (int(label_match[1]), int(label_match[2])):
            raise UsitcEdisSourceError("EDIS bulk index document, filename and link identities disagree")
        if values["SECURITY"] != "Public":
            raise UsitcEdisSourceError("EDIS bulk index row is not Public")
        if key in seen or href in linked:
            raise UsitcEdisSourceError("EDIS bulk index repeats an attachment")
        if key not in expected:
            raise UsitcEdisSourceError("EDIS bulk index contains an unexpected attachment")
        member = members[href]
        if expected[key].file_size is not None and expected[key].file_size != member["byteSize"]:
            raise UsitcEdisSourceError("EDIS bulk PDF size differs from the attachment metadata")
        ordinal = member["ordinal"]
        rows.append(
            EdisBulkIndexRow(key[0], key[1], href, ordinal, values["FILE NAME"], fields, edges[ordinal].pdf_version())
        )
        seen.add(key)
        linked.add(href)
    if seen != set(expected):
        raise UsitcEdisSourceError("EDIS bulk index omitted expected attachments")
    if linked | {"index.html"} != set(members):
        raise UsitcEdisSourceError("EDIS bulk ZIP contains an unindexed PDF member")
    return EdisBulkArchive(members["index.html"]["ordinal"], index_bytes, tuple(rows), inventory)
