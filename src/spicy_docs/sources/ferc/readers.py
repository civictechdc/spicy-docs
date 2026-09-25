"""Reader connectors over the eLibrary routes: comments, accession file lists, new-docket windows and docket sheets.

Every reader follows the package's fetcher rules (``AGENTS.md``) the same way:

1. A 401/403 -- :class:`FercElibraryAccessRefusedError`, a ``CredentialRefusedError``
   subclass -- aborts the run and is never recorded as a key that merely failed.
2. A key that produced no records stays out of ``last_keys`` and lands in
   ``failed_keys`` with its last answer in ``failure_reasons`` (scrubbed, then
   truncated), so the next run asks again. That includes a refused identity and
   a requested-empty answer: its reason is ``requested-empty`` and
   ``empty_observations`` keeps the answer's UTC timestamp, separate from
   never-requested keys. A zero is an observation, never absence: identical
   eLibrary requests have answered zero and then hundreds of rows.
3. A walk that refuses partway yields nothing for its key.

Comment and accession rows are the publisher's rows exactly as served. New-docket
and docket-sheet rows are too (sheet rows flattened per ``DocumentsItem`` entry),
plus ``identity`` and the ``captureSha256`` of the page that served them. Readers
keep no response bytes: publication must consume the captures that
``FercElibraryReader.search_pages``, ``docket_sheet_pages``, ``file_list`` and
``new_dockets`` return.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable, Iterator, Mapping
from datetime import timedelta
from typing import Any

from spicy_docs.reading.paged_json import PagedJsonSourceError
from spicy_docs.sources.base import Reader
from spicy_docs.sources.ferc.elibrary import (
    MAX_PAGES,
    MAX_RESULTS_PER_PAGE,
    NEW_DOCKET_WINDOW_DAYS,
    NEW_DOCKETS_SORT,
    RULEMAKING_COMMENT,
    FercElibraryError,
    FercElibraryReader,
    accession_number,
    docket_id,
    docket_search_body,
    docket_sheet_body,
    new_docket_identity,
    new_dockets_url,
)
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError, failure_reason
from spicy_docs.transport.source_acquirer import utc_now

REQUESTED_EMPTY = "requested-empty"


def _record(row: Mapping[str, Any], identity: str, capture: CapturedBodyResponse) -> dict[str, Any]:
    """The served row verbatim, with its identity and the digest of the capture that served it."""
    return {**row, "identity": identity, "captureSha256": capture.sha256}


class _KeyedReader(Reader):
    """One fetch per key under the package's recovery rules; subclasses name the keys and fetch each."""

    def __init__(self) -> None:
        super().__init__()
        self.failure_reasons: dict[str, str] = {}
        self.empty_observations: dict[str, str] = {}

    @abstractmethod
    def _keys(self) -> Iterable[object]: ...

    @abstractmethod
    def _fetch(self, key: str) -> tuple[list[dict[str, Any]], str, list[str]]:
        """One key's records, the observation time of its first answer, and the keys it completes."""

    def _identity(self, raw: object) -> str:
        return str(raw)

    def iter_records(self) -> Iterator[dict[str, Any]]:
        self.last_keys, self.failed_keys = [], []
        self.failure_reasons, self.empty_observations = {}, {}
        for raw in self._keys():
            key = str(raw)
            try:
                key = self._identity(raw)
                records, observed_at, done = self._fetch(key)
            except CredentialRefusedError:
                raise
            except (FercElibraryError, PagedJsonSourceError) as error:
                self.failed_keys.append(key)
                self.failure_reasons[key] = failure_reason(error)
                continue
            if not records:
                self.failed_keys.append(key)
                self.failure_reasons[key] = REQUESTED_EMPTY
                self.empty_observations[key] = observed_at
                continue
            yield from records
            self.last_keys.extend(done)


class FercElibraryCommentReader(_KeyedReader):
    """Each docket's comment rows from ``Search/AdvancedSearch``, walked to the terminal page before any yields."""

    def __init__(
        self,
        reader: FercElibraryReader,
        dockets: Iterable[str],
        *,
        document_class: Iterable[tuple[str, str]] = (RULEMAKING_COMMENT,),
        results_per_page: int = MAX_RESULTS_PER_PAGE,
        max_pages: int = MAX_PAGES,
    ) -> None:
        super().__init__()
        self._reader = reader
        self._dockets = list(dockets)
        self._document_class = tuple(document_class)
        self._results_per_page = results_per_page
        self._max_pages = max_pages

    def _keys(self) -> Iterable[object]:
        return self._dockets

    def _identity(self, raw: object) -> str:
        return docket_id(raw)

    def _fetch(self, docket: str) -> tuple[list[dict[str, Any]], str, list[str]]:
        body = docket_search_body(docket, document_class=self._document_class, results_per_page=self._results_per_page)
        pages = list(self._reader.search_pages(body, max_pages=self._max_pages))
        return [dict(row) for page in pages for row in page.records], pages[0].capture.observed_at, [docket]


class FercElibraryAccessionReader(_KeyedReader):
    """Each named accession's file-list rows: document metadata keyed by accession number."""

    def __init__(self, reader: FercElibraryReader, accessions: Iterable[str]) -> None:
        super().__init__()
        self._reader = reader
        self._accessions = list(accessions)

    def _keys(self) -> Iterable[object]:
        return self._accessions

    def _identity(self, raw: object) -> str:
        return accession_number(raw)

    def _fetch(self, accession: str) -> tuple[list[dict[str, Any]], str, list[str]]:
        files = self._reader.file_list(accession)
        return [dict(row) for row in files.records], files.capture.observed_at, [accession]


class FercNewDocketReader(_KeyedReader):
    """One ``GetATMSdocs`` window's new dockets in one GET; ``last_keys`` holds each ``DocketFullNumber``.

    The window defaults to the publisher form's cap, the last ``NEW_DOCKET_WINDOW_DAYS``
    days through today (UTC); a wider override answered live anyway (2026-09-25). Every
    row's identity is checked before any row is yielded.
    """

    def __init__(
        self,
        reader: FercElibraryReader,
        mode: str,
        date_from: str | None = None,
        date_to: str | None = None,
        *,
        sort: str = NEW_DOCKETS_SORT,
    ) -> None:
        super().__init__()
        today = utc_now().date()
        self._reader = reader
        self._query = (
            mode,
            (today - timedelta(days=NEW_DOCKET_WINDOW_DAYS)).isoformat() if date_from is None else date_from,
            today.isoformat() if date_to is None else date_to,
        )
        self._sort = sort
        new_dockets_url(*self._query, sort=sort)
        self.window = f"{mode} {self._query[1]}..{self._query[2]}"

    def _keys(self) -> Iterable[object]:
        return (self.window,)

    def _fetch(self, _window: str) -> tuple[list[dict[str, Any]], str, list[str]]:
        listing = self._reader.new_dockets(*self._query, sort=self._sort)
        records = [_record(row, new_docket_identity(row), listing.capture) for row in listing.records]
        return records, listing.capture.observed_at, [record["identity"] for record in records]


class FercDocketSheetReader(_KeyedReader):
    """One docket's sheet documents from ``Docket/GetSingleDocketSheet``; ``last_keys`` holds each ``accession_no``."""

    def __init__(
        self,
        reader: FercElibraryReader,
        dockets: str,
        subdockets: str | None = "",
        *,
        date_from: str = "1960-01-01",
        date_to: str | None = None,
        complete_flag: int = 0,
        num_hits: int = MAX_RESULTS_PER_PAGE,
        max_pages: int = MAX_PAGES,
    ) -> None:
        super().__init__()
        self._reader = reader
        self._body = docket_sheet_body(
            dockets, subdockets, date_from=date_from, date_to=date_to, complete_flag=complete_flag, num_hits=num_hits
        )
        self._max_pages = max_pages
        subdocket = self._body["subdockets"]
        self.key = docket_id(dockets) + (f"-{subdocket}" if subdocket else "")

    def _keys(self) -> Iterable[object]:
        return (self.key,)

    def _fetch(self, _key: str) -> tuple[list[dict[str, Any]], str, list[str]]:
        pages = list(self._reader.docket_sheet_pages(self._body, max_pages=self._max_pages))
        # The walk already held every document's accession to the grammar and refused repeats.
        records = [_record(row, row["accession_no"], page.capture) for page in pages for row in page.records]
        return records, pages[0].capture.observed_at, [record["identity"] for record in records]


__all__ = [
    "REQUESTED_EMPTY",
    "FercDocketSheetReader",
    "FercElibraryAccessionReader",
    "FercElibraryCommentReader",
    "FercNewDocketReader",
]
