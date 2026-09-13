"""Known-answer cases for the publisher's explicit PostgreSQL CSV dialect.

Source: https://github.com/freelawproject/courtlistener/blob/main/scripts/make_bulk_data.sh
It selects ESCAPE '\\', FORCE_QUOTE *, UTF-8, and a header. PostgreSQL's CSV
NULL is an unquoted empty field, not the text-format marker '\\N'.
"""

from __future__ import annotations

import io

import pytest

from spicy_docs.sources import courtlistener_csv
from spicy_docs.sources.courtlistener_csv import CourtListenerCsvError, iter_postgres_csv


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 65536])
def test_native_values_survive_every_kind_of_chunk_boundary(monkeypatch, chunk_size):
    monkeypatch.setattr(courtlistener_csv, "_TEXT_CHUNK", chunk_size)
    body = (
        "id,empty,missing,text,marker\r\n"
        '"1","",,"café\\\\path \\"quoted\\"\r\nsecond line",\\N\r\n'
        '"2"," ",,"literal\\path","\\N"\n'
    ).encode()
    assert list(iter_postgres_csv(io.BytesIO(body))) == [
        ["id", "empty", "missing", "text", "marker"],
        ["1", "", None, 'café\\path "quoted"\r\nsecond line', "\\N"],
        ["2", " ", None, "literal\\path", "\\N"],
    ]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"", []),
        (b"\n", [[None]]),
        (b'""', [[""]]),
        (b",", [[None, None]]),
        (b"value,", [["value", None]]),
        (b"value,\n", [["value", None]]),
        (b"a\rb\rc\r", [["a"], ["b"], ["c"]]),
    ],
)
def test_record_endings_and_empty_fields(body, expected):
    assert list(iter_postgres_csv(io.BytesIO(body))) == expected


@pytest.mark.parametrize("body", [b'"secret', b'"secret\\', b'"secret"tail', b'secret"', b'"a""b"'])
def test_malformed_quotes_fail_without_dumping_source_values(body):
    with pytest.raises(CourtListenerCsvError, match="CSV record 2") as exc:
        list(iter_postgres_csv(io.BytesIO(b"header\n" + body)))
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("body", [b"header\n\xff", b"header\n\xc3"])
def test_invalid_utf8_is_not_replaced(body):
    with pytest.raises(CourtListenerCsvError, match="record 2: invalid UTF-8"):
        list(iter_postgres_csv(io.BytesIO(body)))


@pytest.mark.parametrize("suffix", [b'"unfinished', b"unfinished", b"partial\xc3", b"last,"])
def test_intentional_cutoff_discards_only_the_unfinished_record(suffix):
    assert list(iter_postgres_csv(io.BytesIO(b"header\ncomplete\n" + suffix), is_truncated=lambda: True)) == [
        ["header"],
        ["complete"],
    ]


def test_record_character_bound_includes_csv_syntax_and_embedded_newlines():
    body = b'"ab\nc",x\r\n'
    assert list(iter_postgres_csv(io.BytesIO(body), max_record_characters=8)) == [["ab\nc", "x"]]
    with pytest.raises(CourtListenerCsvError, match="record 1: exceeds 7 characters"):
        list(iter_postgres_csv(io.BytesIO(body), max_record_characters=7))


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_record_bounds_are_refused(limit):
    with pytest.raises(ValueError, match="positive integer"):
        list(iter_postgres_csv(io.BytesIO(b"a"), max_record_characters=limit))


def test_column_count_is_bounded_even_for_empty_fields():
    assert len(next(iter_postgres_csv(io.BytesIO(b"," * 1023)))) == 1024
    with pytest.raises(CourtListenerCsvError, match="exceeds 1024 columns"):
        list(iter_postgres_csv(io.BytesIO(b"," * 1024)))
