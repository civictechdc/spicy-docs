"""Stream CourtListener's published CSV dumps for keyless opinion text.

This complements spicy-regs' docket search reader. The REST opinions and clusters
endpoints required a token when checked on 2026-08-22; the bulk bucket supplies
full tables without one.

The S3 listing records published objects, exact sizes, and modification times.
The reader downloads and decompresses bzip2 incrementally. max_records and
max_compressed_bytes bound a partial ingest. Requests use an identifying
User-Agent and one connection, respecting the publisher's transfer rate.
"""

from __future__ import annotations

import bz2
import io
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Protocol

from loguru import logger

from spicy_docs.sources.base import Reader
from spicy_docs.sources.courtlistener_csv import (
    MAX_RECORD_CHARACTERS,
    CourtListenerCsvError,
    iter_postgres_csv,
    validate_record_limit,
)
from spicy_docs.sources.courtlistener_listing import (
    BULK_BASE_URL,
    BULK_LIST_URL,
    BULK_PREFIX,
    MAX_LISTING_PAGE_BYTES,
    BulkObject,
    parse_listing_page,
)

#: Identify honestly. CourtListener publishes this data for public reuse; the
#: least we owe them is a contactable agent string.
USER_AGENT = "spicy-regs/0.1 (+https://spicy-regs.dev) courtlistener-bulk-ingest"

_TIMEOUT = 180.0
_MAX_RETRIES = 5
_CHUNK = 4 << 20
_PROGRESS_EVERY = 50_000

_DECOMPRESSED_CHUNK = 64 * 1024


def _request(url: str, *, extra_headers: dict[str, str] | None = None):
    headers = {"User-Agent": USER_AGENT}
    if extra_headers:
        headers.update(extra_headers)
    return urllib.request.Request(url, headers=headers)


def _open(url: str, *, extra_headers: dict[str, str] | None = None):
    """Open a URL with bounded retries and exponential backoff."""
    last: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return urllib.request.urlopen(_request(url, extra_headers=extra_headers), timeout=_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - urllib raises a wide family
            last = exc
            if attempt == _MAX_RETRIES:
                break
            backoff = min(2**attempt, 60)
            logger.warning(
                "CourtListener bulk: {} (attempt {}/{}), retrying in {}s",
                exc,
                attempt,
                _MAX_RETRIES,
                backoff,
            )
            time.sleep(backoff)
    raise RuntimeError(f"CourtListener bulk: giving up on {url}") from last


def list_bulk_dumps(prefix: str = BULK_PREFIX) -> list[BulkObject]:
    """Enumerate every object under the bulk-data prefix, with exact sizes.

    This is the publisher's own enumeration of what exists. Coverage claims are
    checked against it, so it is fetched rather than assumed.
    """
    if not isinstance(prefix, str) or not prefix.startswith(BULK_PREFIX):
        raise ValueError("bulk listing prefix must stay under bulk-data/")
    found: list[BulkObject] = []
    seen_keys: set[str] = set()
    seen_tokens: set[str] = set()
    token: str | None = None
    while True:
        query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        with _open(BULK_LIST_URL + "?" + urllib.parse.urlencode(query)) as response:
            objects, token = parse_listing_page(response.read(MAX_LISTING_PAGE_BYTES + 1), prefix=prefix)
        for obj in objects:
            if obj.key in seen_keys:
                raise ValueError(f"bulk listing repeats object key across pages: {obj.key}")
            seen_keys.add(obj.key)
            found.append(obj)
        if token is None:
            break
        if token in seen_tokens:
            raise ValueError("bulk listing repeats a continuation token")
        seen_tokens.add(token)
    logger.info("CourtListener bulk: listing has {:,} objects", len(found))
    return found


def published_object_pin(
    dataset: str,
    dump_date: date,
    *,
    objects: list[BulkObject] | None = None,
    expect_bytes: int | None = None,
    expect_last_modified: str | None = None,
    expect_etag: str | None = None,
) -> dict[str, object]:
    """Record one published object's listing metadata and check caller expectations.

    Byte size, last-modified time, and the exact quoted ETag distinguish revisions
    of the same filename. These checks apply to the listing only: this helper does
    not bind later HTTP reads with If-Match or hash their content.

    DocSpec owns the pinned population in fixtures/courtlistener-bulk-v1/, including
    withdrawn versus declined objects. This helper records only the object read.
    """
    listing = objects if objects is not None else list_bulk_dumps()
    published = find_dump(listing, dataset, dump_date)
    if published is None:
        raise RuntimeError(f"CourtListener bulk: no {dataset} dump published for {dump_date}")
    if expect_bytes is not None and published.size != expect_bytes:
        raise RuntimeError(
            f"CourtListener bulk: {published.filename} is {published.size} bytes, "
            f"not the pinned {expect_bytes} — the publisher's object changed"
        )
    if expect_last_modified is not None and published.last_modified != expect_last_modified:
        raise RuntimeError(
            f"CourtListener bulk: {published.filename} was last modified "
            f"{published.last_modified}, not the pinned {expect_last_modified} — "
            f"the publisher's object changed"
        )
    if expect_etag is not None and published.etag != expect_etag:
        raise RuntimeError(
            f"CourtListener bulk: {published.filename} has ETag {published.etag!r}, "
            f"not the pinned {expect_etag!r} — the publisher's listing changed"
        )
    return {
        "dataset": dataset,
        "dump_date": dump_date.isoformat(),
        "filename": published.filename,
        "url": published.url,
        "bytes": published.size,
        "last_modified": published.last_modified,
        "etag": published.etag,
        "listing_object_count": len(listing),
        "listing_host": BULK_LIST_URL,
    }


def latest_dump_date(objects: list[BulkObject], dataset: str) -> date | None:
    """Newest dump date published for ``dataset``, or None if it has none."""
    dates = [o.dump_date for o in objects if o.dataset == dataset and o.dump_date]
    return max(dates) if dates else None


def find_dump(objects: list[BulkObject], dataset: str, dump_date: date) -> BulkObject | None:
    """The published object for one dataset at one dump date."""
    for obj in objects:
        if obj.dataset == dataset and obj.dump_date == dump_date:
            return obj
    return None


class _UnrangeableResume(RuntimeError):
    """A resume the server answered with a whole new stream instead of a range."""


class _BinarySource(Protocol):
    def read(self, size: int, /) -> bytes: ...

    def close(self) -> None: ...


class _CountingStream(io.RawIOBase):
    """Decompress an HTTP bzip2 stream while counting compressed bytes for the budget.

    After a read error, reopen resumes at the exact compressed offset and feeds the
    same decompressor. Without reopen, as for a local file, the error propagates.

    Concatenated bzip2 streams need a fresh decompressor at each boundary; carry
    unused_data forward so a publisher compressor change cannot truncate the dump.
    """

    def __init__(
        self,
        response: _BinarySource,
        *,
        max_compressed_bytes: int | None = None,
        reopen: Callable[[int], _BinarySource] | None = None,
    ) -> None:
        self._response = response
        self._reopen = reopen
        self._decompressor = bz2.BZ2Decompressor()
        self._buffer = b""
        self._max_compressed_bytes = max_compressed_bytes
        self.compressed_bytes = 0
        self.decompressed_bytes = 0
        self.resumes = 0
        self._exhausted = False
        self.budget_exhausted = False

    def readable(self) -> bool:
        return True

    def close(self) -> None:
        """Close whichever response is current — after a resume it is not the first."""
        try:
            self._response.close()
        except Exception:  # noqa: BLE001, S110 - closing a broken socket
            pass
        super().close()

    def _read_chunk(self, size: int) -> bytes:
        """Pull the next compressed chunk, reconnecting mid-stream if need be."""
        try:
            return self._response.read(size)
        except Exception as exc:
            if self._reopen is None:
                raise
            logger.warning(
                "CourtListener bulk: transfer failed after {:.3f} GiB ({}); resuming",
                self.compressed_bytes / 2**30,
                exc,
            )
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self._response.close()
            except Exception:  # noqa: BLE001, S110 - closing a broken socket
                pass
            try:
                resumed = self._reopen(self.compressed_bytes)
                # A server that ignores Range answers 200 and starts over from
                # byte zero. Feeding that to a decompressor already 30 GiB into
                # the stream does not fail — it produces garbage rows that look
                # like data, which is the one outcome worse than the dropped
                # connection this is recovering from.
                status = getattr(resumed, "status", None)
                if self.compressed_bytes and status != 206:
                    # Not retryable: a server that ignores Range will ignore it
                    # again, and every retry is another chance to splice.
                    resumed.close()
                    raise _UnrangeableResume(
                        f"CourtListener bulk: resume at byte {self.compressed_bytes} "
                        f"answered {status}, not 206 — refusing to splice a restarted "
                        f"stream onto a partial one"
                    )
                self._response = resumed
                self.resumes += 1
                return self._response.read(size)
            except _UnrangeableResume:
                raise
            except Exception as exc:
                if attempt == _MAX_RETRIES:
                    raise RuntimeError(
                        f"CourtListener bulk: could not resume at byte {self.compressed_bytes} after {attempt} attempts"
                    ) from exc
                backoff = min(2**attempt, 60)
                logger.warning(
                    "CourtListener bulk: resume attempt {}/{} failed ({}), retrying in {}s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    backoff,
                )
                time.sleep(backoff)
        return b""  # pragma: no cover - the loop either returns or raises

    def readinto(self, target) -> int:  # type: ignore[override]
        while not self._buffer and not self._exhausted:
            chunk = b""
            member_finished = self._decompressor.eof
            if member_finished:
                chunk = self._decompressor.unused_data
                self._decompressor = bz2.BZ2Decompressor()
            if not chunk and self._decompressor.needs_input:
                if self._max_compressed_bytes is not None and self.compressed_bytes >= self._max_compressed_bytes:
                    self.budget_exhausted = self._exhausted = True
                    break
                size = _CHUNK
                if self._max_compressed_bytes is not None:
                    size = min(size, self._max_compressed_bytes - self.compressed_bytes)
                chunk = self._read_chunk(size)
                if not chunk:
                    if not member_finished:
                        raise EOFError("CourtListener bulk: incomplete bzip2 member at source EOF")
                    self._exhausted = True
                    break
                self.compressed_bytes += len(chunk)
            # Drain already-read compressed bytes before checking the input budget.
            # max_length prevents one compressed chunk allocating an entire dump.
            self._buffer = self._decompressor.decompress(chunk, max_length=_DECOMPRESSED_CHUNK)
            self.decompressed_bytes += len(self._buffer)
        if not self._buffer:
            return 0
        size = min(len(target), len(self._buffer))
        target[:size] = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return size


class CourtListenerBulkReader(Reader):
    """Yield raw CSV rows from one CourtListener bulk dump, decompressed inline.

    Source strings, including quoted empty strings, remain strings. Unquoted
    empty fields become ``None``. Shaping belongs to the caller.

    ``local_file`` reads an already-downloaded ``.bz2`` instead of the network,
    which is how the small dumps are handled once cached. ``max_records`` and
    ``max_compressed_bytes`` bound a run; ``row_filter`` drops rows before they
    are materialized, which is what keeps a filtered pass over a huge dump cheap.
    """

    def __init__(
        self,
        dataset: str,
        *,
        dump_date: date | None = None,
        local_file: Path | None = None,
        max_records: int | None = None,
        max_compressed_bytes: int | None = None,
        max_record_characters: int = MAX_RECORD_CHARACTERS,
        row_filter: Callable[[dict], bool] | None = None,
    ) -> None:
        super().__init__()
        validate_record_limit(max_record_characters)
        self.max_record_characters = max_record_characters
        self.dataset = dataset
        self.dump_date = dump_date
        self.local_file = local_file
        self.max_records = max_records
        self.max_compressed_bytes = max_compressed_bytes
        self.row_filter = row_filter
        #: Populated during iteration so a caller can record the exact bound hit.
        self.rows_scanned = 0
        self.rows_yielded = 0
        self.compressed_bytes = 0
        self.decompressed_bytes = 0
        self.stopped_early = False
        self.source_url: str | None = None
        #: How many times the transfer had to be reconnected mid-dump. Belongs in
        #: a receipt: a pass that resumed twice read the same bytes as one that
        #: did not, but it is not the same run and should not be recorded as one.
        self.resumes = 0

    def _stream(self):
        if self.local_file is not None:
            self.source_url = str(self.local_file)
            return open(self.local_file, "rb"), None
        if self.dump_date is None:
            raise ValueError("dump_date is required when reading over the network")
        filename = f"{self.dataset}-{self.dump_date.isoformat()}.csv.bz2"
        url = f"{BULK_BASE_URL}/{filename}"
        self.source_url = url
        logger.info("CourtListener bulk: streaming {}", url)
        response = _open(url)
        return response, response

    def iter_records(self) -> Iterator[dict]:
        handle, response = self._stream()
        counter = _CountingStream(
            handle,
            max_compressed_bytes=self.max_compressed_bytes,
            reopen=(
                (lambda offset: _open(str(self.source_url), extra_headers={"Range": f"bytes={offset}-"}))
                if response is not None
                else None
            ),
        )
        completed = False
        try:
            with io.BufferedReader(counter) as raw:
                rows = iter_postgres_csv(
                    raw,
                    max_record_characters=self.max_record_characters,
                    is_truncated=lambda: counter.budget_exhausted,
                )
                header = next(rows, None)
                if header is None:
                    if counter.budget_exhausted:
                        return
                    raise CourtListenerCsvError("CourtListener CSV record 1: missing header")
                if any(name is None or name == "" for name in header) or len(set(header)) != len(header):
                    raise CourtListenerCsvError("CourtListener CSV record 1: header names must be nonempty and unique")
                for record_number, row in enumerate(rows, start=2):
                    if len(row) != len(header):
                        raise CourtListenerCsvError(
                            f"CourtListener CSV record {record_number}: expected {len(header)} columns, got {len(row)}"
                        )
                    self.rows_scanned += 1
                    if self.rows_scanned % _PROGRESS_EVERY == 0:
                        logger.info(
                            "CourtListener bulk {}: {:,} rows scanned, {:,} kept, {:.2f} GiB compressed",
                            self.dataset,
                            self.rows_scanned,
                            self.rows_yielded,
                            counter.compressed_bytes / 2**30,
                        )
                    record = dict(zip(header, row, strict=True))
                    if self.row_filter is not None and not self.row_filter(record):
                        continue
                    self.rows_yielded += 1
                    yield record
                    if self.max_records is not None and self.rows_yielded >= self.max_records:
                        self.stopped_early = True
                        break
                else:
                    completed = not counter.budget_exhausted
        finally:
            self.compressed_bytes = counter.compressed_bytes
            self.decompressed_bytes = counter.decompressed_bytes
            self.resumes = counter.resumes
            self.stopped_early = not completed
            counter.close()
        logger.info(
            "CourtListener bulk {}: {:,} scanned / {:,} yielded ({:.2f} GiB compressed read, {} resume(s))",
            self.dataset,
            self.rows_scanned,
            self.rows_yielded,
            self.compressed_bytes / 2**30,
            self.resumes,
        )
