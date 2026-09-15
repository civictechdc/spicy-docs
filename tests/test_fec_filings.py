"""Literal filing syntax and source coordinates; fixtures are not valid reports."""

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest
from rulespec_artifacts import ArtifactVerificationError, LocalBlobWriter

from spicy_docs.sources.fec.filings import _Lines, filing_body, filing_records


def captured(tmp_path, raw):
    blob = LocalBlobWriter(tmp_path).put([raw], max_bytes=len(raw))
    return {"store": tmp_path, "sha256": blob.digest}


def test_literal_fields_unknown_forms_and_separate_text_bodies(tmp_path):
    raw = (
        b"HDR\x1cFEC\x1c8.5\x1cCaseSensitive\x1c1\x1c\x1c\n"
        b'F1N\x1cC00000001\x1c001\x1c0.1000\x1c\x1c"Quoted"\x1cEXTRA\n'
        b"NEWTYPE\x1cDo not drop me\n"
        b"TEXT\x1cC00000001\x1ctx\x1cparent\x1cSC/10\x1cExact  text \x1cunknown-extra\n"
        b"[BEGINTEXT]\r\nCase remains\r\n\r\n More text \n[ENDTEXT]\n"
        b"UNKNOWN\x1cstill here\n"
    )
    kwargs = captured(tmp_path, raw)
    rows = list(filing_records(**kwargs))
    assert rows[0]["fields"][3] == "CaseSensitive"
    assert rows[1]["fields"] == {
        "0": "F1N",
        "1": "C00000001",
        "2": "001",
        "3": "0.1000",
        "4": "",
        "5": '"Quoted"',
        "6": "EXTRA",
    }
    assert rows[2]["record_type"] == "NEWTYPE"
    assert rows[3]["field_count"] == 7
    assert "5" not in rows[3]["fields"]
    assert rows[3]["fields"]["6"] == "unknown-extra"
    assert filing_body(store=tmp_path, body=rows[3]["embedded_bodies"][0]) == "Exact  text "
    body = rows[4]["embedded_bodies"][0]
    assert filing_body(store=tmp_path, body=body) == "Case remains\r\n\r\n More text \n"
    assert raw[body["byte_offset"] : body["byte_offset"] + body["byte_length"]] == b"Case remains\r\n\r\n More text \n"
    assert rows[5]["record_type"] == "UNKNOWN"
    for row in [rows[0], rows[1], rows[2], rows[3], rows[5]]:
        ref = row["source"]
        assert raw[ref["byte_offset"] : ref["byte_offset"] + ref["byte_length"]].endswith(b"\n")


def test_csv_multiline_and_legacy_header_keep_case_and_byte_coordinates(tmp_path):
    raw = b'/* Header\nFEC_Ver_# = 2.02\nSoft_Name = MiXeD\n/* End Header\nF3A,"Mixed, Name","line one\nline two",0.00\nNEXT,"a ""quote""",\n'
    rows = list(filing_records(**captured(tmp_path, raw)))
    assert rows[0]["format_version"] == "2.02"
    assert "Soft_Name = MiXeD" in rows[0]["fields"]
    assert rows[1]["fields"] == {"0": "F3A", "1": "Mixed, Name", "2": "line one\nline two", "3": "0.00"}
    assert rows[2]["fields"] == {"0": "NEXT", "1": 'a "quote"', "2": ""}
    ref = rows[1]["source"]
    assert (
        raw[ref["byte_offset"] : ref["byte_offset"] + ref["byte_length"]]
        == b'F3A,"Mixed, Name","line one\nline two",0.00\n'
    )


@pytest.mark.parametrize("text", ["", 'Exact, "quoted"\r\nsecond line\n caf\u00e9 '])
@pytest.mark.parametrize("version", ["5.0", "5.1", "5.2", "5.3"])
def test_qualified_csv_text_lifts_only_narrative_and_resolves_exactly(tmp_path, text, version):
    output = io.StringIO(newline="")
    expected = ["TEXT", "SB29", "parent-id", text, "", "unknown-extra"]
    csv.writer(output).writerow(expected)
    record = output.getvalue().encode()
    header = f"HDR,FEC,{version},Example\r\n".encode()
    raw = header + record + b"OTHER,untouched\r\n"
    rows = list(filing_records(**captured(tmp_path, raw), max_record_bytes=len(record)))
    row = rows[1]
    assert row["field_count"] == 6
    assert row["fields"] == {"0": "TEXT", "1": "SB29", "2": "parent-id", "4": "", "5": "unknown-extra"}
    (body,) = row["embedded_bodies"]
    assert body == {**row["source"], "field_index": 3, "delimiter": ","}
    assert body["byte_offset"] == len(header) and body["byte_length"] == len(record)
    assert raw[body["byte_offset"] : body["byte_offset"] + body["byte_length"]] == record
    assert filing_body(store=tmp_path, body=body, max_bytes=len(record)) == text
    assert rows[2]["fields"] == {"0": "OTHER", "1": "untouched"}
    with pytest.raises(ValueError, match="byte bound"):
        filing_body(store=tmp_path, body=body, max_bytes=len(record) - 1)
    with pytest.raises(ValueError, match="byte bound"):
        list(filing_records(**captured(tmp_path, raw), max_record_bytes=len(record) - 1))


@pytest.mark.parametrize("version", ["3", "3.00", "5.000", "5.20", "5.30", "6.1", "unqualified"])
def test_unqualified_csv_text_remains_positional(tmp_path, version):
    raw = f"HDR,FEC,{version}\nTEXT,SB29,parent,Narrative,,EXTRA\n".encode()
    row = list(filing_records(**captured(tmp_path, raw)))[1]
    assert row["embedded_bodies"] == []
    assert row["fields"] == {"0": "TEXT", "1": "SB29", "2": "parent", "3": "Narrative", "4": "", "5": "EXTRA"}


@pytest.mark.parametrize(
    "fragment",
    json.loads((Path(__file__).parent / "fixtures/fec/historical-text-fragments.json").read_text())["fragments"],
    ids=lambda fragment: fragment["declared_version"],
)
def test_genuine_historical_text_fragments_separate_and_preserve_body(tmp_path, fragment):
    # Complete source pins and original offsets live with the exact fragments.
    # The fixture concatenates its header and one record, not a complete report.
    header, record = fragment["header"].encode(), fragment["record"].encode()
    rows = list(filing_records(**captured(tmp_path, header + record)))
    assert len(rows) == 2
    assert rows[0]["format_version"] == fragment["declared_version"]
    row = rows[1]
    assert row["field_count"] == 4 and row["fields"] == fragment["metadata_fields"]
    (body,) = row["embedded_bodies"]
    assert body["field_index"] == 3 and body["delimiter"] == ","
    assert body["byte_offset"] == len(header)
    assert body["byte_length"] == len(record) == fragment["record_bytes"]
    text = filing_body(store=tmp_path, body=body)
    assert hashlib.sha256(text.encode()).hexdigest() == fragment["body_sha256"]


@pytest.mark.parametrize("record", [b"TEXT,form,parent\n", b"text,form,parent,not-a-TEXT-record\n"])
def test_short_or_other_csv_record_does_not_invent_a_body(tmp_path, record):
    row = list(filing_records(**captured(tmp_path, b"HDR,FEC,5.3\n" + record)))[1]
    assert row["embedded_bodies"] == []
    assert len(row["fields"]) == row["field_count"]


@pytest.mark.parametrize("raw", [b"TEXT,form,parent,body\nOTHER,row\n", b""])
def test_csv_body_reference_requires_exactly_one_record(tmp_path, raw):
    kwargs = captured(tmp_path, raw or b"\n")
    body = {
        "sha256": kwargs["sha256"],
        "byte_offset": 0,
        "byte_length": len(raw),
        "encoding": "utf-8",
        "field_index": 3,
        "delimiter": ",",
    }
    with pytest.raises(ValueError, match="exactly one"):
        filing_body(store=tmp_path, body=body)


def test_csv_body_malformed_row_and_missing_field_refuse(tmp_path):
    for raw, error in [(b'TEXT,form,parent,"unterminated\n', csv.Error), (b"TEXT,form,parent\n", ValueError)]:
        kwargs = captured(tmp_path, raw)
        body = {
            "sha256": kwargs["sha256"],
            "byte_offset": 0,
            "byte_length": len(raw),
            "encoding": "utf-8",
            "field_index": 3,
            "delimiter": ",",
        }
        with pytest.raises(error):
            filing_body(store=tmp_path, body=body)


def test_explicit_latin1_never_restarts_prior_records(tmp_path):
    raw = b"HDR\x1cP3.3\x1cExample\nF13N\x1cC00000001\nF132\x1cCAF\xc9\n"
    kwargs = captured(tmp_path, raw)
    stream = filing_records(**kwargs)
    assert next(stream)["format_version"] == "P3.3"
    assert next(stream)["record_type"] == "F13N"
    with pytest.raises(UnicodeDecodeError):
        next(stream)
    rows = list(filing_records(**kwargs, encoding="latin-1"))
    assert [r.get("record_type") for r in rows] == [None, "F13N", "F132"]
    assert rows[-1]["fields"]["1"] == "CAFÉ"


@pytest.mark.parametrize("delimiter,version,body_index", [("\x1c", "8.5", 5), (",", "5.2", 3)])
def test_explicit_cp1252_preserves_source_ranges_and_readable_bodies(tmp_path, delimiter, version, body_index):
    # Retained FEC-1998705/1998706 use 0x93/0x94 around Agreement; choosing
    # cp1252 is caller interpretation, not a publisher encoding declaration.
    header = f"HDR{delimiter}FEC{delimiter}{version}\n".encode()
    fields = ["TEXT", "parent", "source-id", "back", "schedule"][:body_index] + ["“Agreement”, café", "EXTRA"]
    output = io.StringIO(newline="")
    csv.writer(output).writerow(fields)
    line = (delimiter.join(fields) + "\r\n" if delimiter == "\x1c" else output.getvalue()).encode("cp1252")
    raw = header + line + b"[BEGINTEXT]\n\x93Exact\x94\r\n[ENDTEXT]\n"
    kwargs = captured(tmp_path, raw)
    default = filing_records(**kwargs)
    assert next(default)["kind"] == "header"
    with pytest.raises(UnicodeDecodeError):
        next(default)
    rows = list(filing_records(**kwargs, encoding="cp1252"))
    assert len(rows) == 3
    assert rows[1]["fields"][str(body_index + 1)] == "EXTRA"
    body = rows[1]["embedded_bodies"][0]
    assert body["encoding"] == "cp1252"
    assert body["byte_offset"] == len(header) and body["byte_length"] == len(line)
    assert filing_body(store=tmp_path, body=body) == "“Agreement”, café"
    bracketed = rows[2]["embedded_bodies"][0]
    text = filing_body(store=tmp_path, body=bracketed)
    assert text == "“Exact”\r\n"
    assert text.encode("cp1252") == raw[bracketed["byte_offset"] : bracketed["byte_offset"] + bracketed["byte_length"]]
    # Latin-1 is still an explicit byte-preserving choice, with different text.
    latin_body = list(filing_records(**kwargs, encoding="latin-1"))[2]["embedded_bodies"][0]
    assert filing_body(store=tmp_path, body=latin_body) == "\x93Exact\x94\r\n"


def test_selected_encoding_never_replaces_undefined_bytes_or_guesses(tmp_path):
    kwargs = captured(tmp_path, b"HDR\x1cFEC\x1c8.5\nUNKNOWN\x1c\x81\n")
    stream = filing_records(**kwargs, encoding="cp1252")
    assert next(stream)["kind"] == "header"
    with pytest.raises(UnicodeDecodeError):
        next(stream)
    assert list(filing_records(**kwargs, encoding="latin-1"))[1]["fields"]["1"] == "\x81"
    with pytest.raises(ValueError, match="select"):
        next(filing_records(**kwargs, encoding="utf-16"))


def test_record_bound_at_limit_and_csv_total_across_lines(tmp_path):
    header = b"HDR\x1cFEC\x1c8.5\n"
    kwargs = captured(tmp_path, header + b"A\x1c" + b"x" * 61 + b"\n")
    assert list(filing_records(**kwargs, max_record_bytes=64))[-1]["fields"]["1"] == "x" * 61
    with pytest.raises(ValueError, match="byte bound"):
        list(filing_records(**kwargs, max_record_bytes=63))
    csv_input = captured(tmp_path, b'HDR,FEC,3.00\nA,"' + b"x" * 30 + b"\n" + b"x" * 30 + b'"\n')
    with pytest.raises(ValueError, match="byte bound"):
        list(filing_records(**csv_input, max_record_bytes=64))


def test_lines_request_only_the_remaining_record_budget():
    class Observed(io.BytesIO):
        def __init__(self, raw):
            super().__init__(raw)
            self.sizes = []

        def readline(self, size=-1):
            self.sizes.append(size)
            return super().readline(size)

    stream = Observed(b"first\nsecond\n" + b"x" * 1000)
    lines = _Lines(stream, "utf-8", 13)
    assert next(lines) == "first\n"
    assert next(lines) == "second\n"
    with pytest.raises(ValueError, match="byte bound"):
        next(lines)
    assert stream.sizes == [14, 8, 1]
    assert stream.tell() == 14


@pytest.mark.parametrize("tail", [b"[BEGINTEXT]\nmissing close\n", b"[END TEXT]\n"])
def test_broken_text_blocks_fail_without_invented_completed_body(tmp_path, tail):
    stream = filing_records(**captured(tmp_path, b"HDR\x1cFEC\x1c8.5\n" + tail))
    assert next(stream)["kind"] == "header"
    with pytest.raises(ValueError, match="text block"):
        next(stream)


def test_bracketed_body_can_exceed_record_bound_without_accumulating(tmp_path):
    raw = b"HDR\x1cFEC\x1c8.5\n[BEGIN TEXT]\n" + b"body line\n" * 100 + b"[END TEXT]\n"
    rows = list(filing_records(**captured(tmp_path, raw), max_record_bytes=20))
    body = rows[1]["embedded_bodies"][0]
    assert body["byte_length"] == 1000
    with pytest.raises(ValueError, match="byte bound"):
        filing_body(store=tmp_path, body=body, max_bytes=999)
    assert filing_body(store=tmp_path, body=body, max_bytes=1000) == "body line\n" * 100


@pytest.mark.parametrize("raw", [b"", b"not a filing\n", b"/* Header\nFEC_Ver_# = 2.02\n"])
def test_unrecognized_and_unterminated_headers_refuse(tmp_path, raw):
    # The writer does not accept an empty object; use a valid source blob whose
    # selected bytes are whitespace for the empty-header case.
    with pytest.raises((ValueError, StopIteration)):
        list(filing_records(**captured(tmp_path, raw or b"\n")))


def test_original_digest_is_checked_before_rows_are_emitted(tmp_path):
    kwargs = captured(tmp_path, b"HDR\x1cFEC\x1c8.5\n")
    path = tmp_path / "sha256" / kwargs["sha256"].removeprefix("sha256:")
    path.write_bytes(b"changed source bytes")
    with pytest.raises(ArtifactVerificationError, match="invalid.member-digest"):
        next(filing_records(**kwargs))
    assert kwargs["sha256"] != "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_body_coordinates_cannot_escape_retained_bytes(tmp_path):
    kwargs = captured(tmp_path, b"HDR\x1cFEC\x1c8.5\n")
    body = {"sha256": kwargs["sha256"], "encoding": "utf-8", "byte_offset": 999, "byte_length": 0}
    with pytest.raises(ValueError, match="beyond"):
        filing_body(store=tmp_path, body=body)
