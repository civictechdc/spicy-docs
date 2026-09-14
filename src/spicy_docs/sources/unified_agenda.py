"""Unified Agenda editions from reginfo.gov: one XML file per semiannual edition, identity proved per record.

The Regulatory Information Service Center publishes each edition of the
Unified Agenda of Regulatory and Deregulatory Actions as one XML file,
``REGINFO_RIN_DATA_{YYYYMM}.xml`` with MM 04 (Spring) or 10 (Fall), reachable
keyless through ``XMLViewFileAction``. The root ``REGINFO_RIN_DATA`` states a
``RUN_DATE`` and the publisher's XSD; every ``RIN_INFO`` record states its
``RIN`` and the ``PUBLICATION_ID`` of the edition it belongs to, so an edition
proves itself from every record rather than from its file name. Three
publisher irregularities are recorded, not repaired: the file named
``REGINFO_RIN_DATA_2012.xml`` states ``PUBLICATION_ID`` 201210; Spring 2012
(``201204``) was never published; and the two 2004 editions each contain one
control byte that XML 1.0 forbids, so the strict parser refuses them and the
exact bytes remain the caller's to repair downstream.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

import httpx

from spicy_docs.sources.xml import scan_xml
from spicy_docs.transport.capture import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

EXPORT_URL = "https://www.reginfo.gov/public/do/XMLViewFileAction"
ROOT = "REGINFO_RIN_DATA"
RECORD = "RIN_INFO"
_SCHEMA_LOCATION = "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation"
_EDITION_STEM = re.compile(r"(?:199[5-9]|20[0-9]{2})(?:04|10)")
# The publisher's one off-pattern file name; its records state the Fall 2012 edition.
LEGACY_FILE_STEMS = {"2012": "201210"}
# The Fall 2025 edition is 17.6 MB; sixty editions total 981 MB.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
MAX_EDITION_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 100_000
_MAX_FIELD_CHARACTERS = 4096


class UnifiedAgendaSourceError(ValueError):
    """The request or response cannot establish the selected edition."""


class UnifiedAgendaUnavailableError(UnifiedAgendaSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"Unified Agenda export answered HTTP {capture.status_code}")
        self.capture = capture


def _limit(max_bytes: int) -> None:
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_EDITION_BYTES:
        raise UnifiedAgendaSourceError("max_bytes must be a positive integer no greater than 256 MiB")


@dataclass(frozen=True, slots=True)
class UnifiedAgendaEdition:
    """The file stem the publisher uses; the edition it states may differ (``2012`` states 201210)."""

    file_stem: str

    def __post_init__(self) -> None:
        if not isinstance(self.file_stem, str) or (
            self.file_stem not in LEGACY_FILE_STEMS and _EDITION_STEM.fullmatch(self.file_stem) is None
        ):
            raise UnifiedAgendaSourceError("file_stem must be YYYYMM with MM 04 or 10 from 1995, or the legacy 2012")

    @property
    def publication_id(self) -> str:
        return LEGACY_FILE_STEMS.get(self.file_stem, self.file_stem)

    @property
    def file_name(self) -> str:
        return f"REGINFO_RIN_DATA_{self.file_stem}.xml"


def unified_agenda_xml_locator(edition: UnifiedAgendaEdition) -> str:
    if not isinstance(edition, UnifiedAgendaEdition):
        raise UnifiedAgendaSourceError("edition must be a UnifiedAgendaEdition")
    return f"{EXPORT_URL}?f={edition.file_name}"


@dataclass(frozen=True, slots=True)
class UnifiedAgendaMetadata:
    """What the edition file proves about itself; record bodies stay with the caller's bytes."""

    file_stem: str
    publication_id: str
    run_date: str | None
    schema_location: str | None
    record_count: int
    rins: tuple[str, ...]


class _Scan:
    """Stream the edition; keep the root's identity and every record's RIN, never a tree."""

    def __init__(self, publication_id: str) -> None:
        self.publication_id = publication_id
        self.path: list[str] = []
        self.run_date: str | None = None
        self.schema_location: str | None = None
        self.rins: list[str] = []
        self._seen: set[str] = set()
        self._rin: list[str] | None = None
        self._publication: list[str] | None = None
        self._record_rins: list[str] = []
        self._record_publications: list[str] = []

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        self.path.append(tag)
        depth = len(self.path)
        if depth == 1:
            if tag != ROOT:
                raise UnifiedAgendaSourceError("Unified Agenda XML root is not REGINFO_RIN_DATA")
            self.run_date = attributes.get("RUN_DATE")
            self.schema_location = attributes.get(_SCHEMA_LOCATION)
        elif tag == ROOT:
            raise UnifiedAgendaSourceError("Unified Agenda XML contains a nested document root")
        path = tuple(self.path)
        if path == (ROOT, RECORD):
            if len(self.rins) >= MAX_RECORDS:
                raise UnifiedAgendaSourceError("Unified Agenda edition lists more records than supported")
            self._record_rins, self._record_publications = [], []
        elif path == (ROOT, RECORD, "RIN"):
            self._rin = []
        elif path == (ROOT, RECORD, "PUBLICATION", "PUBLICATION_ID"):
            self._publication = []

    def data(self, text: str) -> None:
        for parts in (self._rin, self._publication):
            if parts is not None:
                parts.append(text)
                if sum(map(len, parts)) > _MAX_FIELD_CHARACTERS:
                    raise UnifiedAgendaSourceError("Unified Agenda identity field exceeds 4,096 characters")

    def end(self, tag: str) -> None:
        path = tuple(self.path)
        if path == (ROOT, RECORD, "RIN") and self._rin is not None:
            self._record_rins.append("".join(self._rin).strip())
            self._rin = None
        elif path == (ROOT, RECORD, "PUBLICATION", "PUBLICATION_ID") and self._publication is not None:
            self._record_publications.append("".join(self._publication).strip())
            self._publication = None
        elif path == (ROOT, RECORD):
            if len(self._record_rins) != 1 or not self._record_rins[0]:
                raise UnifiedAgendaSourceError("Unified Agenda record requires exactly one RIN")
            if self._record_publications != [self.publication_id]:
                raise UnifiedAgendaSourceError("Unified Agenda record states another edition than the request")
            rin = self._record_rins[0]
            if rin in self._seen:
                raise UnifiedAgendaSourceError("Unified Agenda edition repeats a RIN")
            self._seen.add(rin)
            self.rins.append(rin)
        self.path.pop()


def validate_unified_agenda_xml(
    body: bytes,
    *,
    edition: UnifiedAgendaEdition,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> UnifiedAgendaMetadata:
    """Prove every record belongs to the requested edition; keep the exact bytes for the caller."""
    _limit(max_bytes)
    if final_url != unified_agenda_xml_locator(edition):
        raise UnifiedAgendaSourceError("Unified Agenda response URL differs from the requested edition")
    scan = _Scan(edition.publication_id)
    scan_xml(
        body,
        start=scan.start,
        end=scan.end,
        data=scan.data,
        max_bytes=max_bytes,
        error_type=UnifiedAgendaSourceError,
        label="Unified Agenda XML",
    )
    if not scan.rins:
        raise UnifiedAgendaSourceError("Unified Agenda edition lists no RIN_INFO records")
    return UnifiedAgendaMetadata(
        edition.file_stem,
        edition.publication_id,
        scan.run_date,
        scan.schema_location,
        len(scan.rins),
        tuple(scan.rins),
    )


@dataclass(frozen=True, slots=True)
class UnifiedAgendaBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_EDITION_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class UnifiedAgendaAcquisition:
    edition: UnifiedAgendaEdition
    metadata: UnifiedAgendaMetadata
    capture: CapturedBodyResponse
    request_count: int
    budget: UnifiedAgendaBudget


class UnifiedAgendaAcquirer(SourceAcquirer):
    """Keyless capture of one edition file; the whole series is sixty explicit calls."""

    def __init__(
        self,
        *,
        budget: UnifiedAgendaBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, UnifiedAgendaBudget):
            raise TypeError("budget must be a UnifiedAgendaBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-unified-agenda/1.0",
            label="Unified Agenda",
            error_type=UnifiedAgendaSourceError,
            context_key="unified_agenda_acquisition",
            transport=transport,
            clock=clock,
        )

    @property
    def budget(self) -> UnifiedAgendaBudget:
        return self._budget

    def acquire_edition(
        self, edition: UnifiedAgendaEdition, *, max_bytes: int | None = None
    ) -> UnifiedAgendaAcquisition:
        limit = narrow_byte_limit(self.budget.max_bytes, max_bytes)
        metadata, capture = self.capture_validated(
            unified_agenda_xml_locator(edition),
            media_types=("application/xml", "text/xml"),
            parse=lambda response, bound: validate_unified_agenda_xml(
                response.body, edition=edition, final_url=response.resolved_url, max_bytes=bound
            ),
            max_bytes=limit,
            unavailable=UnifiedAgendaUnavailableError,
            context={"operation": "edition", "fileStem": edition.file_stem, "publicationId": edition.publication_id},
        )
        return UnifiedAgendaAcquisition(
            edition, metadata, capture, self.request_count, replace(self.budget, max_bytes=limit)
        )
