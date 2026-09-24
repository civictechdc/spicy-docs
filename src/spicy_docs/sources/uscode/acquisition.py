"""Acquire explicit OLRC U.S. Code sources with exact bytes and bounded HTTP evidence.

Every route is keyless and public: one call captures one file or page, proves
the identity the request named against the bytes that came back, and hands the
caller the exact payload -- no route fallback, no implicit latest release point
and no disk cache. The zip routes send no ``Content-Type`` or ``Content-Length``
and so are proved from their bytes, a generated page cut short is a 200 the
readers refuse by name, and a title the publisher lists but does not serve
answers 302 rather than 404, so only the exact requested locator answering
404/410 raises :class:`UsCodeSourceUnavailableError`. No answer establishes
that Table III lacks an act; :func:`~spicy_docs.sources.uscode.table3.iter_table3_chain`
reads that from the links between the pages it serves.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from spicy_docs.sources.uscode.core import (
    DEFAULT_MAX_ARCHIVE_ENTRIES,
    DEFAULT_MAX_ENTRIES_PER_PAGE,
    DEFAULT_MAX_TABLE3_MEMBER_BYTES,
    DEFAULT_MAX_XML_BYTES,
    MAX_USCODE_BYTES,
    ReleasePoint,
    TitleSelection,
    UsCodeSourceError,
    annual_archive_locator,
    corpus_xml_locator,
    popular_names_locator,
    table3_act_locator,
    table3_bulk_locator,
    table3_file_name,
    title_xml_locator,
)
from spicy_docs.sources.uscode.popular_names import PopularNames, parse_popular_names
from spicy_docs.sources.uscode.table3 import (
    Table3Bulk,
    Table3Page,
    parse_table3_page,
    read_table3_bulk_archive,
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

from .archive import (
    AnnualArchive,
    UsCodeArchive,
    UsCodeTitleArchive,
    read_annual_archive,
    read_corpus_archive,
    read_title_archive,
)
from .classification import (
    CLASSIFICATION_INDEX_URL,
    ClassificationIndex,
    ClassificationTable,
    TableOrder,
    classification_table_locator,
    parse_classification_index,
    parse_classification_table,
)

if TYPE_CHECKING:
    import httpx

type UsCodeResult = (
    UsCodeTitleArchive
    | UsCodeArchive
    | AnnualArchive
    | PopularNames
    | Table3Page
    | Table3Bulk
    | ClassificationIndex
    | ClassificationTable
)

#: The empty string is the header the publisher does not send on any download
#: route. Accepting it declares that absence rather than hiding it; the zip
#: readers still refuse anything that is not a zip, with its bytes attached.
ZIP_MEDIA_TYPES = ("", "application/zip", "application/x-zip-compressed")
HTML_MEDIA_TYPES = ("text/html", "application/xhtml+xml")


@dataclass(frozen=True, slots=True)
class UsCodeAcquisitionBudget:
    """Bounds for each operation; pacing persists across the client's operations.

    Generated pages need a far longer timeout than files: the Popular Name Tool
    is assembled per request and took 435 seconds on 2026-09-14, where a title
    zip took 11. The whole-corpus zip is about 108 MB and an annual archive up
    to 88 MB, so archive routes need an explicit allowance well above a page's.
    """

    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_USCODE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class UsCodeAcquisition:
    """One captured OLRC source, the identity its bytes proved, and the budget it cost."""

    operation: str
    selection: dict[str, object] | None
    result: UsCodeResult
    capture: CapturedBodyResponse
    request_count: int
    budget: UsCodeAcquisitionBudget


class UsCodeSourceUnavailableError(UsCodeSourceError):
    """Only the exact requested locator has answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"U.S. Code source answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


class UsCodeAcquirer(SourceAcquirer):
    """A sequential source client. Callers select, retain and process captures."""

    def __init__(
        self,
        *,
        budget: UsCodeAcquisitionBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, UsCodeAcquisitionBudget):
            raise TypeError("budget must be a UsCodeAcquisitionBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-uscode/1.0",
            label="U.S. Code",
            error_type=UsCodeSourceError,
            context_key="uscode_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> UsCodeAcquisitionBudget:
        return self._budget

    def _acquire(
        self,
        url: str,
        *,
        operation: str,
        selection: dict[str, object] | None,
        media_types: tuple[str, ...],
        read: Callable[[bytes, int], UsCodeResult],
        max_bytes: int | None,
        retain_dropped_body: bool = False,
    ) -> UsCodeAcquisition:
        effective = replace(self.budget, max_bytes=narrow_byte_limit(self.budget.max_bytes, max_bytes))
        result, capture = self.capture_validated(
            url,
            media_types=media_types,
            parse=lambda response, limit: read(response.body, limit),
            max_bytes=effective.max_bytes,
            unavailable=UsCodeSourceUnavailableError,
            context={"operation": operation, "selection": selection, "budget": asdict(effective)},
            retain_dropped_body=retain_dropped_body,
        )
        return UsCodeAcquisition(operation, selection, result, capture, self.request_count, effective)

    def acquire_title(
        self,
        selection: TitleSelection,
        *,
        max_bytes: int | None = None,
        max_entry_bytes: int = DEFAULT_MAX_XML_BYTES,
    ) -> UsCodeAcquisition:
        """Capture one title's release-point zip and prove its native number and release point."""
        return self._acquire(
            title_xml_locator(selection),
            operation="release-point-title",
            selection={"release_point": selection.release_point.label, "title": selection.title},
            media_types=ZIP_MEDIA_TYPES,
            read=lambda body, limit: read_title_archive(
                body, selection=selection, max_bytes=limit, max_entry_bytes=max_entry_bytes
            ),
            max_bytes=max_bytes,
        )

    def acquire_corpus(
        self,
        release_point: ReleasePoint,
        *,
        max_bytes: int | None = None,
        max_entry_bytes: int = DEFAULT_MAX_XML_BYTES,
        max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
        max_total_bytes: int | None = None,
    ) -> UsCodeAcquisition:
        """Capture every title at one release point in one zip; each member proves its own identity."""
        return self._acquire(
            corpus_xml_locator(release_point),
            operation="release-point-corpus",
            selection={"release_point": release_point.label},
            media_types=ZIP_MEDIA_TYPES,
            read=lambda body, limit: read_corpus_archive(
                body,
                release_point=release_point,
                max_bytes=limit,
                max_entry_bytes=max_entry_bytes,
                max_entries=max_entries,
                max_total_bytes=max_total_bytes,
            ),
            max_bytes=max_bytes,
        )

    def acquire_annual_archive(
        self,
        year: int,
        *,
        max_bytes: int | None = None,
        max_entry_bytes: int = DEFAULT_MAX_XML_BYTES,
        max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
        max_total_bytes: int | None = None,
    ) -> UsCodeAcquisition:
        """Capture one year's XHTML archive; every title member states its own edition and year."""
        return self._acquire(
            annual_archive_locator(year),
            operation="annual-archive",
            selection={"year": year},
            media_types=ZIP_MEDIA_TYPES,
            read=lambda body, limit: read_annual_archive(
                body,
                year=year,
                max_bytes=limit,
                max_entry_bytes=max_entry_bytes,
                max_entries=max_entries,
                max_total_bytes=max_total_bytes,
            ),
            max_bytes=max_bytes,
        )

    def acquire_popular_names(
        self, *, max_bytes: int | None = None, max_entries: int = DEFAULT_MAX_ENTRIES_PER_PAGE
    ) -> UsCodeAcquisition:
        """Capture the whole Popular Name Tool page. It is generated per request and is slow."""
        return self._acquire(
            popular_names_locator(),
            operation="popular-names",
            selection=None,
            media_types=HTML_MEDIA_TYPES,
            read=lambda body, limit: parse_popular_names(body, max_bytes=limit, max_entries=max_entries),
            max_bytes=max_bytes,
        )

    def acquire_table3_act(
        self, key: str, *, max_bytes: int | None = None, max_rows: int = DEFAULT_MAX_ENTRIES_PER_PAGE
    ) -> UsCodeAcquisition:
        """Capture one act's Table III page and prove the act it states is the act requested.

        An act the table serves no page for answers 200, the first 16 KB of the
        site template, and a dropped connection: a transport failure, retried
        like any other. The error that escapes keeps the last attempt's bytes as
        its ``response-incomplete`` evidence. Those bytes are a prefix of every
        served page, so they never establish absence; the chain of pages does.
        """
        table3_file_name(key)
        return self._acquire(
            table3_act_locator(key),
            operation="table3-act",
            selection={"key": key},
            media_types=HTML_MEDIA_TYPES,
            read=lambda body, limit: parse_table3_page(body, key=key, max_bytes=limit, max_rows=max_rows),
            max_bytes=max_bytes,
            retain_dropped_body=True,
        )

    def acquire_table3_bulk(
        self,
        *,
        release_point: str | None = None,
        max_bytes: int | None = None,
        max_member_bytes: int = DEFAULT_MAX_TABLE3_MEMBER_BYTES,
    ) -> UsCodeAcquisition:
        """Capture the whole of Table III in one zip, as ``table3years.htm`` links it.

        Table III lags the Code: on 2026-09-14 the Code stood at 119-103 and this
        file at 119-73, which the member's own name states.
        """
        return self._acquire(
            table3_bulk_locator(),
            operation="table3-bulk",
            selection={"release_point": release_point} if release_point else None,
            media_types=ZIP_MEDIA_TYPES,
            read=lambda body, limit: read_table3_bulk_archive(
                body, release_point=release_point, max_bytes=limit, max_member_bytes=max_member_bytes
            ),
            max_bytes=max_bytes,
        )

    def acquire_classification_index(self, *, max_bytes: int | None = None) -> UsCodeAcquisition:
        """Capture ``classification/tables.shtml``: the links to the current Congress's session tables.

        Read this before a session table when the file name should come from
        the publisher rather than from :func:`classification_table_locator`'s
        grammar; the index proves itself by its own ``<title>``.
        """
        return self._acquire(
            CLASSIFICATION_INDEX_URL,
            operation="classification-index",
            selection=None,
            media_types=HTML_MEDIA_TYPES,
            read=lambda body, limit: parse_classification_index(body, max_bytes=limit),
            max_bytes=max_bytes,
        )

    def acquire_classification_table(
        self,
        congress: int,
        session: int,
        *,
        order: TableOrder = "public-law",
        max_bytes: int | None = None,
        max_rows: int = DEFAULT_MAX_ENTRIES_PER_PAGE,
    ) -> UsCodeAcquisition:
        """Capture one session's classification table and prove the Congress and session it states.

        The page states both in its caption; a page for another session, or
        a challenge page served with status 200, is refused before any row is
        read, with its bytes attached.
        """
        return self._acquire(
            classification_table_locator(congress, session, order),
            operation="classification-table",
            selection={"congress": congress, "session": session, "order": order},
            media_types=HTML_MEDIA_TYPES,
            read=lambda body, limit: parse_classification_table(
                body, congress=congress, session=session, order=order, max_bytes=limit, max_rows=max_rows
            ),
            max_bytes=max_bytes,
        )
