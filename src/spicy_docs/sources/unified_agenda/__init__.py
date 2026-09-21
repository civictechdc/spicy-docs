"""Unified Agenda editions from reginfo.gov: one XML file per semiannual edition, identity proved per record.

The Regulatory Information Service Center publishes each edition of the Unified Agenda of Regulatory
and Deregulatory Actions as one XML file, ``REGINFO_RIN_DATA_{YYYYMM}.xml`` with MM 04 (Spring) or
10 (Fall), reachable keyless through ``XMLViewFileAction``. The root ``REGINFO_RIN_DATA`` states a
``RUN_DATE`` and the publisher's XSD, and every ``RIN_INFO`` record states its ``RIN`` and the
``PUBLICATION_ID`` of the edition it belongs to, so an edition proves itself from every record
rather than from its file name. Three publisher irregularities are recorded, not repaired: the file
named ``REGINFO_RIN_DATA_2012.xml`` states ``PUBLICATION_ID`` 201210, Spring 2012 (``201204``) was
never published, and the two 2004 editions each contain one control byte that XML 1.0 forbids, so
the strict parser refuses them and the exact bytes remain the caller's to repair downstream.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

from .records import (
    DEFAULT_MAX_BYTES,
    MAX_EDITION_BYTES,
    UnifiedAgendaRecordObservation,
    UnifiedAgendaSourceError,
    _limit,
    _read_records,
)

if TYPE_CHECKING:
    import httpx

EXPORT_URL = "https://www.reginfo.gov/public/do/XMLViewFileAction"
_SCHEMA_LOCATION = "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation"
_EDITION_STEM = re.compile(r"(?:199[5-9]|20[0-9]{2})(?:04|10)")
# The publisher's one off-pattern file name; its records state the Fall 2012 edition.
LEGACY_FILE_STEMS = {"2012": "201210"}
_MAX_FIELD_CHARACTERS = 4096


class UnifiedAgendaUnavailableError(UnifiedAgendaSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"Unified Agenda export answered HTTP {capture.status_code}")
        self.capture = capture


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
        """The edition every record must state; the legacy 2012 file states 201210."""
        return LEGACY_FILE_STEMS.get(self.file_stem, self.file_stem)

    @property
    def file_name(self) -> str:
        return f"REGINFO_RIN_DATA_{self.file_stem}.xml"


def unified_agenda_xml_locator(edition: UnifiedAgendaEdition) -> str:
    """Build the keyless export URL for one edition."""
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
    rins: list[str] = []
    seen: set[str] = set()

    def validate_record(record: UnifiedAgendaRecordObservation) -> None:
        raw_rins = [field.text for field in record.fields if field.element.tag == "RIN"]
        publications = [
            child.text
            for field in record.fields
            if field.element.tag == "PUBLICATION"
            for child in field.children
            if child.element.tag == "PUBLICATION_ID"
        ]
        if any(len(value) > _MAX_FIELD_CHARACTERS for value in (*raw_rins, *publications)):
            raise UnifiedAgendaSourceError("Unified Agenda identity field exceeds 4,096 characters")
        record_rins = [value.strip() for value in raw_rins]
        if len(record_rins) != 1 or not record_rins[0]:
            raise UnifiedAgendaSourceError("Unified Agenda record requires exactly one RIN")
        if [value.strip() for value in publications] != [edition.publication_id]:
            raise UnifiedAgendaSourceError("Unified Agenda record states another edition than the request")
        rin = record_rins[0]
        if rin in seen:
            raise UnifiedAgendaSourceError("Unified Agenda edition repeats a RIN")
        seen.add(rin)
        rins.append(rin)

    result = _read_records(body, on_record=validate_record, max_bytes=max_bytes, identity_only=True)
    if not rins:
        raise UnifiedAgendaSourceError("Unified Agenda edition lists no RIN_INFO records")
    return UnifiedAgendaMetadata(
        edition.file_stem,
        edition.publication_id,
        result.root.attributes.get("RUN_DATE"),
        result.root.attributes.get(_SCHEMA_LOCATION),
        result.record_count,
        tuple(rins),
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
        self,
        edition: UnifiedAgendaEdition,
        *,
        max_bytes: int | None = None,
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
