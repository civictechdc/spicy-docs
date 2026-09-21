"""Literal code sentences and tables from the retained BILLSTATUS Markdown guide."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from itertools import pairwise

_TABLES = {
    "# 3. Action Code Element Possible Values": "3",
    "# 4. Actions Type Element Possible Values": "4",
    "# 5. Mapping of LOC Summaries Version Codes and  Action Description Text": "5",
    "# 6. Title Type Possible Values": "6",
}
_BILL_TYPE = "### `<billType>`"
_INTRO = "## 1.1. Bill Types"
_VERSION = "### `<version>`"
_SENTENCE = re.compile(rb"Bill type \(Possible values are (.+)\)\.")
_SEPARATOR = re.compile(r":?-+:?")


class BillStatusGuideError(ValueError):
    """The retained guide cannot be read within the supported source shape/bounds."""


@dataclass(frozen=True, slots=True)
class BillStatusGuideText:
    """Exact UTF-8 source span; byte_end is exclusive and lines are one-based."""

    text: str
    line_number: int
    byte_start: int
    byte_end: int


@dataclass(frozen=True, slots=True)
class BillStatusGuideCell:
    raw: BillStatusGuideText
    value: str
    bold: bool


@dataclass(frozen=True, slots=True)
class BillStatusGuideRow:
    raw: BillStatusGuideText
    cells: tuple[BillStatusGuideCell, ...]


@dataclass(frozen=True, slots=True)
class BillStatusGuideContext:
    heading: BillStatusGuideText
    text: BillStatusGuideText


@dataclass(frozen=True, slots=True)
class BillStatusBillTypes:
    heading: BillStatusGuideText
    sentence: BillStatusGuideText
    values: tuple[BillStatusGuideCell, ...]


@dataclass(frozen=True, slots=True)
class BillStatusGuideTable:
    section_number: str
    heading: BillStatusGuideText
    context: BillStatusGuideText
    header: BillStatusGuideRow
    separator: BillStatusGuideRow
    rows: tuple[BillStatusGuideRow, ...]


@dataclass(frozen=True, slots=True)
class BillStatusGuide:
    input_sha256: str
    input_bytes: int
    bill_type_statements: tuple[BillStatusBillTypes, ...]
    bill_type_introductions: tuple[BillStatusGuideContext, ...]
    tables: tuple[BillStatusGuideTable, ...]
    version_notes: tuple[BillStatusGuideContext, ...]


class _Reader:
    def __init__(self, body: bytes, max_rows: int) -> None:
        self.body = body
        self.lines = body.splitlines(keepends=True)
        self.offsets = [0]
        for line in self.lines:
            self.offsets.append(self.offsets[-1] + len(line))
        self.max_rows = max_rows
        self.row_count = 0

    def span(self, start: int, end: int, line: int) -> BillStatusGuideText:
        return BillStatusGuideText(self.body[start:end].decode("utf-8"), line + 1, start, end)

    def line(self, index: int) -> BillStatusGuideText:
        return self.span(self.offsets[index], self.offsets[index + 1], index)

    def stripped_line(self, index: int) -> bytes:
        return self.lines[index].decode("utf-8").strip().encode("utf-8")

    def row(self, index: int) -> BillStatusGuideRow:
        raw = self.lines[index]
        stripped = self.stripped_line(index)
        if not stripped.startswith(b"|") or not stripped.endswith(b"|") or len(stripped) < 2:
            raise BillStatusGuideError(f"malformed pipe-table row at line {index + 1}")
        if b"\\|" in raw:
            raise BillStatusGuideError(f"escaped pipes are unsupported at line {index + 1}")
        pipes = []
        for index_in_line, byte in enumerate(raw):
            if byte == ord("|"):
                pipes.append(index_in_line)
                if len(pipes) > 33:
                    raise BillStatusGuideError("BILLSTATUS guide table exceeds 32 columns")
        cells = []
        for left, right in pairwise(pipes):
            source = self.span(self.offsets[index] + left + 1, self.offsets[index] + right, index)
            value = source.text.strip()
            bold = len(value) >= 4 and value.startswith("**") and value.endswith("**")
            if bold:
                value = value[2:-2].strip()
            cells.append(BillStatusGuideCell(source, value, bold))
        return BillStatusGuideRow(self.line(index), tuple(cells))

    def bill_types(self, start: int, end: int) -> BillStatusBillTypes:
        index = start + 1
        while index < end and not self.stripped_line(index):
            index += 1
        if index == end:
            raise BillStatusGuideError("bill type section has no sentence")
        raw = self.lines[index]
        stripped = self.stripped_line(index)
        match = _SENTENCE.fullmatch(stripped)
        if match is None:
            raise BillStatusGuideError("bill type sentence does not match the documented source form")
        leading_bytes = len(raw) - len(raw.decode("utf-8").lstrip().encode("utf-8"))
        beginning = self.offsets[index] + leading_bytes + match.start(1)
        values = []
        cursor = 0
        enumeration = match[1]
        while cursor <= len(enumeration):
            stop = enumeration.find(b",", cursor)
            if stop < 0:
                stop = len(enumeration)
            self.count_row()
            source = self.span(beginning + cursor, beginning + stop, index)
            value = source.text.strip()
            if cursor and (conjunction := re.match(r"and\s+", value)):
                value = value[conjunction.end() :].strip()
            values.append(BillStatusGuideCell(source, value, False))
            cursor = stop + 1
        return BillStatusBillTypes(self.line(start), self.line(index), tuple(values))

    def count_row(self) -> None:
        self.row_count += 1
        if self.row_count > self.max_rows:
            raise BillStatusGuideError("BILLSTATUS guide exceeds max_rows")

    def table(self, start: int, end: int, section: str) -> BillStatusGuideTable:
        index = start + 1
        while index < end and not self.stripped_line(index).startswith(b"|"):
            index += 1
        if index + 1 >= end:
            raise BillStatusGuideError(f"section {section} has no complete pipe table")
        header = self.row(index)
        separator = self.row(index + 1)
        columns = len(header.cells)
        if len(separator.cells) != columns or not all(
            _SEPARATOR.fullmatch(cell.raw.text.strip()) for cell in separator.cells
        ):
            raise BillStatusGuideError(f"malformed table separator in section {section}")
        context = self.span(self.offsets[start + 1], self.offsets[index], start + 1)
        index += 2
        rows = []
        while index < end and self.stripped_line(index).startswith(b"|"):
            row = self.row(index)
            if len(row.cells) != columns:
                raise BillStatusGuideError(f"table row width differs from header at line {index + 1}")
            self.count_row()
            rows.append(row)
            index += 1
        # A separated second table must not silently replace or extend the first.
        if any(self.stripped_line(later).startswith(b"|") for later in range(index, end)):
            raise BillStatusGuideError(f"section {section} contains multiple pipe tables")
        return BillStatusGuideTable(section, self.line(start), context, header, separator, tuple(rows))


def read_billstatus_guide(body: bytes, *, max_bytes: int = 2 * 1024 * 1024, max_rows: int = 10_000) -> BillStatusGuide:
    """Read the fixed guide sections, retaining repetitions, raw spelling and context.

    Sections 3/4/5/6 supply action codes, action types, summary versions and title
    types; the billType sentence, introductory bill types and version explanation
    stay separate. No code grammar, deduplication, chamber validation, completeness
    classification or H/HR reconciliation runs. Missing sections remain absent.
    Markdown cells expose whitespace-trimmed values with one enclosing bold pair
    removed; their original text survives. Escaped pipes refuse explicitly.
    max_rows bounds table rows and sentence values together, including empties.

    This is a bounded reader for the publisher's literal guide layout, not a
    general Markdown renderer: it infers no guide release number from section
    numbers or the schema-version explanation, and fetches and publishes nothing.
    Preserve the returned digest with original bytes to replay spans.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= 16 * 1024 * 1024:
        raise BillStatusGuideError("max_bytes must be a positive integer no greater than 16 MiB")
    if type(max_rows) is not int or max_rows <= 0:
        raise BillStatusGuideError("max_rows must be a positive integer")
    if not isinstance(body, bytes) or not body or len(body) > max_bytes:
        raise BillStatusGuideError("BILLSTATUS guide must be nonempty bytes within max_bytes")
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BillStatusGuideError("BILLSTATUS guide is not valid UTF-8") from error
    reader = _Reader(body, max_rows)
    sections: list[tuple[int, int]] = []
    active: list[tuple[int, int]] = []
    for index, raw in enumerate(reader.lines):
        match = re.match(rb"^(#{1,6}) ", raw)
        if match is None:
            continue
        level = len(match[1])
        while active and active[-1][1] >= level:
            sections.append((active.pop()[0], index))
        active.append((index, level))
    sections.extend((start, len(reader.lines)) for start, _level in active)
    bill_types, introductions, tables, versions = [], [], [], []
    for start, end in sorted(sections):
        heading = reader.lines[start].decode("utf-8").strip()
        if heading in _TABLES:
            tables.append(reader.table(start, end, _TABLES[heading]))
        elif heading == _BILL_TYPE:
            bill_types.append(reader.bill_types(start, end))
        elif heading in (_INTRO, _VERSION):
            context = BillStatusGuideContext(
                reader.line(start), reader.span(reader.offsets[start + 1], reader.offsets[end], start + 1)
            )
            (introductions if heading == _INTRO else versions).append(context)
    return BillStatusGuide(
        hashlib.sha256(body).hexdigest(),
        len(body),
        tuple(bill_types),
        tuple(introductions),
        tuple(tables),
        tuple(versions),
    )
