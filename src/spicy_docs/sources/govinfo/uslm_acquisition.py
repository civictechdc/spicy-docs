"""Acquire explicit GovInfo USLM sources with exact bytes and bounded HTTP evidence.

Public and private laws and statute compilations are keyless bulkdata. Each
call captures one file or one archive, proves the native identity the request
named, and hands the caller the exact payload. No route fallback, no implicit
latest choice, and no disk cache.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from spicy_docs.sources.govinfo.uslm import (
    DEFAULT_MAX_ARCHIVE_ENTRIES,
    DEFAULT_MAX_BYTES,
    MAX_USLM_BYTES,
    LawKind,
    PublicLawSelection,
    StatuteCompilationSelection,
    UslmArchive,
    UslmMetadata,
    UslmSourceError,
    public_law_archive_locator,
    public_law_xml_locator,
    read_public_law_archive,
    read_statute_compilations_archive,
    statute_compilation_xml_locator,
    statute_compilations_archive_locator,
    validate_public_law_xml,
    validate_statute_compilation_xml,
)
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

type UslmSelection = PublicLawSelection | StatuteCompilationSelection | tuple[int, LawKind] | None


@dataclass(frozen=True, slots=True)
class UslmAcquisitionBudget:
    """Bounds for each operation; pacing persists across the client's operations.

    Archives need a larger explicit allowance than single files: the statute
    compilations zip is about 81 MB and a Congress of public laws up to 10 MB.
    """

    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_USLM_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class UslmXmlAcquisition:
    selection: PublicLawSelection | StatuteCompilationSelection
    metadata: UslmMetadata
    capture: CapturedBodyResponse
    request_count: int
    budget: UslmAcquisitionBudget


@dataclass(frozen=True, slots=True)
class UslmArchiveAcquisition:
    selection: tuple[int, LawKind] | None
    archive: UslmArchive
    capture: CapturedBodyResponse
    request_count: int
    budget: UslmAcquisitionBudget


class UslmSourceUnavailableError(UslmSourceError):
    """Only the exact requested locator has answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"USLM source answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


def _selection_fields(selection: UslmSelection) -> dict | None:
    if isinstance(selection, (PublicLawSelection, StatuteCompilationSelection)):
        return asdict(selection)
    if selection is None:
        return None
    return {"congress": selection[0], "kind": selection[1]}


class UslmAcquirer(SourceAcquirer):
    """A sequential source client. Callers select, retain and process captures."""

    def __init__(
        self,
        *,
        budget: UslmAcquisitionBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, UslmAcquisitionBudget):
            raise TypeError("budget must be a UslmAcquisitionBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-uslm/1.0",
            label="USLM",
            error_type=UslmSourceError,
            context_key="uslm_acquisition",
            transport=transport,
            clock=clock,
        )

    @property
    def budget(self) -> UslmAcquisitionBudget:
        return self._budget

    def _acquire[Result](
        self,
        url: str,
        *,
        operation: str,
        selection: UslmSelection,
        media_types: tuple[str, ...],
        parse: Callable[[CapturedBodyResponse, int], Result],
        max_bytes: int | None,
    ) -> tuple[Result, CapturedBodyResponse, UslmAcquisitionBudget]:
        effective_budget = replace(self.budget, max_bytes=narrow_byte_limit(self.budget.max_bytes, max_bytes))
        result, capture = self.capture_validated(
            url,
            media_types=media_types,
            parse=parse,
            max_bytes=effective_budget.max_bytes,
            unavailable=UslmSourceUnavailableError,
            context={
                "operation": operation,
                "selection": _selection_fields(selection),
                "budget": asdict(effective_budget),
            },
        )
        return result, capture, effective_budget

    def _xml(
        self,
        url: str,
        selection: PublicLawSelection | StatuteCompilationSelection,
        operation: str,
        validate: Callable[[bytes, str, int], UslmMetadata],
        max_bytes: int | None,
    ) -> UslmXmlAcquisition:
        metadata, capture, budget = self._acquire(
            url,
            operation=operation,
            selection=selection,
            media_types=("application/xml", "text/xml"),
            parse=lambda response, limit: validate(response.body, response.resolved_url, limit),
            max_bytes=max_bytes,
        )
        return UslmXmlAcquisition(selection, metadata, capture, self._http.request_count, budget)

    def _archive(
        self,
        url: str,
        selection: tuple[int, LawKind] | None,
        operation: str,
        read: Callable[[bytes, int], UslmArchive],
        max_bytes: int | None,
    ) -> UslmArchiveAcquisition:
        archive, capture, budget = self._acquire(
            url,
            operation=operation,
            selection=selection,
            media_types=("application/zip",),
            parse=lambda response, limit: read(response.body, limit),
            max_bytes=max_bytes,
        )
        return UslmArchiveAcquisition(selection, archive, capture, self._http.request_count, budget)

    def acquire_public_law(self, selection: PublicLawSelection, *, max_bytes: int | None = None) -> UslmXmlAcquisition:
        """Capture one law's USLM XML and prove its native Congress, kind, number and citation."""
        return self._xml(
            public_law_xml_locator(selection),
            selection,
            "public-law",
            lambda xml, url, limit: validate_public_law_xml(xml, selection=selection, final_url=url, max_bytes=limit),
            max_bytes,
        )

    def acquire_statute_compilation(
        self, selection: StatuteCompilationSelection, *, max_bytes: int | None = None
    ) -> UslmXmlAcquisition:
        """Capture one compilation and prove its native file identifier; its currency stays raw."""
        return self._xml(
            statute_compilation_xml_locator(selection),
            selection,
            "statute-compilation",
            lambda xml, url, limit: validate_statute_compilation_xml(
                xml, selection=selection, final_url=url, max_bytes=limit
            ),
            max_bytes,
        )

    def acquire_public_law_archive(
        self,
        congress: int,
        kind: LawKind,
        *,
        max_bytes: int | None = None,
        max_entry_bytes: int = DEFAULT_MAX_BYTES,
        max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
    ) -> UslmArchiveAcquisition:
        """Capture one Congress/kind zip; every entry is validated against its own name."""
        return self._archive(
            public_law_archive_locator(congress, kind),
            (congress, kind),
            "public-law-archive",
            lambda body, limit: read_public_law_archive(
                body,
                congress=congress,
                kind=kind,
                max_bytes=limit,
                max_entry_bytes=max_entry_bytes,
                max_entries=max_entries,
            ),
            max_bytes,
        )

    def acquire_statute_compilations_archive(
        self,
        *,
        max_bytes: int | None = None,
        max_entry_bytes: int = DEFAULT_MAX_BYTES,
        max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
    ) -> UslmArchiveAcquisition:
        """Capture the whole-collection zip; every compilation is validated against its own name."""
        return self._archive(
            statute_compilations_archive_locator(),
            None,
            "statute-compilations-archive",
            lambda body, limit: read_statute_compilations_archive(
                body, max_bytes=limit, max_entry_bytes=max_entry_bytes, max_entries=max_entries
            ),
            max_bytes,
        )
