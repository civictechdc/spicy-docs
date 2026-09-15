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
    CourtListenerBulkReader,
    find_dump,
    latest_dump_date,
)
from spicy_docs.sources.courtlistener_listing import BulkObject


def _csv_bz2(tmp_path: Path, name: str, header: str, rows: list[str]) -> Path:
    """Write a bzip2 CSV the reader can stream, exactly as the dumps are shaped."""
    path = tmp_path / name
    body = "\n".join([header, *rows]) + "\n"
    path.write_bytes(bz2.compress(body.encode("utf-8")))
    return path


# -- listing / enumeration ---------------------------------------------------


def test_bulk_object_splits_dataset_from_dump_date():
    """Coverage is checked per dataset per dump, so both must parse out of the key."""
    obj = BulkObject(
        "bulk-data/opinion-clusters-2026-06-30.csv.bz2", 2_457_231_057, '"etag"', "2026-06-30T04:11:47.000Z"
    )
    assert obj.dataset == "opinion-clusters"
    assert obj.dump_date == date(2026, 6, 30)
    assert obj.filename == "opinion-clusters-2026-06-30.csv.bz2"
    assert obj.url.endswith("/bulk-data/opinion-clusters-2026-06-30.csv.bz2")

    # The bucket also holds undated one-off exports; those must not masquerade
    # as a dated dump of some dataset.
    undated = BulkObject("bulk-data/scotus_network.csv", 7_000, '"etag"', "2024-04-04T00:00:00.000Z")
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
            '"multipart-etag-25"',
            "2026-06-30T09:56:48.000Z",
        ),
        BulkObject("bulk-data/courts-2026-06-30.csv.bz2", 81_180, '"etag"', "2026-06-30T09:00:26.000Z"),
    ]

    pin = published_object_pin("opinions", date(2026, 6, 30), objects=listing)
    assert pin["bytes"] == 54_561_543_156
    assert pin["last_modified"] == "2026-06-30T09:56:48.000Z"
    assert pin["filename"] == "opinions-2026-06-30.csv.bz2"
    assert pin["listing_object_count"] == 2
    assert pin["etag"] == '"multipart-etag-25"'

    # Held against an expectation, it is a precondition rather than a note —
    # which is the only useful place to discover a changed object when reading
    # it costs 8.6 hours.
    published_object_pin(
        "opinions",
        date(2026, 6, 30),
        objects=listing,
        expect_bytes=54_561_543_156,
        expect_last_modified="2026-06-30T09:56:48.000Z",
        expect_etag='"multipart-etag-25"',
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
    with pytest.raises(RuntimeError, match="publisher's listing changed"):
        published_object_pin("opinions", date(2026, 6, 30), objects=listing, expect_etag="multipart-etag-25")
    with pytest.raises(RuntimeError, match="no opinions dump published"):
        published_object_pin("opinions", date(2026, 3, 31), objects=listing)


def test_latest_dump_date_and_find_dump_pick_one_published_object():
    objects = [
        BulkObject("bulk-data/opinions-2026-03-31.csv.bz2", 54_190_000_000, '"etag"', "2026-03-31T00:00:00Z"),
        BulkObject("bulk-data/opinions-2026-06-30.csv.bz2", 54_561_543_156, '"etag"', "2026-06-30T00:00:00Z"),
        BulkObject("bulk-data/courts-2026-06-30.csv.bz2", 81_180, '"etag"', "2026-06-30T00:00:00Z"),
    ]
    assert latest_dump_date(objects, "opinions") == date(2026, 6, 30)
    assert latest_dump_date(objects, "nonexistent") is None

    found = find_dump(objects, "opinions", date(2026, 6, 30))
    assert found is not None and found.size == 54_561_543_156
    assert find_dump(objects, "opinions", date(2020, 1, 1)) is None


# -- streaming reader --------------------------------------------------------


def test_reader_tracking_defaults_are_owned_by_each_instance():
    first = CourtListenerBulkReader("courts")
    second = CourtListenerBulkReader("opinions")

    first.last_keys.append("captured-key")
    first.failed_keys.append("failed-key")

    assert second.last_keys == []
    assert second.failed_keys == []


def test_reader_preserves_empty_strings_and_nulls(tmp_path: Path):
    path = _csv_bz2(
        tmp_path,
        "courts-2026-06-30.csv.bz2",
        "id,short_name,jurisdiction,notes",
        ["ca9,Ninth Circuit,F,", 'scotus,Supreme Court,F,""'],
    )
    rows = list(CourtListenerBulkReader("courts", local_file=path).iter_records())
    assert [r["id"] for r in rows] == ["ca9", "scotus"]
    assert rows[0]["notes"] is None
    assert rows[1]["notes"] == ""


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
        self.headers = {"ETag": '"fixture-object"', "Content-Length": str(len(payload) - offset)}
        if offset:
            self.headers["Content-Range"] = f"bytes {offset}-{len(payload) - 1}/{len(payload)}"
        self.closed = False

    def geturl(self):
        return "https://storage.courtlistener.com/bulk-data/fixture.csv.bz2"

    def read(self, size: int) -> bytes:
        if self._fail_after is not None and self._served >= self._fail_after:
            raise OSError("connection reset by peer")
        chunk = self._payload[self._pos : self._pos + size]
        self._pos += len(chunk)
        self._served += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


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

    def reopen(headers):
        offset = int(headers["Range"][6:-1])
        assert headers["If-Match"] == '"fixture-object"'
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

    refused = _FlakyResponse(payload, offset=0, fail_after=None, status=200)

    def restart_from_zero(headers):
        return refused

    stream = _CountingStream(_FlakyResponse(payload, offset=0, fail_after=2048), reopen=restart_from_zero)
    with pytest.raises(RuntimeError, match="not 206"):
        io.BufferedReader(stream).read()
    assert refused.closed


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


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"", "missing header"),
        (b"id,id\n1,2\n", "nonempty and unique"),
        (b"id,\n1,2\n", "nonempty and unique"),
        (b'id,""\n1,2\n', "nonempty and unique"),
        (b"id,name\n1\n", "expected 2 columns, got 1"),
        (b"id,name\n1,two,extra\n", "expected 2 columns, got 3"),
        (b"id\n\xff\n", "invalid UTF-8"),
    ],
)
def test_reader_refuses_lossy_header_or_row_recovery(tmp_path, body, reason):
    from spicy_docs.sources.courtlistener_csv import CourtListenerCsvError

    path = tmp_path / "dump.bz2"
    path.write_bytes(bz2.compress(body))
    reader = CourtListenerBulkReader("courts", local_file=path)
    with pytest.raises(CourtListenerCsvError, match=reason):
        list(reader.iter_records())
    assert reader.stopped_early
    assert reader.compressed_bytes == path.stat().st_size
    assert reader.decompressed_bytes == len(body)


def test_reader_keeps_counters_and_closes_on_early_generator_close(tmp_path, monkeypatch):
    from spicy_docs.sources import courtlistener_bulk

    path = _csv_bz2(tmp_path, "dump.bz2", "id,name", ["1,one", "2,two"])
    handles = []
    original = courtlistener_bulk._CountingStream.close

    def close(stream):
        handles.append(stream._response)
        original(stream)

    monkeypatch.setattr(courtlistener_bulk._CountingStream, "close", close)
    reader = CourtListenerBulkReader("courts", local_file=path)
    rows = reader.iter_records()
    assert next(rows)["id"] == "1"
    rows.close()
    assert reader.rows_scanned == reader.rows_yielded == 1
    assert reader.compressed_bytes == path.stat().st_size
    assert reader.stopped_early
    assert handles and all(handle.closed for handle in handles)


@pytest.mark.parametrize("partial", [b'"partial', b"partial", b"partial\xc3"])
def test_byte_budget_discards_partial_record_but_drains_complete_rows(tmp_path, monkeypatch, partial):
    from spicy_docs.sources import courtlistener_bulk

    first = bz2.compress(b"id\ncomplete\n" + partial)
    path = tmp_path / "dump.bz2"
    path.write_bytes(first + bz2.compress(b"rest\n"))
    monkeypatch.setattr(courtlistener_bulk, "_CHUNK", len(first))
    reader = CourtListenerBulkReader("courts", local_file=path, max_compressed_bytes=len(first))
    assert list(reader.iter_records()) == [{"id": "complete"}]
    assert reader.compressed_bytes == len(first)
    assert reader.decompressed_bytes == len(b"id\ncomplete\n" + partial)
    assert reader.rows_scanned == reader.rows_yielded == 1
    assert reader.stopped_early


def test_highly_compressed_input_is_drained_in_bounded_blocks(monkeypatch):
    from spicy_docs.sources import courtlistener_bulk

    original = b"a" * (2 * 1024 * 1024)
    payload = bz2.compress(original)
    monkeypatch.setattr(courtlistener_bulk, "_DECOMPRESSED_CHUNK", 1024)
    stream = courtlistener_bulk._CountingStream(io.BytesIO(payload))
    block = bytearray(17)
    recovered = bytearray()
    while size := stream.readinto(block):
        assert len(stream._buffer) <= 1024
        recovered.extend(block[:size])
    assert bytes(recovered) == original
    assert stream.decompressed_bytes == len(original)
    assert stream.compressed_bytes == len(payload)


def test_record_bound_is_configurable_on_reader(tmp_path):
    from spicy_docs.sources.courtlistener_csv import CourtListenerCsvError

    path = _csv_bz2(tmp_path, "dump.bz2", "id", ['"12345"'])
    assert list(CourtListenerBulkReader("courts", local_file=path, max_record_characters=7).iter_records()) == [
        {"id": "12345"}
    ]
    with pytest.raises(CourtListenerCsvError, match="record 2: exceeds 6"):
        list(CourtListenerBulkReader("courts", local_file=path, max_record_characters=6).iter_records())


@pytest.mark.parametrize("concatenated", [False, True])
def test_natural_eof_requires_complete_bzip2_footer(tmp_path, concatenated):
    from spicy_docs.sources.courtlistener_bulk import _CountingStream

    body = b"id\ncomplete\nunterminated-tail"
    member = bz2.compress(body)
    # All CSV bytes are available before these footer bytes. A missing footer
    # must still prevent this transport from reporting a completed dump.
    assert bz2.BZ2Decompressor().decompress(member[:-5]) == body
    payload = (bz2.compress(b"id\nfirst\n") if concatenated else b"") + member[:-5]
    path = tmp_path / "truncated.bz2"
    path.write_bytes(payload)
    reader = CourtListenerBulkReader("courts", local_file=path)
    with pytest.raises(EOFError, match="incomplete bzip2 member"):
        list(reader.iter_records())
    assert reader.stopped_early
    assert reader.compressed_bytes == len(payload)
    # Direct stream access has the same completion requirement.
    with pytest.raises(EOFError, match="incomplete bzip2 member"):
        io.BufferedReader(_CountingStream(io.BytesIO(payload))).read()


def test_one_byte_budget_does_not_read_an_entire_compressed_chunk(tmp_path):
    path = _csv_bz2(tmp_path, "dump.bz2", "id", ["first", "second"])
    reader = CourtListenerBulkReader("courts", local_file=path, max_compressed_bytes=1)
    assert list(reader.iter_records()) == []
    assert reader.compressed_bytes == 1
    assert reader.stopped_early


def test_unaligned_budget_caps_the_resumed_read_and_closes_current_response(monkeypatch):
    from spicy_docs.sources import courtlistener_bulk

    monkeypatch.setattr(courtlistener_bulk, "_CHUNK", 1024)
    payload = bz2.compress(b"id,name\n" + b"".join(b"%d,row %d\n" % (i, i) for i in range(4000)))
    resumed = []

    class Response(_FlakyResponse):
        closed = False

        def close(self):
            self.closed = True

    def reopen(headers):
        offset = int(headers["Range"][6:-1])
        response = Response(payload, offset=offset, fail_after=None)
        resumed.append(response)
        return response

    stream = courtlistener_bulk._CountingStream(
        Response(payload, offset=0, fail_after=1024),
        max_compressed_bytes=1025,
        reopen=reopen,
    )
    with io.BufferedReader(stream) as raw:
        raw.read()
    assert stream.compressed_bytes == 1025
    assert stream.resumes == 1
    assert stream.budget_exhausted
    assert len(resumed) == 1 and resumed[0]._served == 1 and resumed[0].closed
