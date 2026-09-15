"""Whole-stream replay, exact positional values, bounded pages and stream lifetime."""

import csv
import hashlib
import io
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest
from rulespec_artifacts import LocalMemberSource

from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher, SourceNativeReleaseReader
from spicy_docs.sources.fec.row_profile import (
    FEC_POSITIONAL_ROWS_PROFILE as PROFILE,
)
from spicy_docs.sources.fec.row_profile import (
    iter_retained_positional_rows,
    positional_row_scope,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import IMPLEMENTATION_ID, PRODUCER
from tests.test_fec_bulk_release import FIXTURES, _capture, _TrackingStore, _zip


def _publish(tmp, raw, *, capture=None, profile=PROFILE, output=None, pages=None, **options):
    capture = capture or _capture(raw, representation="opaque")
    options = {
        "format": "delimited",
        "encoding": "utf-8",
        "delimiter": "|",
        "quoting": "literal",
        "max_records_per_page": 2,
        **options,
    }
    scope = positional_row_scope(capture, **options)
    originals = LocalSourceNativeBlobStore(tmp / "originals")
    originals.put_blob(capture["responseSha256"], len(raw), (raw,))
    output = output or LocalSourceNativeBlobStore(tmp / "blobs")
    release = SourceNativeReleasePublisher(
        profile, blob_store=output, clock=lambda: datetime(2026, 9, 15, 12, tzinfo=UTC)
    ).publish(
        iter_retained_positional_rows(scope, blob_source=originals) if pages is None else pages,
        build=SourceNativeReleaseBuild(query_scope=scope, producer=PRODUCER, started_at="2026-09-15T11:00:00Z"),
        destination=tmp / "release",
    )
    return SourceNativeReleaseReader(
        LocalMemberSource(release.root),
        blob_source=output,
        profile=profile,
        expected_pin=release.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )


def _records(reader):
    return [row["record"] for row in reader.iter_records()]


def test_rows_keep_headers_blanks_leading_zeros_quotes_and_duplicate_values(tmp_path):
    raw = b'ID|Amount|Note\r\n001|0.1000|"quoted"\r\n\r\n001|0.1000|"quoted"\nLAST||\n'
    reader = _publish(tmp_path, raw)
    rows = _records(reader)
    expected = [
        ["ID", "Amount", "Note"],
        ["001", "0.1000", '"quoted"'],
        [],
        ["001", "0.1000", '"quoted"'],
        ["LAST", "", ""],
    ]
    assert [row["record"]["fields"] for row in rows] == expected
    assert [row["ordinal"] for row in rows] == list(range(5))
    assert len({row["id"] for row in rows}) == 5
    assert rows[1]["id"] != rows[3]["id"]
    for row, line in zip(rows, raw.splitlines(keepends=True), strict=True):
        ref = row["record"]["source"]
        assert raw[ref["byte_offset"] : ref["byte_offset"] + ref["byte_length"]] == line
    assert reader.collection_outcome["acquisitionEvidenceCount"] == 1
    assert list(reader.iter_renditions()) == []
    assert b"".join(reader.iter_evidence(_capture(raw)["responseSha256"])) == raw


def test_quoted_csv_multiline_records_keep_exact_byte_ranges(tmp_path):
    raw = b'Id,Text,Amount\n1,"two\nlines",0.00\r\n2,"a ""quote""",\n'
    rows = _records(_publish(tmp_path, raw, delimiter=",", quoting="csv"))
    assert [row["record"]["fields"] for row in rows] == list(csv.reader(io.StringIO(raw.decode(), newline="")))
    ref = rows[1]["record"]["source"]
    assert raw[ref["byte_offset"] : ref["byte_offset"] + ref["byte_length"]] == b'1,"two\nlines",0.00\r\n'


def test_native_zip_member_all_rows_match_independent_csv(tmp_path):
    selected = json.loads((FIXTURES / "sources.json").read_bytes())[0]
    raw = (FIXTURES / selected["file"]).read_bytes()
    reader = _publish(
        tmp_path, raw, capture=selected["capture"], member={"ordinal": 0, "name": "ccl.txt"}, max_records_per_page=1000
    )
    with ZipFile(io.BytesIO(raw)) as archive:
        member = archive.read(archive.infolist()[0])
    rows = _records(reader)
    assert [row["record"]["fields"] for row in rows] == list(
        csv.reader(io.StringIO(member.decode()), delimiter="|", quoting=csv.QUOTE_NONE)
    )
    assert rows and all(row["member"] == {"ordinal": 0, "name": "ccl.txt"} for row in rows)
    member_digest = "sha256:" + hashlib.sha256(member).hexdigest()
    assert all(row["record"]["source"]["sha256"] == member_digest for row in rows)
    assert b"".join(reader.iter_evidence(selected["capture"]["responseSha256"])) == raw


def test_duplicate_member_names_require_exact_ordinal(tmp_path):
    with pytest.warns(UserWarning, match="Duplicate name"):
        raw = _zip([("data.txt", b"first|001\n"), ("data.txt", b"second|002\n")])
    rows = _records(_publish(tmp_path, raw, capture=_capture(raw), member={"ordinal": 1, "name": "data.txt"}))
    assert rows[0]["record"]["fields"] == ["second", "002"]
    assert rows[0]["member"]["ordinal"] == 1


@pytest.mark.parametrize("member", [{"ordinal": 0, "name": "wrong"}, {"ordinal": 1, "name": "data"}])
def test_selected_member_disagreement_refuses(tmp_path, member):
    raw = _zip([("data", b"row\n")])
    with pytest.raises(ValueError, match="member"):
        _publish(tmp_path, raw, capture=_capture(raw), member=member)
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252", "latin-1"])
def test_whole_stream_encoding_is_explicit(tmp_path, encoding):
    raw = "café|001\n".encode(encoding)
    assert _records(_publish(tmp_path, raw, encoding=encoding))[0]["record"]["fields"] == ["café", "001"]


def test_filing_header_unknown_rows_and_bodies_remain_source_faithful(tmp_path):
    raw = (
        b"HDR\x1cFEC\x1c8.5\nF1N\x1cC00000001\x1c001\n"
        b"TEXT\x1cC00000001\x1ctx\x1cparent\x1cSC/10\x1cExact text\x1cextra\n"
        b"[BEGINTEXT]\r\nSecond body\r\n[ENDTEXT]\nUNKNOWN\x1c001\n"
    )
    capture = {**_capture(raw, representation="opaque"), "requestUrl": "https://docquery.fec.gov/dcdev/posted/123.fec"}
    rows = _records(_publish(tmp_path, raw, capture=capture, format="fec", delimiter=None, quoting=None))
    assert [row["record"]["kind"] for row in rows] == ["header", "record", "record", "text", "record"]
    assert rows[0]["record"]["format_version"] == "8.5"
    assert rows[-1]["record"]["fields"] == {"0": "UNKNOWN", "1": "001"}
    assert "5" not in rows[2]["record"]["fields"]
    assert rows[2]["record"]["fields"]["6"] == "extra"
    body = rows[3]["record"]["embedded_bodies"][0]
    assert raw[body["byte_offset"] : body["byte_offset"] + body["byte_length"]] == b"Second body\r\n"


def test_empty_zip_member_yields_observed_empty_release(tmp_path):
    raw = _zip([("empty", b"")])
    reader = _publish(tmp_path, raw, capture=_capture(raw), member={"ordinal": 0, "name": "empty"})
    assert _records(reader) == []
    assert reader.collection_outcome["requestedScope"]["member"]["name"] == "empty"


def test_page_count_does_not_multiply_original_opens_and_parser_stays_live(tmp_path):
    counts = []
    for name, count in [("one", 1000), ("many", 1)]:
        output = _TrackingStore(tmp_path / name / "output")
        parser_calls = []

        def parser(stream, parser_calls=parser_calls, count=count, **kwargs):
            parser_calls.append(kwargs["evidence_ref"])
            assert not stream.closed
            for response in PROFILE.parse_file_stream(stream, **kwargs):
                assert not stream.closed
                assert len(response["results"]) <= count
                yield response
            assert not stream.closed

        raw = b"001|0.00\n" * 40
        reader = _publish(
            tmp_path / name,
            raw,
            output=output,
            profile=replace(PROFILE, parse_file_stream=parser),
            max_records_per_page=count,
        )
        assert len(_records(reader)) == 40
        assert len(parser_calls) == 2  # Publication and independent source replay.
        counts.append(output.opens.count(_capture(raw)["responseSha256"]))
    assert counts[0] == counts[1]


def test_nonseekable_zip_provider_and_short_reads_keep_all_rows(tmp_path):
    class Nonseekable(io.BytesIO):
        def seekable(self):
            return False

        def seek(self, *args):
            raise io.UnsupportedOperation()

        def read(self, size=-1):
            assert size >= 0
            return super().read(min(size, 17))

    class Store(LocalSourceNativeBlobStore):
        @contextmanager
        def open(self, ref):
            with super().open(ref) as stream:
                raw = stream.read(65536)
            with Nonseekable(raw) as selected:
                yield selected

    raw = _zip([("data", b"001|0\n002|\n")])
    rows = _records(
        _publish(
            tmp_path,
            raw,
            capture=_capture(raw),
            member={"ordinal": 0, "name": "data"},
            output=Store(tmp_path / "blobs"),
        )
    )
    assert [r["record"]["fields"] for r in rows] == [["001", "0"], ["002", ""]]


@pytest.mark.parametrize("damage", ["missing", "extra", "extra-none", "key", "late-error"])
def test_stream_refusals_do_not_publish_partial_release(tmp_path, damage):
    calls = 0
    closed = []

    def parser(stream, **kwargs):
        nonlocal calls
        calls += 1
        try:
            for page in PROFILE.parse_file_stream(stream, **kwargs):
                # Change replay only: publication/replay must compare entire streams.
                if calls == 2 and damage == "missing" and page["page"] == 1:
                    return
                if calls == 2 and damage == "key":
                    page = {**page, "requestKey": "fec-rows://page/999"}
                yield page
            if calls == 2 and damage == "extra":
                yield page
            if calls == 2 and damage == "extra-none":
                yield None
            if calls == 2 and damage == "late-error":
                raise ValueError("late parse refusal")
        finally:
            closed.append(calls)

    with pytest.raises(ValueError):
        _publish(tmp_path, b"a|1\nb|2\nc|3\n", profile=replace(PROFILE, parse_file_stream=parser))
    assert closed == [1, 2]
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize(
    "options",
    [
        {"max_records_per_page": 0},
        {"max_record_bytes": 131073},
        {"format": "auto"},
        {"encoding": "auto"},
        {"quoting": None},
        {"member": {"ordinal": 0, "name": "x"}},
    ],
)
def test_unsupported_or_ambiguous_scope_refuses(tmp_path, options):
    with pytest.raises(ValueError):
        _publish(tmp_path, b"a|b\n", **options)


def test_record_bound_refuses_after_prior_page_without_partial_success(tmp_path):
    with pytest.raises(ValueError, match="byte bound"):
        _publish(tmp_path, b"a|1\nb|2\n" + b"z" * 50, max_records_per_page=1, max_record_bytes=10)
    assert not (tmp_path / "release").exists()


def test_plain_iterator_parser_is_a_supported_injected_implementation(tmp_path):
    def parser(stream, **kwargs):
        return iter(list(PROFILE.parse_file_stream(stream, **kwargs)))

    assert len(_records(_publish(tmp_path, b"a|1\n", profile=replace(PROFILE, parse_file_stream=parser)))) == 1


def test_output_page_bytes_are_bounded_independently_of_record_count(tmp_path):
    from rulespec_artifacts import canonical_json_bytes

    from spicy_docs.sources.fec.row_profile import MAX_PAGE_BYTES

    observed = []

    def parser(stream, **kwargs):
        for response in PROFILE.parse_file_stream(stream, **kwargs):
            observed.append(len(canonical_json_bytes(response)))
            yield response

    raw = (b"001|" + b"x" * 100000 + b"\n") * 12
    reader = _publish(tmp_path, raw, max_records_per_page=1000, profile=replace(PROFILE, parse_file_stream=parser))
    assert len(_records(reader)) == 12
    assert len(observed) == 4 and max(observed) <= MAX_PAGE_BYTES


def test_consumer_error_closes_current_original_and_parser(tmp_path):
    streams, closed = [], []

    def parser(stream, **kwargs):
        streams.append(stream)
        try:
            yield from PROFILE.parse_file_stream(stream, **kwargs)
        finally:
            closed.append(True)

    def wrap(row, **kwargs):
        raise RuntimeError("consumer stopped")

    with pytest.raises(RuntimeError, match="consumer stopped") as failure:
        _publish(tmp_path, b"a|1\nb|2\n", profile=replace(PROFILE, parse_file_stream=parser, wrap_record=wrap))
    assert failure.value.__traceback__ is not None
    assert closed == [True] and all(stream.closed for stream in streams)


def test_second_original_is_refused_before_opening_it(tmp_path):
    from spicy_docs.source_native import SourceNativeBlobPage

    raw = b"a|1\n"
    capture = _capture(raw, representation="opaque")
    originals = LocalSourceNativeBlobStore(tmp_path / "selected")
    originals.put_blob(capture["responseSha256"], len(raw), (raw,))

    class ForbiddenSource:
        def open(self, ref):
            raise AssertionError("second original must not be opened")

    first = SourceNativeBlobPage(
        0, 0, "fec-rows://page/0", capture["responseSha256"], len(raw), originals, "application/octet-stream"
    )
    extra = replace(first, page_index=1, blob_ref="sha256:" + "1" * 64, blob_source=ForbiddenSource())
    with pytest.raises(ValueError, match="one initial original"):
        _publish(tmp_path, raw, pages=[first, extra])


def test_page_bound_includes_response_fields_and_array_separators(monkeypatch):
    from rulespec_artifacts import canonical_json_bytes

    from spicy_docs.sources.fec import row_profile

    raw = b"a|1\nb|2\n"
    capture = _capture(raw, representation="opaque")
    scope = positional_row_scope(capture, format="delimited", encoding="utf-8", delimiter="|", quoting="literal")
    kwargs = {
        "query_scope": scope,
        "request_key": "fec-rows://page/0",
        "evidence_ref": capture["responseSha256"],
        "byte_size": len(raw),
        "media_type": "application/octet-stream",
    }
    (original,) = PROFILE.parse_file_stream(io.BytesIO(raw), **kwargs)
    bound = len(canonical_json_bytes(original)) - 1
    monkeypatch.setattr(row_profile, "MAX_PAGE_BYTES", bound)
    pages = list(PROFILE.parse_file_stream(io.BytesIO(raw), **kwargs))
    assert len(pages) == 2 and all(len(canonical_json_bytes(page)) <= bound for page in pages)


def test_filing_options_refuse_before_opening_original(monkeypatch):
    from spicy_docs.sources.fec import filings

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid options must not open an original")

    monkeypatch.setattr(filings, "LocalBlobSource", forbidden)
    with pytest.raises(ValueError, match="select"):
        list(filings.filing_records(store=None, sha256="unused", encoding="guess"))


@pytest.mark.parametrize(
    "source",
    json.loads((Path(__file__).parent / "fixtures/fec/rows/sources.json").read_bytes()),
    ids=lambda source: source["file"],
)
def test_retained_financial_and_filing_originals_match_every_csv_cell(tmp_path, source):
    raw = (Path(__file__).parent / "fixtures/fec/rows" / source["file"]).read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == source["capture"]["responseSha256"]
    mode = source["format"]
    reader = _publish(
        tmp_path,
        raw,
        capture=source["capture"],
        format=mode,
        delimiter="," if mode == "delimited" else None,
        quoting="csv" if mode == "delimited" else None,
    )
    rows = _records(reader)
    expected = list(csv.reader(io.StringIO(raw.decode(), newline="")))
    assert len(rows) == len(expected) == source["independent_csv_records"]
    bodies = 0
    for row, original in zip(rows, expected, strict=True):
        record = row["record"]
        source_ref = record["source"]
        fragment = raw[source_ref["byte_offset"] : source_ref["byte_offset"] + source_ref["byte_length"]]
        assert list(csv.reader(io.StringIO(fragment.decode(), newline=""))) == [original]
        if mode == "delimited" or record["kind"] == "header":
            assert record["fields"] == original
        else:
            actual = dict(record["fields"])
            for body in record["embedded_bodies"]:
                assert body["byte_offset"] == source_ref["byte_offset"]
                actual[str(body["field_index"])] = original[body["field_index"]]
                bodies += 1
            assert actual == {str(i): value for i, value in enumerate(original)}
    if mode == "fec":
        assert bodies == source["embedded_body_count"]
    assert b"".join(reader.iter_evidence(source["capture"]["responseSha256"])) == raw
