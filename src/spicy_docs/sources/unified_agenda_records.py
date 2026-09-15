"""Bounded source metadata from retained Unified Agenda XML editions."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from .xml_observations import XmlElement, XmlObservationScan

ROOT = "REGINFO_RIN_DATA"
RECORD = "RIN_INFO"
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
MAX_EDITION_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 100_000
_FIELDS = frozenset(
    {
        "RIN",
        "PUBLICATION",
        "CFR_LIST",
        "LEGAL_AUTHORITY_LIST",
        "TIMETABLE_LIST",
        "ADDITIONAL_INFO",
        "AGENCY",
        "PARENT_AGENCY",
        "RULE_TITLE",
        "ABSTRACT",
        "PRIORITY_CATEGORY",
        "RIN_STATUS",
        "RULE_STAGE",
        "MAJOR",
    }
)


class UnifiedAgendaSourceError(ValueError):
    """The request or response cannot establish the selected source observation."""


def _limit(max_bytes: int) -> None:
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_EDITION_BYTES:
        raise UnifiedAgendaSourceError("max_bytes must be a positive integer no greater than 256 MiB")


@dataclass(frozen=True, slots=True)
class UnifiedAgendaField:
    """One selected field or descendant, with literal XML text and structure.

    ``text`` concatenates all descendant text. ``leading_text`` contains only
    text before the first child, matching ElementTree's element.text or "".
    Child tails are included in the parent's text. Exact interleaving, entity
    spelling and XML markup remain in the input bytes, not these observations.
    """

    element: XmlElement
    text: str
    leading_text: str
    children: tuple[UnifiedAgendaField, ...]


@dataclass(frozen=True, slots=True)
class UnifiedAgendaRecordObservation:
    """A direct RIN_INFO record; missing fields are absent, empty fields remain."""

    element: XmlElement
    fields: tuple[UnifiedAgendaField, ...]


@dataclass(frozen=True, slots=True)
class UnifiedAgendaRecordScan:
    """Original input pin, root attributes, and count from a complete XML scan."""

    input_sha256: str
    input_bytes: int
    root: XmlElement
    record_count: int


@dataclass(slots=True)
class _Field:
    element: XmlElement
    text: list[str] = field(default_factory=list)
    leading: list[str] = field(default_factory=list)
    children: list[UnifiedAgendaField] = field(default_factory=list)
    child_started: bool = False


class _RecordScan(XmlObservationScan):
    def __init__(
        self,
        on_record: Callable[[UnifiedAgendaRecordObservation], object] | None,
        max_records: int,
        max_fields: int,
        max_text_characters: int,
        max_depth: int,
        identity_only: bool,
    ) -> None:
        super().__init__(error_type=UnifiedAgendaSourceError, label="Unified Agenda XML", max_depth=max_depth)
        self.on_record = on_record
        self.selected_fields = frozenset({"RIN", "PUBLICATION"}) if identity_only else _FIELDS
        self.max_records = max_records
        self.max_fields = max_fields
        self.max_text_characters = max_text_characters
        self.root: XmlElement | None = None
        self.record: XmlElement | None = None
        self.count = 0
        self.fields: list[UnifiedAgendaField] = []
        self.active: list[_Field] = []
        self.field_count = self.text_characters = 0

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        depth = len(self.stack)
        if depth == 1:
            if tag != ROOT:
                raise UnifiedAgendaSourceError("Unified Agenda XML root is not REGINFO_RIN_DATA")
            self.root = self.current_element()
        elif tag == ROOT:
            raise UnifiedAgendaSourceError("Unified Agenda XML contains a nested document root")
        if tag == RECORD and depth != 2:
            raise UnifiedAgendaSourceError("Unified Agenda RIN_INFO must be a direct child of REGINFO_RIN_DATA")
        if depth == 2 and tag == RECORD:
            self.count += 1
            if self.count > self.max_records:
                raise UnifiedAgendaSourceError("Unified Agenda edition exceeds max_records")
            self.record = self.current_element()
            self.fields = []
            self.field_count = self.text_characters = 0
        elif self.record is not None and (self.active or depth == 3 and tag in self.selected_fields):
            self.field_count += 1
            if self.field_count > self.max_fields:
                raise UnifiedAgendaSourceError("Unified Agenda record exceeds max_fields")
            if self.active:
                self.active[-1].child_started = True
            self.active.append(_Field(self.current_element()))

    def observe_text(self, text: str) -> None:
        # Count all retained copies, including ancestors and leading text. The
        # completed fields remain buffered until their record callback returns.
        self.text_characters += len(text) * sum(1 + (not item.child_started) for item in self.active)
        if self.text_characters > self.max_text_characters:
            raise UnifiedAgendaSourceError("Unified Agenda record exceeds max_text_characters")
        for item in self.active:
            item.text.append(text)
            if not item.child_started:
                item.leading.append(text)

    def observe_end(self, tag: str) -> None:
        if self.active:
            item = self.active.pop()
            result = UnifiedAgendaField(item.element, "".join(item.text), "".join(item.leading), tuple(item.children))
            if self.active:
                self.active[-1].children.append(result)
            else:
                self.fields.append(result)
        elif len(self.stack) == 2 and tag == RECORD and self.record is not None:
            if self.on_record is not None:
                self.emit(self.on_record, UnifiedAgendaRecordObservation(self.record, tuple(self.fields)))
            self.record = None
            self.fields = []


def scan_unified_agenda_records(
    body: bytes,
    *,
    on_record: Callable[[UnifiedAgendaRecordObservation], object] | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_records: int = MAX_RECORDS,
    max_fields: int = 100_000,
    max_text_characters: int = 4 * 1024 * 1024,
    max_depth: int = 256,
) -> UnifiedAgendaRecordScan:
    """Read direct records and their fixed selected metadata fields in one pass.

    RIN, PUBLICATION, CFR_LIST, LEGAL_AUTHORITY_LIST, TIMETABLE_LIST,
    ADDITIONAL_INFO, AGENCY, PARENT_AGENCY, RULE_TITLE, ABSTRACT,
    PRIORITY_CATEGORY, RIN_STATUS, RULE_STAGE and MAJOR survive in source order,
    including all repetitions and unknown descendants. Other fields remain in
    the retained input. Selection uses exact unqualified publisher tag names;
    selected descendants retain expanded names and literal attributes.

    Missing/repeated identities and empty records remain raw observations. The
    acquisition validator separately checks RIN and selected-edition identity.
    No control-byte repair, whitespace collapse or citation interpretation runs.
    XML decoding/newline rules apply; HTML within CDATA remains literal text.

    Callbacks run at record close and remain provisional until successful
    return. Source XPath counts elements, never bytes. Retain the input with
    its returned pin. Limits bound input bytes, records, nesting, selected nodes
    per record and retained text copies per record, including ancestor/leading
    duplication. Caller-owned callback storage is outside those limits.
    """
    return _read_records(
        body,
        on_record=on_record,
        max_bytes=max_bytes,
        max_records=max_records,
        max_fields=max_fields,
        max_text_characters=max_text_characters,
        max_depth=max_depth,
    )


def _read_records(
    body: bytes,
    *,
    on_record: Callable[[UnifiedAgendaRecordObservation], object] | None,
    max_bytes: int,
    max_records: int = MAX_RECORDS,
    max_fields: int = 100_000,
    max_text_characters: int = 4 * 1024 * 1024,
    max_depth: int = 256,
    identity_only: bool = False,
) -> UnifiedAgendaRecordScan:
    _limit(max_bytes)
    for name, value in (
        ("max_records", max_records),
        ("max_fields", max_fields),
        ("max_text_characters", max_text_characters),
    ):
        if type(value) is not int or value <= 0:
            raise UnifiedAgendaSourceError(f"{name} must be a positive integer")
    if on_record is not None and not callable(on_record):
        raise UnifiedAgendaSourceError("on_record must be callable")
    scan = _RecordScan(on_record, max_records, max_fields, max_text_characters, max_depth, identity_only)
    scan.read(body, max_bytes=max_bytes)
    assert scan.root is not None
    return UnifiedAgendaRecordScan(hashlib.sha256(body).hexdigest(), len(body), scan.root, scan.count)
