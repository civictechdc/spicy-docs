"""Hermetic tests for the CourtListener bulk-dump ingest (no network).

Covers the pieces with real logic: parsing the publisher's S3 listing into
dataset/date pairs (which is how coverage gets checked at all), and the
streaming bzip2 CSV reader and its two bounds.

Trimmed from spicy-regs' ``tests/test_courtlistener_bulk.py``: the raw-row ->
published-schema shaping tests and the disk-headroom guard exercised
``spicy_regs.transforms.build_court_opinion_bodies`` /
``build_court_opinion_clusters``, which are ETL/rollup modules that stayed
behind in spicy-regs. Only the reader itself (BulkObject, CourtListenerBulkReader,
find_dump, latest_dump_date) is this product's concern.
"""

from __future__ import annotations

import bz2
import io
from datetime import date
from pathlib import Path

import pytest

from spicy_docs.sources.courtlistener_bulk import (
    BulkObject,
    CourtListenerBulkReader,
    find_dump,
    latest_dump_date,
)


def _csv_bz2(tmp_path: Path, name: str, header: str, rows: list[str]) -> Path:
    """Write a bzip2 CSV the reader can stream, exactly as the dumps are shaped."""
    path = tmp_path / name
    body = "\n".join([header, *rows]) + "\n"
    path.write_bytes(bz2.compress(body.encode("utf-8")))
    return path


# -- listing / enumeration ---------------------------------------------------


def test_bulk_object_splits_dataset_from_dump_date():
    """Coverage is checked per dataset per dump, so both must parse out of the key."""
    obj = BulkObject("bulk-data/opinion-clusters-2026-06-30.csv.bz2", 2_457_231_057, "2026-06-30T04:11:47.000Z")
    assert obj.dataset == "opinion-clusters"
    assert obj.dump_date == date(2026, 6, 30)
    assert obj.filename == "opinion-clusters-2026-06-30.csv.bz2"
    assert obj.url.endswith("/bulk-data/opinion-clusters-2026-06-30.csv.bz2")

    # The bucket also holds undated one-off exports; those must not masquerade
    # as a dated dump of some dataset.
    undated = BulkObject("bulk-data/scotus_network.csv", 7_000, "2024-04-04T00:00:00.000Z")
    assert undated.dump_date is None
    assert undated.dataset == "scotus_network"


def test_published_object_pin_identifies_what_a_capture_read():
    """A receipt naming a filename has named a filename, not a thing.

    The publisher's listing carries the object's exact byte size and
    last-modified stamp, which is what makes two runs comparable and makes "the
    dump was re-cut under us" a detectable event rather than an unexplained
    difference in row counts. DocSpec pins the *population* at
    ``fixtures/courtlistener-bulk-v1/``; this pins the one object a run read,
    and lets that be checked against DocSpec's before the reading starts.
    """
    from spicy_docs.sources.courtlistener_bulk import published_object_pin

    listing = [
        BulkObject(
            "bulk-data/opinions-2026-06-30.csv.bz2",
            54_561_543_156,
            "2026-06-30T09:56:48.000Z",
        ),
        BulkObject("bulk-data/courts-2026-06-30.csv.bz2", 81_180, "2026-06-30T09:00:26.000Z"),
    ]

    pin = published_object_pin("opinions", date(2026, 6, 30), objects=listing)
    assert pin["bytes"] == 54_561_543_156
    assert pin["last_modified"] == "2026-06-30T09:56:48.000Z"
    assert pin["filename"] == "opinions-2026-06-30.csv.bz2"
    assert pin["listing_object_count"] == 2

    # Held against an expectation, it is a precondition rather than a note —
    # which is the only useful place to discover a changed object when reading
    # it costs 8.6 hours.
    published_object_pin(
        "opinions",
        date(2026, 6, 30),
        objects=listing,
        expect_bytes=54_561_543_156,
        expect_last_modified="2026-06-30T09:56:48.000Z",
    )
    with pytest.raises(RuntimeError, match="the publisher's object changed"):
        published_object_pin("opinions", date(2026, 6, 30), objects=listing, expect_bytes=1)
    with pytest.raises(RuntimeError, match="the publisher's object changed"):
        published_object_pin(
            "opinions",
            date(2026, 6, 30),
            objects=listing,
            expect_last_modified="2026-07-01T00:00:00.000Z",
        )
    with pytest.raises(RuntimeError, match="no opinions dump published"):
        published_object_pin("opinions", date(2026, 3, 31), objects=listing)


def test_latest_dump_date_and_find_dump_pick_one_published_object():
    objects = [
        BulkObject("bulk-data/opinions-2026-03-31.csv.bz2", 54_190_000_000, ""),
        BulkObject("bulk-data/opinions-2026-06-30.csv.bz2", 54_561_543_156, ""),
        BulkObject("bulk-data/courts-2026-06-30.csv.bz2", 81_180, ""),
    ]
    assert latest_dump_date(objects, "opinions") == date(2026, 6, 30)
    assert latest_dump_date(objects, "nonexistent") is None

    found = find_dump(objects, "opinions", date(2026, 6, 30))
    assert found is not None and found.size == 54_561_543_156
    assert find_dump(objects, "opinions", date(2020, 1, 1)) is None


# -- streaming reader --------------------------------------------------------


def test_reader_streams_rows_and_normalizes_blanks(tmp_path: Path):
    path = _csv_bz2(
        tmp_path,
        "courts-2026-06-30.csv.bz2",
        "id,short_name,jurisdiction,notes",
        ["ca9,Ninth Circuit,F,", "scotus,Supreme Court,F,seat of last resort"],
    )
    rows = list(CourtListenerBulkReader("courts", local_file=path).iter_records())
    assert [r["id"] for r in rows] == ["ca9", "scotus"]
    # An empty CSV field is absence, not the empty string — downstream NULL
    # handling depends on that being decided here rather than per-transform.
    assert rows[0]["notes"] is None
    assert rows[1]["notes"] == "seat of last resort"


def test_reader_honors_the_record_bound_and_reports_it(tmp_path: Path):
    """A bounded run must be *recorded* as bounded, so coverage is not overclaimed."""
    path = _csv_bz2(
        tmp_path,
        "opinions-2026-06-30.csv.bz2",
        "id,cluster_id",
        [f"{i},{i * 10}" for i in range(1, 51)],
    )
    reader = CourtListenerBulkReader("opinions", local_file=path, max_records=7)
    rows = list(reader.iter_records())
    assert len(rows) == 7
    assert reader.rows_yielded == 7
    assert reader.stopped_early is True

    unbounded = CourtListenerBulkReader("opinions", local_file=path)
    assert len(list(unbounded.iter_records())) == 50
    assert unbounded.stopped_early is False


def test_reader_applies_the_row_filter_before_materializing(tmp_path: Path):
    """Filtering is what makes a targeted pass over a 50 GiB dump affordable."""
    path = _csv_bz2(
        tmp_path,
        "opinions-2026-06-30.csv.bz2",
        "id,cluster_id",
        ["1,100", "2,200", "3,100"],
    )
    wanted = {"100"}
    reader = CourtListenerBulkReader(
        "opinions", local_file=path, row_filter=lambda row: (row.get("cluster_id") or "") in wanted
    )
    rows = list(reader.iter_records())
    assert [r["id"] for r in rows] == ["1", "3"]
    assert reader.rows_scanned == 3
    assert reader.rows_yielded == 2


def test_reader_reads_the_dumps_backslash_escaped_quotes(tmp_path: Path):
    """The dumps escape an embedded quote as ``\\"``, not as the doubled ``""``.

    Read with the stdlib default dialect this does not raise — it *desyncs*, and
    the prose after the escaped quote becomes the next record's first column.
    Measured on the real 2026-06-30 opinion-clusters dump that corrupted 1,987 of
    the first 3,000 rows and dropped ``docket_id`` on two thirds of them, which
    would have silently destroyed the docket join. A regression here is a data
    corruption, not a parse error, so it is pinned.
    """
    path = _csv_bz2(
        tmp_path,
        "opinion-clusters-2026-06-30.csv.bz2",
        "id,case_name,docket_id",
        [r'"7290305","Ex parte \"Doe\", Inc.","64278691"', '"7290306","Plain v. Simple","64278692"'],
    )
    rows = list(CourtListenerBulkReader("opinion-clusters", local_file=path).iter_records())
    assert [r["id"] for r in rows] == ["7290305", "7290306"]
    assert rows[0]["case_name"] == 'Ex parte "Doe", Inc.'
    # The row after the escaped quote must still be a row, with its join key intact.
    assert rows[0]["docket_id"] == "64278691"
    assert rows[1]["docket_id"] == "64278692"


def test_reader_handles_embedded_newlines_in_opinion_text(tmp_path: Path):
    """Opinion bodies contain newlines inside quoted fields; a naive line split loses rows."""
    path = _csv_bz2(
        tmp_path,
        "opinions-2026-06-30.csv.bz2",
        "id,plain_text",
        ['1,"line one\nline two"', "2,short"],
    )
    rows = list(CourtListenerBulkReader("opinions", local_file=path).iter_records())
    assert len(rows) == 2
    assert rows[0]["plain_text"] == "line one\nline two"


# -- resuming a long transfer ------------------------------------------------


class _FlakyResponse:
    """Serve bytes from an offset and die once, the way a long socket does."""

    def __init__(
        self,
        payload: bytes,
        *,
        offset: int,
        fail_after: int | None,
        status: int | None = None,
    ) -> None:
        self._payload = payload
        self._pos = offset
        self._served = 0
        self._fail_after = fail_after
        self.status = status if status is not None else (206 if offset else 200)

    def read(self, size: int) -> bytes:
        if self._fail_after is not None and self._served >= self._fail_after:
            raise OSError("connection reset by peer")
        chunk = self._payload[self._pos : self._pos + size]
        self._pos += len(chunk)
        self._served += len(chunk)
        return chunk

    def close(self) -> None:
        return None


def test_counting_stream_resumes_a_dropped_transfer_at_the_exact_offset(monkeypatch):
    """8.6 hours on one socket will be interrupted; the pass must survive it.

    The resumed request must start at the compressed byte already consumed and
    feed the *same* decompressor — bzip2 wants its bytes in order, not in one
    connection. If the offset were wrong the failure would not be an error, it
    would be corrupt text, so this pins the recovered bytes against the original.
    """
    from spicy_docs.sources import courtlistener_bulk
    from spicy_docs.sources.courtlistener_bulk import _CountingStream

    original = ("id,body\n" + "".join(f"{i},row {i}\n" for i in range(4000))).encode()
    payload = bz2.compress(original)
    # Read in small bites so the drop lands mid-dump, as a real one would.
    monkeypatch.setattr(courtlistener_bulk, "_CHUNK", 1024)
    assert len(payload) > 4096, "test payload must be big enough to interrupt mid-stream"

    ranges: list[int] = []

    def reopen(offset: int):
        ranges.append(offset)
        return _FlakyResponse(payload, offset=offset, fail_after=None)

    stream = _CountingStream(_FlakyResponse(payload, offset=0, fail_after=2048), reopen=reopen)
    recovered = io.BufferedReader(stream).read()

    assert recovered == original
    assert stream.resumes == 1
    # Resumed once, from what was actually consumed — not from zero, not a guess.
    assert ranges == [2048]
    assert stream.compressed_bytes == len(payload)


def test_a_resume_that_restarts_the_stream_is_refused_not_spliced(monkeypatch):
    """A server that ignores Range answers 200 and starts over from byte zero.

    Splicing that onto a transfer already gigabytes in does not raise — the
    decompressor happily produces garbage that looks like rows. Refusing is the
    only safe answer, and it has to be checked rather than assumed, because the
    whole point of the resume is that nobody is watching when it happens.
    """
    from spicy_docs.sources import courtlistener_bulk
    from spicy_docs.sources.courtlistener_bulk import _CountingStream

    payload = bz2.compress(b"id,body\n" + b"".join(b"%d,row\n" % i for i in range(4000)))
    monkeypatch.setattr(courtlistener_bulk, "_CHUNK", 1024)

    def restart_from_zero(offset: int):
        return _FlakyResponse(payload, offset=0, fail_after=None, status=200)

    stream = _CountingStream(_FlakyResponse(payload, offset=0, fail_after=2048), reopen=restart_from_zero)
    with pytest.raises(RuntimeError, match="not 206"):
        io.BufferedReader(stream).read()


def test_counting_stream_reads_a_concatenated_bzip2_dump():
    """``pbzip2`` writes many streams; a plain decompressor stops at the first.

    The publisher's dumps are single-stream today. If that ever changes, a
    decompressor that raises ``EOFError`` past the first boundary would end a
    pass early — which is a coverage number that is quietly wrong, the failure
    mode this ingest most has to avoid.
    """
    from spicy_docs.sources.courtlistener_bulk import _CountingStream

    payload = bz2.compress(b"id,body\n1,first\n") + bz2.compress(b"2,second\n")
    stream = _CountingStream(_FlakyResponse(payload, offset=0, fail_after=None))
    assert io.BufferedReader(stream).read() == b"id,body\n1,first\n2,second\n"


def test_reader_raises_on_a_broken_local_read_rather_than_resuming(tmp_path: Path):
    """Resume is a network affordance; a local file has no ``Range`` to ask for."""
    from spicy_docs.sources.courtlistener_bulk import _CountingStream

    stream = _CountingStream(_FlakyResponse(b"anything", offset=0, fail_after=0))
    with pytest.raises(OSError, match="connection reset"):
        io.BufferedReader(stream).read()
