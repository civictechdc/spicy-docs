"""Bulk releases count original files and preserve every archive entry."""

import hashlib
import json
import struct
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

import pytest
from rulespec_artifacts import BlobIntegrityError, LocalMemberSource

from spicy_docs.reading.zip_archive import inspect_archive_stream
from spicy_docs.source_native import (
    MAX_EVIDENCE_BYTES,
    SourceNativeReleaseBuild,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native.profiles import FEC_BULK_FILES_PROFILE as PROFILE
from spicy_docs.sources.fec.bulk_profile import bulk_file_scope, iter_retained_bulk_files
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore, iter_verified_blob
from tests.releases.fixtures import IMPLEMENTATION_ID, PRODUCER

FIXTURES = Path(__file__).parent / "fixtures/fec/bulk"
URL = "https://www.fec.gov/files/bulk-downloads/2024/example.zip"


def _capture(raw, *, representation="zip", key="example.zip"):
    return {
        "requestUrl": URL.replace("example.zip", key),
        "objectKey": "bulk-downloads/2024/" + key,
        "observedAt": "2026-09-15T03:00:00Z",
        "responseSha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "byteSize": len(raw),
        "representation": representation,
    }


def _zip(entries):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        archive.comment = b"publisher\xffcomment"
        for name, raw in entries:
            info = ZipInfo(name, date_time=(2024, 1, 2, 3, 4, 6))
            info.comment = b"entry\xffcomment"
            archive.writestr(info, raw)
    return output.getvalue()


def _publish(
    tmp_path,
    captures,
    blobs,
    *,
    max_members=100,
    max_decoded_bytes=64 * 1024**2,
    pages=None,
    output=None,
    profile=PROFILE,
):
    scope = bulk_file_scope(captures, max_members=max_members, max_decoded_bytes=max_decoded_bytes)
    output = output or LocalSourceNativeBlobStore(tmp_path / "output-blobs")
    published = SourceNativeReleasePublisher(
        profile, blob_store=output, clock=lambda: datetime(2026, 9, 15, 4, tzinfo=UTC)
    ).publish(
        iter_retained_bulk_files(scope, blob_source=blobs) if pages is None else pages,
        build=SourceNativeReleaseBuild(query_scope=scope, producer=PRODUCER, started_at="2026-09-15T03:00:00Z"),
        destination=tmp_path / "release",
    )
    reader = SourceNativeReleaseReader(
        LocalMemberSource(published.root),
        blob_source=output,
        profile=profile,
        expected_pin=published.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )
    return reader


def _inputs(tmp_path, raw, **kwargs):
    capture = _capture(raw, **kwargs)
    blobs = LocalSourceNativeBlobStore(tmp_path / "originals")
    blobs.put_blob(capture["responseSha256"], len(raw), (raw,))
    return [capture], blobs


def test_retained_bulk_files_keep_complete_native_member_inventory_and_originals(tmp_path):
    selected = json.loads((FIXTURES / "sources.json").read_bytes())
    captures = [item["capture"] for item in selected]
    blobs = LocalSourceNativeBlobStore(tmp_path / "originals")
    for item in selected:
        raw = (FIXTURES / item["file"]).read_bytes()
        assert len(raw) == item["capture"]["byteSize"]
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == item["capture"]["responseSha256"]
        blobs.put_blob(item["capture"]["responseSha256"], len(raw), (raw,))
    reader = _publish(tmp_path, captures, blobs)
    rows = {row["sourceRecordId"]: row["record"] for row in reader.iter_records()}
    assert set(rows) == {capture["objectKey"] for capture in captures}
    for item in selected:
        capture = item["capture"]
        row = rows[capture["objectKey"]]
        assert row["capture"] == capture
        evidence = reader.record_evidence(capture["objectKey"])
        assert evidence["evidenceBlobRef"] == capture["responseSha256"]
        assert b"".join(reader.iter_evidence(evidence["evidenceBlobRef"])) == (FIXTURES / item["file"]).read_bytes()
        if capture["representation"] == "opaque":
            assert row["archive"] is None
            continue
        with ZipFile(FIXTURES / item["file"]) as archive:
            assert row["archive"]["commentHex"] == archive.comment.hex()
            assert len(row["archive"]["members"]) == len(archive.infolist())
            for member, info in zip(row["archive"]["members"], archive.infolist(), strict=True):
                assert member["name"] == info.orig_filename == "ccl.txt"
                assert member["sha256"] == "sha256:" + hashlib.sha256(archive.read(info)).hexdigest()
                assert (
                    member["byteSize"] == info.file_size
                    and member["crc32"] == f"{info.CRC:08x}"
                    and member["crcVerified"]
                )
    assert list(reader.iter_renditions()) == []
    assert reader.collection_outcome["sourceStateScope"] == "observed-crawl"
    assert reader.collection_outcome["requestedScope"]["captures"] == captures


def test_directories_empty_members_and_repeated_names_remain_distinct(tmp_path):
    entries = [
        ("folder/", b""),
        ("folder/data.txt", b"A|001|\n"),
        ("other/data.txt", b"B||0\n"),
        ("same.txt", b"first"),
        ("same.txt", b"second"),
        ("empty.txt", b""),
    ]
    with pytest.warns(UserWarning, match="Duplicate name"):
        raw = _zip(entries)
    captures, blobs = _inputs(tmp_path, raw)
    (wrapped,) = _publish(
        tmp_path, captures, blobs, max_members=len(entries), max_decoded_bytes=sum(len(value) for _, value in entries)
    ).iter_records()
    inventory = wrapped["record"]["archive"]
    assert inventory["commentHex"] == b"publisher\xffcomment".hex()
    members = inventory["members"]
    assert [m["ordinal"] for m in members] == list(range(len(entries)))
    assert [m["name"] for m in members] == [name for name, _ in entries]
    assert [m["sha256"] for m in members] == ["sha256:" + hashlib.sha256(raw).hexdigest() for _, raw in entries]
    assert members[0]["isDirectory"] is True and members[-1]["byteSize"] == 0
    assert all(m["commentHex"] == b"entry\xffcomment".hex() for m in members)


class _TrackingStream:
    def __init__(self, stream, reads):
        self.stream, self.reads = stream, reads

    def read(self, size=-1):
        assert size >= 0, "unbounded read"
        self.reads.append(size)
        return self.stream.read(size)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _TrackingStore(LocalSourceNativeBlobStore):
    def __init__(self, root):
        super().__init__(root)
        self.reads, self.opens = [], []

    @contextmanager
    def open(self, blob_ref):
        self.opens.append(blob_ref)
        with super().open(blob_ref) as stream:
            yield _TrackingStream(stream, self.reads)


def test_archive_above_old_limit_streams_and_reader_keeps_small_read_bound(tmp_path):
    # Synthetic stored ZIP proves the stream route engages above the existing byte-page bound.
    raw = _zip([("large.txt", b"x" * (MAX_EVIDENCE_BYTES + 1))])
    captures, blobs = _inputs(tmp_path, raw)
    output = _TrackingStore(tmp_path / "output-blobs")
    parse_calls = []

    def parse(stream, **kwargs):
        parse_calls.append(kwargs["byte_size"])
        return PROFILE.parse_page_stream(stream, **kwargs)

    reader = _publish(tmp_path, captures, blobs, output=output, profile=replace(PROFILE, parse_page_stream=parse))
    assert parse_calls == [len(raw), len(raw)]  # Publication and independent replay.
    assert max(output.reads) <= 2 * 1024**2
    ref = captures[0]["responseSha256"]
    output.opens.clear()
    digest = hashlib.sha256()
    for chunk in reader.iter_evidence(ref):
        assert len(chunk) <= 64 * 1024
        digest.update(chunk)
    assert "sha256:" + digest.hexdigest() == ref
    assert output.opens == [ref]
    with pytest.raises(ValueError, match="requested byte limit"):
        reader.read_evidence(ref)


def test_member_count_does_not_multiply_original_blob_opens(tmp_path):
    def measure(path, count):
        raw = _zip([(f"{index}.txt", b"content") for index in range(count)])
        captures, blobs = _inputs(path, raw)
        output = _TrackingStore(path / "output-blobs")
        _publish(path, captures, blobs, output=output)
        return output.opens.count(captures[0]["responseSha256"])

    assert measure(tmp_path / "one", 1) == measure(tmp_path / "many", 80)


@pytest.mark.parametrize("entries", [[], [("empty", b"")]])
def test_empty_archive_is_a_file_observation(tmp_path, entries):
    captures, blobs = _inputs(tmp_path, _zip(entries))
    reader = _publish(tmp_path, captures, blobs)
    (row,) = reader.iter_records()
    assert len(row["record"]["archive"]["members"]) == len(entries)
    assert reader.collection_outcome["recordOutcome"] != "empty"


@pytest.mark.parametrize("limit,value", [("max_members", 1), ("max_decoded_bytes", 1)])
def test_archive_bounds_refuse_before_member_payload_reads(tmp_path, monkeypatch, limit, value):
    raw = _zip([("a", b"123"), ("b", b"456")])
    captures, blobs = _inputs(tmp_path, raw)

    def forbidden(*args, **kwargs):
        pytest.fail("member payload opened before inventory bound was enforced")

    monkeypatch.setattr(ZipFile, "open", forbidden)
    with pytest.raises(ValueError, match="exceeds its bound"):
        _publish(tmp_path, captures, blobs, **{limit: value})
    assert not (tmp_path / "release").exists()


def test_directory_allocation_bound_precedes_zipfile_directory_read():
    raw = bytearray(_zip([("a", b"x")]))
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<I", raw, end + 12, 1024**3)
    with pytest.raises(ValueError, match="metadata read exceeds"):
        inspect_archive_stream(
            BytesIO(raw), byte_size=len(raw), max_entries=10, max_decoded_bytes=100, max_metadata_bytes=1024
        )


@pytest.mark.parametrize("damage", ["crc", "truncated", "wrong-format"])
def test_corrupt_archive_refuses_and_retains_exact_original(tmp_path, damage):
    raw = _zip([("data", b"UNIQUE_PAYLOAD")])
    raw = (
        raw.replace(b"UNIQUE_PAYLOAD", b"ALTEREDPAYLOAD")
        if damage == "crc"
        else raw[:-15]
        if damage == "truncated"
        else b"<html>denied</html>"
    )
    captures, blobs = _inputs(tmp_path, raw)
    with pytest.raises((ValueError, BadZipFile)) as raised:
        _publish(tmp_path, captures, blobs)
    report = raised.value.failed_acquisition["response"]
    assert report["status"] == "retained" and report["blobRef"] == captures[0]["responseSha256"]
    with LocalSourceNativeBlobStore(tmp_path / "output-blobs").open(report["blobRef"]) as stream:
        assert stream.read() == raw
    assert not (tmp_path / "release").exists()


def test_missing_selected_file_and_repeated_object_identity_refuse(tmp_path):
    raw = _zip([("data", b"row")])
    captures, blobs = _inputs(tmp_path, raw)
    other = {
        **captures[0],
        "objectKey": "bulk-downloads/2024/other.zip",
        "requestUrl": URL.replace("example.zip", "other.zip"),
    }
    captures.append(other)
    scope = bulk_file_scope(captures, max_members=10, max_decoded_bytes=100)
    pages = list(iter_retained_bulk_files(scope, blob_source=blobs))
    with pytest.raises(ValueError, match="omitted selected files"):
        _publish(tmp_path, captures, blobs, pages=pages[:-1])
    with pytest.raises(ValueError, match="identity differs or repeats"):
        bulk_file_scope([captures[0], captures[0]], max_members=10, max_decoded_bytes=100)


@pytest.mark.parametrize(
    "field,value",
    [
        ("objectKey", "bulk-downloads/wrong.zip"),
        ("responseSha256", "invalid"),
        ("byteSize", True),
        ("representation", "guess"),
        ("observedAt", "2024-01-01"),
        ("requestUrl", URL + "?api_key=secret"),
        ("resolvedUrl", URL.replace("example", "wrong")),
    ],
)
def test_capture_declaration_refusals(field, value):
    capture = {**_capture(b"x"), field: value}
    with pytest.raises(ValueError):
        bulk_file_scope([capture], max_members=10, max_decoded_bytes=100)


def test_pinned_stream_rejects_corrupt_short_and_excess_bytes_and_closes_early():
    class Source:
        closed = False
        value = b"right"

        @contextmanager
        def open(self, ref):
            try:
                yield BytesIO(self.value)
            finally:
                self.closed = True

    source = Source()
    ref = "sha256:" + hashlib.sha256(b"right").hexdigest()
    assert b"".join(iter_verified_blob(source, ref, 5)) == b"right"
    for value in (b"wrong", b"shorter", b"no"):
        source.value = value
        with pytest.raises(BlobIntegrityError):
            list(iter_verified_blob(source, ref, 5))
    source.value = b"right"
    source.closed = False
    chunks = iter_verified_blob(source, ref, 5)
    assert next(chunks) == b"right"
    chunks.close()
    assert source.closed


def test_opaque_original_is_pinned_without_invented_rows_or_member_format(tmp_path):
    raw = b"CMTE_ID|AMOUNT\nC00000001|000.00\nC00000001|\n"
    captures, blobs = _inputs(tmp_path, raw, representation="opaque", key="data.txt")
    (row,) = _publish(tmp_path, captures, blobs).iter_records()
    assert row["record"] == {"capture": captures[0], "archive": None}


def test_stream_evidence_requires_explicit_profile_opt_in(tmp_path):
    captures, blobs = _inputs(tmp_path, _zip([("data", b"row")]))
    profile = replace(PROFILE, parse_page_stream=None, max_evidence_bytes=MAX_EVIDENCE_BYTES)
    with pytest.raises(ValueError, match="explicit stream profile"):
        _publish(tmp_path, captures, blobs, profile=profile)


def test_nonseekable_output_provider_spools_without_unbounded_reads(tmp_path):
    class Stream:
        def __init__(self, original):
            self.original = original

        def seekable(self):
            return False

        def read(self, size):
            assert 0 < size <= 64 * 1024
            return self.original.read(min(size, 17))

    captures, blobs = _inputs(tmp_path, _zip([("data", b"row" * 100)]))

    # Default admission owns its own read sizes. Restrict only the new source parser's I/O.
    def parse(stream, **kwargs):
        return PROFILE.parse_page_stream(Stream(stream), **kwargs)

    (row,) = _publish(tmp_path, captures, blobs, profile=replace(PROFILE, parse_page_stream=parse)).iter_records()
    assert row["record"]["archive"]["members"][0]["byteSize"] == 300


def test_streamed_reader_rechecks_custom_provider_and_refuses_unknown_refs(tmp_path):
    captures, blobs = _inputs(tmp_path, _zip([("data", b"row")]))
    reader = _publish(tmp_path, captures, blobs)

    class ChangedSource:
        def __init__(self):
            self.opened = []

        @contextmanager
        def open(self, ref):
            self.opened.append(ref)
            yield BytesIO(b"changed")

    changed = ChangedSource()
    reader._blob_source = changed
    with pytest.raises(ValueError, match="not an admitted"):
        list(reader.iter_evidence("sha256:" + "0" * 64))
    assert changed.opened == []
    with pytest.raises(BlobIntegrityError):
        list(reader.iter_evidence(captures[0]["responseSha256"]))


def test_bulk_page_media_and_digest_must_match_selected_capture(tmp_path):
    captures, blobs = _inputs(tmp_path, _zip([("data", b"row")]))
    scope = bulk_file_scope(captures, max_members=10, max_decoded_bytes=100)
    (page,) = iter_retained_bulk_files(scope, blob_source=blobs)
    with pytest.raises(ValueError, match="media type differs"):
        _publish(tmp_path, captures, blobs, pages=[replace(page, evidence_media_type="application/octet-stream")])
    wrong = {**captures[0], "responseSha256": "sha256:" + "0" * 64}
    with pytest.raises(ValueError, match="capture pin"):
        _publish(tmp_path, [wrong], blobs, pages=[page])


@pytest.mark.parametrize("compression", [0, 8])
def test_understated_member_size_and_prefix_crc_cannot_hide_payload(tmp_path, compression):
    output = BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("data", b"hidden body")
    raw = bytearray(output.getvalue())
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<I", raw, 14, 0)  # Local CRC of the falsely empty member.
    struct.pack_into("<I", raw, 22, 0)  # Local decoded size.
    struct.pack_into("<I", raw, central + 16, 0)
    struct.pack_into("<I", raw, central + 24, 0)
    # A plain ZipExtFile reader accepts this prefix, so this is a discriminating control.
    with ZipFile(BytesIO(raw)) as archive:
        assert archive.read("data") == b""
    captures, blobs = _inputs(tmp_path, bytes(raw))
    with pytest.raises(ValueError, match="decoded member exceeds"):
        _publish(tmp_path, captures, blobs)


@pytest.mark.parametrize("compression", [0, 8])
def test_complete_member_decoder_preserves_empty_and_large_outputs(tmp_path, compression):
    output = BytesIO()
    expected = [b"", b"many bytes " * 100_000]
    with ZipFile(output, "w", compression=compression) as archive:
        for index, raw in enumerate(expected):
            archive.writestr(str(index), raw)
    captures, blobs = _inputs(tmp_path, output.getvalue())
    (row,) = _publish(tmp_path, captures, blobs).iter_records()
    assert [member["sha256"] for member in row["record"]["archive"]["members"]] == [
        "sha256:" + hashlib.sha256(raw).hexdigest() for raw in expected
    ]


@pytest.mark.parametrize("compression", [12, 14])
def test_compressors_without_bounded_decoding_refuse(tmp_path, compression):
    output = BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("data", b"body")
    captures, blobs = _inputs(tmp_path, output.getvalue())
    with pytest.raises(ValueError, match="bounded decoder"):
        _publish(tmp_path, captures, blobs)


def test_writer_failure_closes_source_iterator_before_error_returns(tmp_path):
    raw = _zip([("data", b"row")])
    captures = [_capture(raw)]

    class Source:
        closed = False

        @contextmanager
        def open(self, ref):
            try:
                yield BytesIO(raw)
            finally:
                self.closed = True

    class FailingStore(LocalSourceNativeBlobStore):
        def put_blob(self, ref, byte_size, chunks):
            assert next(iter(chunks))
            raise OSError("write failed")

    source = Source()
    with pytest.raises(OSError, match="write failed") as failure:
        _publish(tmp_path, captures, source, output=FailingStore(tmp_path / "output-blobs"))
    # Keep the traceback alive: garbage collection must not stand in for explicit closure.
    assert failure.value.__traceback__ is not None
    assert source.closed


@pytest.mark.parametrize("suffix", ["%FF.zip", "%FE.zip", "%E2%98%83.zip"])
def test_bulk_native_identity_refuses_lossy_or_unsupported_decoding(suffix):
    # Match the old lossy decoding so unrelated object-key mismatch cannot mask the guard.
    old_name = "☃.zip" if suffix == "%E2%98%83.zip" else "�.zip"
    capture = {
        **_capture(b"x"),
        "requestUrl": URL.replace("example.zip", suffix),
        "objectKey": "bulk-downloads/2024/" + old_name,
    }
    with pytest.raises(ValueError):
        bulk_file_scope([capture], max_members=10, max_decoded_bytes=100)


@pytest.mark.parametrize("encoding", ["identity", "Identity", "  IDENTITY  "])
def test_identity_length_witness_disagreement_refuses_opaque_capture(encoding):
    capture = {**_capture(b"short", representation="opaque"), "contentEncoding": encoding, "contentLength": "100"}
    with pytest.raises(ValueError, match="Content-Length differs"):
        bulk_file_scope([capture], max_members=10, max_decoded_bytes=100)
    capture["contentLength"] = "5"
    assert bulk_file_scope([capture], max_members=10, max_decoded_bytes=100)["captures"] == [capture]
    capture["contentLength"] = "100"
    capture["contentEncoding"] = "gzip"
    assert bulk_file_scope([capture], max_members=10, max_decoded_bytes=100)["captures"] == [capture]
