"""One field-path projection of a Unified Agenda edition: citations, timetable and continued authorities.

Moved from RefSpec's ``refspec.registry.unified_agenda_editions`` (file at ``d4a22979``, read at RefSpec
``4a680c81``): ``_leading`` (:682), the ``0x19`` repair (:74, :811), ``legal_authority_continuations`` and its
patterns (:689-786), and the field selection of ``parse_unified_agenda_edition`` (:821-861). spicy-regs'
``sources/unified_agenda.py`` read the same paths with ``strip()`` and would otherwise keep a second answer.

Four rules, each measured over all 60 retained editions (241,726 records; receipt
``corpora/supply-2026-09-02/receipts/unified-agenda-projection-2026-09-23/``):

* **Whitespace runs collapse** to one ASCII space in every projected string, as a citation box's are, and so
  does a lone non-ASCII space (U+2009, U+202F). Whitespace is what ``str.split()`` splits on: Unicode
  whitespace plus U+001C-U+001F and U+0085 (48 of those in the editions, none in a projected path).
  Stripping alone keeps them inside 4,748 records: 1,562 CFR lists, 1,959 authority lists and 1,373 timetables.
* **Every** ``CFR_LIST/CFR``, ``LEGAL_AUTHORITY_LIST/LEGAL_AUTHORITY`` and ``TIMETABLE_LIST/TIMETABLE`` is
  read, and nothing else inside those lists; no edition repeats a list or puts a foreign child in one, so
  this equals RefSpec's first-list reading on every record while losing nothing if one ever does.
* **The 2004 editions' one ``0x19`` byte each** is the publisher's mangled ``U+2019`` and is repaired in
  memory for those two editions only. A second one there is refused, as is one in any other edition
  (by the strict parser), because only one each was measured.
* **Legal-authority lists continued in ``ADDITIONAL_INFO``** under a label are read as separate
  continuations: 98 records, all 199510-200510, carry lists that ``LEGAL_AUTHORITY_LIST`` does not
  (1,310 citations by RefSpec's current grammar, as its sealed table holds).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from . import UnifiedAgendaEdition, _EditionIdentity
from .records import (
    DEFAULT_MAX_BYTES,
    MAX_EDITION_BYTES,
    UnifiedAgendaField,
    UnifiedAgendaRecordObservation,
    UnifiedAgendaSourceError,
    _limit,
    _read_records,
)

#: Editions whose export carries the publisher's mangled ``U+2019`` as a ``0x19`` byte, which XML 1.0 forbids:
#: exactly one each ("Department\x19s", "bureau\x19s") and none in the other 58 editions. It is not systematic
#: mojibake -- no ``0x1c``/``0x1d``/``0x14`` companions from curly quotes or dashes appear -- so the repair is
#: scoped to these two exports and their one byte each, rather than applied to any file that carries the byte.
MANGLED_APOSTROPHE_EDITIONS = ("200404", "200410")
_MANGLED_APOSTROPHE = b"\x19"
_APOSTROPHE = "\u2019".encode()

#: What a continuation's label says it continues. ``legal-authority-cont`` is "LEGAL AUTHORITY CONT:" and its
#: other case-folded spellings (67 records, 17 RINs, 16 editions, 199510-200304); ``additional-legal-authority``
#: is "Additional Legal Authority(ies)", "Additional legal authority information:" and the single "Continue from
#: #8 Legal Authority" (31 records, 8 RINs, 11 editions). Deliberately not read: "STATUTORY DEADLINE CONT:" and
#: "CFR CITATION(S) CONT:" (other fields); a bare "Legal Authority:" (0938-AI52, 0938-AI45, 1090-AA67 in 199804;
#: 0701-AA65 in 2001-2002, which says it restates "the information for legal authority as it is generally
#: listed") because restating a field is not continuing it; and "Additional authority DOT Order 5660.1A"
#: (2125-AD78, 199604-200104), which never says "legal".
CONTINUATION_LABEL_FAMILIES = ("legal-authority-cont", "additional-legal-authority")

# Every spelling the retained editions contain, and no wider: the optional "LEGAL", singular and plural, the
# parenthesised form, each truncation of "CONTINUED", and the dots or colons behind it; the "Additional Legal
# Authority" family with its "information:" outlier; and "Continue from #8 Legal Authority" (3235-AE11, 199704).
# RefSpec wrote each optional part as "\s*\(?\s*"; "\s*(?:\(\s*)?" matches the same text without two
# quantifiers competing for one whitespace run, so a label followed by spaces backtracks linearly.
_CONTINUATION_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "legal-authority-cont",
        re.compile(r"(?:LEGAL\s+)?AUTHORIT(?:Y|IES)\s*(?:\(\s*)?CONT(?:INUED|INUES|INUE)?\)?\s*[.:]*", re.IGNORECASE),
    ),
    (
        "additional-legal-authority",
        re.compile(r"ADDITIONAL\s+LEGAL\s+AUTHORIT(?:Y|IES)(?:\s+INFORMATION)?\s*[.:]*", re.IGNORECASE),
    ),
    (
        "additional-legal-authority",
        re.compile(r"CONTINUE[DS]?\s+FROM\s*(?:#\s*)?\d+\s*LEGAL\s+AUTHORIT(?:Y|IES)\s*[.:]*", re.IGNORECASE),
    ),
)
# A continuation ends at the publisher's paragraph mark (a literal "^", written "^P" before the next field) or a
# blank line, the same boundary in editions that carry real newlines.
_CONTINUATION_BOUNDARY = re.compile(r"\^|\n[ \t]*\n")
# Or, before that boundary, at another field continuing under its own label. This fires on nothing in the retained
# editions -- every "CFR CITATIONS CONT:" and "STATUTORY DEADLINE CONT:" already sits behind a boundary above -- and
# is kept because the regression it guards is silent: two continuations separated by a semicolon would hand a CFR
# list to the authority reader. A label ends in a colon; "continued" in prose does not, so a list is never cut by
# its own text. A label's words are at most 64 letters and spaces; a longer run before "CONT:" is prose, and only
# its last 64 characters are cut. RefSpec searched to the end of the field with "[A-Za-z ']*\s*\(?\s*", which is
# cubic in a run of spaces behind one letter (1,000 spaces: 0.6 s; 2,000: 5.0 s; 2,000 after a paragraph mark:
# 9.8 s), and a record may hold 4 MiB. Searched only up to the boundary and bounded, 100,000 spaces take 0.09 s.
# Over the 65,128 ADDITIONAL_INFO fields in the 60 editions both searches return the same result.
_ANOTHER_FIELD_CONTINUES = re.compile(
    r"[A-Za-z][A-Za-z ']{0,63}\s*(?:\(\s*)?CONT(?:INUED|INUES|INUE)?\)?\s*:", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class UnifiedAgendaAuthorityContinuation:
    """One legal-authority list that outran its boxes, typed into ``ADDITIONAL_INFO`` under a label.

    ``marker`` is the label exactly as the filer typed it; ``text`` runs from the label's end to the boundary,
    whitespace collapsed, and is never pre-split: 1115-AE47's Spring 1997 continuation is one comma list under
    one title ("8 USC 1186b, 1187, 1201, ...") that a citation grammar reads whole and misreads if split first.
    """

    label_family: str
    marker: str
    text: str


@dataclass(frozen=True, slots=True)
class UnifiedAgendaTimetableEntry:
    """One ``TIMETABLE``: each child's text collapsed, ``None`` when absent or blank.

    ``date_text`` is the publisher's ``MM/DD/YYYY`` or "To Be Determined" verbatim; a projected month carries
    a zero day ("11/00/2026"), so reading it as a date is the caller's rule.
    """

    action: str | None
    date_text: str | None
    fr_citation: str | None


@dataclass(frozen=True, slots=True)
class UnifiedAgendaRecordProjection:
    """One proved record's projected fields beside the raw observation they were read from."""

    record: UnifiedAgendaRecordObservation
    rin: str
    publication_id: str
    cfr_references: tuple[str, ...]
    legal_authorities: tuple[str, ...]
    legal_authority_continuations: tuple[UnifiedAgendaAuthorityContinuation, ...]
    timetable: tuple[UnifiedAgendaTimetableEntry, ...]


@dataclass(frozen=True, slots=True)
class UnifiedAgendaProjectionScan:
    """The input pin over the bytes as served, before repair, and what the read proved."""

    input_sha256: str
    input_bytes: int
    publication_id: str
    record_count: int
    repaired_bytes: int


def project_unified_agenda_edition(
    body: bytes,
    *,
    edition: UnifiedAgendaEdition,
    on_record: Callable[[UnifiedAgendaRecordProjection], object],
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> UnifiedAgendaProjectionScan:
    """Project every record of one retained edition, proving identity as acquisition does.

    Each record must state one RIN and ``edition``'s publication id, and no RIN may repeat. Callbacks run at
    record close and are provisional until the call returns, like ``scan_unified_agenda_records``. The pin
    covers ``body`` as served; the ``0x19`` repair touches only the in-memory copy the parser reads.
    """
    if not isinstance(edition, UnifiedAgendaEdition):
        raise UnifiedAgendaSourceError("edition must be a UnifiedAgendaEdition")
    if not callable(on_record):
        raise UnifiedAgendaSourceError("on_record must be callable")
    _limit(max_bytes)
    if not isinstance(body, bytes) or len(body) > max_bytes:
        raise UnifiedAgendaSourceError("Unified Agenda XML must be bytes within max_bytes")
    repaired_bytes = body.count(_MANGLED_APOSTROPHE) if edition.publication_id in MANGLED_APOSTROPHE_EDITIONS else 0
    if repaired_bytes > 1:
        raise UnifiedAgendaSourceError("Unified Agenda 2004 edition carries more than its one measured 0x19 byte")
    readable = body.replace(_MANGLED_APOSTROPHE, _APOSTROPHE) if repaired_bytes else body
    identity = _EditionIdentity(edition)

    def project(record: UnifiedAgendaRecordObservation) -> None:
        on_record(_project(record, identity.prove(record), edition.publication_id))

    # The caller's bound covers the bytes as served; each repair lengthens the parsed copy by two bytes.
    scan = _read_records(readable, on_record=project, max_bytes=MAX_EDITION_BYTES)
    identity.proved()
    return UnifiedAgendaProjectionScan(
        hashlib.sha256(body).hexdigest(), len(body), edition.publication_id, scan.record_count, repaired_bytes
    )


def legal_authority_continuations(additional_info: str) -> tuple[UnifiedAgendaAuthorityContinuation, ...]:
    """Every labelled legal-authority continuation in one ``ADDITIONAL_INFO``, in source order.

    Read from the field's whitespace intact, because a blank line is one of the boundaries; each continuation
    runs from its label's end to the first boundary and is returned whitespace-collapsed.
    """
    marks = sorted(
        (match.start(), match.end(), family, match.group(0))
        for family, pattern in _CONTINUATION_MARKERS
        for match in pattern.finditer(additional_info)
    )
    found: list[UnifiedAgendaAuthorityContinuation] = []
    consumed = 0
    for start, end, family, marker in marks:
        # Two patterns overlap only by reading one label two ways; the first wins, so no label is read twice.
        if start < consumed:
            continue
        consumed = end
        boundary = _CONTINUATION_BOUNDARY.search(additional_info, end)
        stop = boundary.start() if boundary is not None else len(additional_info)
        if label := _ANOTHER_FIELD_CONTINUES.search(additional_info, end, stop):
            stop = label.start()
        if text := _collapse(additional_info[end:stop]):
            found.append(UnifiedAgendaAuthorityContinuation(family, marker.strip(), text))
    return tuple(found)


def _project(record: UnifiedAgendaRecordObservation, rin: str, publication_id: str) -> UnifiedAgendaRecordProjection:
    fields = record.fields
    return UnifiedAgendaRecordProjection(
        record=record,
        rin=rin,
        publication_id=publication_id,
        cfr_references=_texts(fields, "CFR_LIST", "CFR"),
        legal_authorities=_texts(fields, "LEGAL_AUTHORITY_LIST", "LEGAL_AUTHORITY"),
        legal_authority_continuations=tuple(
            continuation
            for field in fields
            if field.element.tag == "ADDITIONAL_INFO"
            for continuation in legal_authority_continuations(field.text)
        ),
        timetable=tuple(
            UnifiedAgendaTimetableEntry(
                _first_text(entry.children, "TTBL_ACTION"),
                _first_text(entry.children, "TTBL_DATE"),
                _first_text(entry.children, "FR_CITATION"),
            )
            for entry in _items(fields, "TIMETABLE_LIST", "TIMETABLE")
        ),
    )


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _items(fields: Sequence[UnifiedAgendaField], container: str, item: str) -> Iterator[UnifiedAgendaField]:
    for field in fields:
        if field.element.tag == container:
            yield from (child for child in field.children if child.element.tag == item)


def _texts(fields: Sequence[UnifiedAgendaField], container: str, item: str) -> tuple[str, ...]:
    """Blank entries are dropped: an empty box states no citation."""
    return tuple(text for child in _items(fields, container, item) if (text := _collapse(child.leading_text)))


def _first_text(fields: Sequence[UnifiedAgendaField], tag: str) -> str | None:
    field = next((field for field in fields if field.element.tag == tag), None)
    return (_collapse(field.leading_text) or None) if field is not None else None
