"""Counted FCC filing walks that partition crowded queries by submission timestamp."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from spicy_docs.reading.paged_json import (
    JsonPage,
    PagedJsonSourceError,
    WalkPass,
    pool_walks,
    pooled_reach,
    query_value,
    walk_page_sizes,
    with_query,
)
from spicy_docs.sources.fcc_ecfs import FILINGS_KEY, filings_url

if TYPE_CHECKING:
    from spicy_docs.sources.fcc_ecfs import FccEcfsReader

# Measured September 25, 2026: offset 9,999 succeeds, 10,000 answers an HTML
# error, despite the download plan recommending deeper offsets. Keep a terminal
# short page reachable even on a repeated walk with a smaller page size.
MAX_RESULT_WINDOW = 10_000
_LABEL = "FCC ECFS filings"
_MILLISECOND = timedelta(milliseconds=1)


def _count(page: JsonPage) -> int:
    """Count the native boolean field; an approximate or missing aggregation refuses."""
    try:
        aggregation = json.loads(page.capture.body)["aggregations"]["express_comment"]
        buckets = aggregation["buckets"]
        if any(
            type(aggregation[field]) is not int or aggregation[field] != 0
            for field in ("doc_count_error_upper_bound", "sum_other_doc_count")
        ) or not isinstance(buckets, list):
            raise ValueError
        keys = [bucket["key"] for bucket in buckets]
        if any(type(key) is not int or key not in (0, 1) for key in keys) or len(set(keys)) != len(keys):
            raise ValueError
        counts = [bucket["doc_count"] for bucket in buckets]
        if any(type(count) is not int or count < 0 for count in counts):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise PagedJsonSourceError(f"{_LABEL} needs an exact express_comment aggregation") from None
    if any(
        type(record.get("express_comment")) not in (int, bool) or record["express_comment"] not in (0, 1)
        for record in page.records
    ):
        # Observed missing fields cannot tell us how many unseen rows lack it.
        raise PagedJsonSourceError(f"{_LABEL} served a record without a scalar express_comment flag")
    return sum(counts)


def _utc(value: str) -> datetime:
    # ECFS also stores legacy timezone-free timestamps; its UTC range query
    # selects those same instants (retained September 25, 2026 probes).
    instant = datetime.fromisoformat(value)
    return instant.replace(tzinfo=UTC) if instant.tzinfo is None else instant.astimezone(UTC)


def _instant(record: Mapping[str, Any], field: str = "date_submission") -> datetime:
    try:
        value = record[field]
        if not isinstance(value, str) or "T" not in value:
            raise ValueError
        return _utc(value)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise PagedJsonSourceError(f"{_LABEL} needs a usable {field} on every filing of this selection") from None


def _stamp(instant: datetime) -> str:
    # The live API rejected default isoformat bounds (zero/six fractional
    # digits) and accepted the same range with exactly three digits.
    return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _floor_millisecond(instant: datetime) -> datetime:
    return instant.replace(microsecond=instant.microsecond // 1000 * 1000)


@dataclass(frozen=True)
class _Window:
    """Only boundary identities survive a completed leaf, not its filing bodies."""

    count: int
    first: frozenset[str | int]
    last: frozenset[str | int]


def iter_filings(
    reader: FccEcfsReader,
    *,
    received_from: str,
    received_to: str,
    proceeding: str | None,
    limit: int,
    on_page: Callable[[JsonPage], None] | None,
) -> Iterator[Mapping[str, Any]]:
    """Keep application selection and persistence outside the source traversal."""
    url = filings_url(received_from=received_from, received_to=received_to, limit=limit, descending=False)
    if proceeding is not None:
        if not isinstance(proceeding, str) or not proceeding.strip():
            raise PagedJsonSourceError("proceeding must be a nonempty docket name")
        url = with_query(url, "proceedings.name", proceeding)
    url = with_query(url, "sort", "date_submission,ASC")
    sizes = walk_page_sizes(limit)
    reachable = pooled_reach(limit, MAX_RESULT_WINDOW)
    # Check each row against the filters actually sent: an ignored filter and
    # one that matched nothing look the same, so the count cannot prove scope.
    received = [_utc(bound) for bound in query_value(url, "date_received").removeprefix("[gte]").split("[lte]")]

    def read(address: str) -> JsonPage:
        page = reader.page(address, records_key=FILINGS_KEY)
        if on_page is not None:
            on_page(page)
        for record in page.records:
            if not received[0] <= _instant(record, "date_received") <= received[1]:
                raise PagedJsonSourceError(f"{_LABEL} served a filing received outside the requested dates")
            if proceeding is not None and not any(
                isinstance(item, Mapping) and item.get("name") == proceeding for item in record.get("proceedings") or ()
            ):
                raise PagedJsonSourceError(f"{_LABEL} served a filing outside proceeding {proceeding}")
        return page

    def stable(page: JsonPage, expected: int) -> None:
        if _count(page) != expected:
            raise PagedJsonSourceError(f"{_LABEL} count changed during the selection; retry it")

    def pooled(address: str, first_page: JsonPage, count: int):
        def walk(index: int) -> WalkPass:
            size = sizes[index % len(sizes)]
            page = first_page if index == 0 else read(with_query(address, "limit", str(size)))
            records: list[Mapping[str, Any]] = []
            while True:
                stable(page, count)
                records.extend(page.records)
                if page.next_url is None:
                    return WalkPass(tuple(records), count)
                if len(records) + size > MAX_RESULT_WINDOW:
                    raise PagedJsonSourceError(f"{_LABEL} exceeded its counted result window")
                page = read(page.next_url)

        return pool_walks(walk, key=lambda row: row.get("id_submission"), label=_LABEL)

    def visit(
        start: datetime,
        end: datetime,
        *,
        exclude_start: bool = False,
        expected: int | None = None,
    ) -> Generator[Mapping[str, Any], None, _Window]:
        address = with_query(url, "date_submission", f"[gte]{_stamp(start)}[lte]{_stamp(end)}")
        page = read(address)
        count = _count(page)
        if expected is not None:
            stable(page, expected)
        if count < reachable:
            result = pooled(address, page, count)
            lower, upper = set(), set()
            for row in result.records:
                instant = _instant(row)
                if not start <= instant <= end:
                    raise PagedJsonSourceError(f"{_LABEL} served a timestamp outside its requested partition")
                identity = row["id_submission"]
                if instant == start:
                    lower.add(identity)
                if instant == end:
                    upper.add(identity)
                if not (exclude_start and instant == start):
                    yield row
            return _Window(count, frozenset(lower), frozenset(upper))

        # Release the probe body before descending: memory follows one bounded
        # leaf plus boundary IDs, rather than the archive or ancestor pages.
        del page
        if end - start > _MILLISECOND:
            # Closed children share the midpoint instant; the right child re-reads it and must agree.
            midpoint = _floor_millisecond(start + (end - start) // 2)
            left = yield from visit(start, midpoint, exclude_start=exclude_start)
            right = yield from visit(midpoint, end, exclude_start=True)
            shared, agree = left.last, left.last == right.first
        elif end > start:
            # Adjacent milliseconds share no instant: split into two disjoint point queries.
            left = yield from visit(start, start, exclude_start=exclude_start)
            right = yield from visit(end, end)
            shared, agree = frozenset(), True
        else:
            raise PagedJsonSourceError(f"{_LABEL} cannot split a crowded tied timestamp; narrow the selection")
        if not agree or left.count + right.count - len(shared) != count:
            raise PagedJsonSourceError(f"{_LABEL} partitions do not reconcile with their parent count; retry it")
        return _Window(count, left.first, right.last)

    first_page = read(url)
    count = _count(first_page)
    if count < reachable:
        yield from pooled(url, first_page, count).records
        return
    if not first_page.records:
        raise PagedJsonSourceError(f"{_LABEL} counted filings but supplied no submission timestamp bound")
    start = _floor_millisecond(_instant(first_page.records[0]))
    del first_page
    last_page = read(with_query(with_query(url, "sort", "date_submission,DESC"), "limit", "1"))
    stable(last_page, count)
    if not last_page.records:
        raise PagedJsonSourceError(f"{_LABEL} supplied no final submission timestamp bound")
    end = _instant(last_page.records[0])
    if remainder := end.microsecond % 1000:
        end += timedelta(microseconds=1000 - remainder)
    del last_page
    if end < start:
        raise PagedJsonSourceError(f"{_LABEL} submission timestamp bounds are reversed")
    # Recheck the unpartitioned count against the timestamp-bounded selection:
    # omitted or malformed submission timestamps must not silently disappear.
    yield from visit(start, end, expected=count)
