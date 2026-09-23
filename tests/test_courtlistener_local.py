"""Record-aligned pieces parsed by DuckDB, held to the reference decoder on the publisher's dialect.

Small ``piece_bytes`` make a small file split into many pieces, so every test crosses piece
boundaries. Where DuckDB is more lenient than the reference decoder, each piece's canary refuses;
one test pins that the canary covers only the opening of a piece.
"""

from __future__ import annotations

import bz2
import random
import threading
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("indexed_bzip2")

from spicy_docs.sources.courtlistener import local
from spicy_docs.sources.courtlistener.bulk import CourtListenerBulkReader
from spicy_docs.sources.courtlistener.csv import CourtListenerCsvError
from spicy_docs.sources.courtlistener.local import CourtListenerLocalDump


def _export(tmp_path: Path, body: bytes, name: str = "dump.csv.bz2") -> Path:
    path = tmp_path / name
    path.write_bytes(bz2.compress(body))
    return path


def _encode(value: str | None) -> str:
    """The publisher's FORCE_QUOTE * encoding: NULL unquoted and empty, backslash-escaped quotes."""
    return "" if value is None else '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rows(dump: CourtListenerLocalDump) -> list[tuple]:
    return [row for batch in dump.iter_batches() for row in zip(*(c.to_pylist() for c in batch.columns), strict=True)]


def _reference(path: Path, columns: list[str] | None = None) -> list[tuple]:
    records = CourtListenerBulkReader("dump", local_file=path, decompression_threads=1).iter_records()
    return [tuple(record[name] for name in (columns or list(record))) for record in records]


def _publisher_export(tmp_path: Path, records: int = 3000, seed: int = 20260922) -> Path:
    # A value can hold a newline, an escaped quote and digits in a row: never a record start.
    pieces = ['"', "\\", ",", "\n", "\r\n", '\n"12', "é", "\\N", "a,b,c\n", '<p id="x">', " ", "7"]
    rng = random.Random(seed)
    lines = ["id,text,maybe,note"]
    for number in range(records):
        cells = [str(number)] + [
            None
            if rng.random() < 0.15
            else ""
            if rng.random() < 0.15
            else "".join(rng.choices(pieces, k=rng.randint(1, 40)))
            for _ in range(3)
        ]
        lines.append(",".join(_encode(cell) for cell in cells))
    return _export(tmp_path, ("\n".join(lines) + "\n").encode())


def test_pieces_decode_exactly_as_the_reference_decoder(tmp_path):
    path = _publisher_export(tmp_path)
    dump = CourtListenerLocalDump(path, piece_bytes=4096, parse_workers=3, canary_bytes=512)
    assert _rows(dump) == _reference(path)
    assert dump.completed and dump.rows == 3000 and dump.pieces > 20
    assert 0 < dump.canary_rows < dump.rows
    assert dump.decompressed_bytes == len(bz2.decompress(path.read_bytes()))


def test_columns_are_selected_in_the_requested_order(tmp_path):
    path = _publisher_export(tmp_path, records=200)
    dump = CourtListenerLocalDump(path, columns=["note", "id"], piece_bytes=2048)
    assert _rows(dump) == _reference(path, ["note", "id"])


def test_a_record_longer_than_a_piece_stays_whole(tmp_path):
    body = "id,text\n" + "".join(
        ",".join(map(_encode, row)) + "\n" for row in [("1", "short"), ("2", 'long "line"\n' * 2000), ("3", None)]
    )
    path = _export(tmp_path, body.encode())
    dump = CourtListenerLocalDump(path, piece_bytes=1024)
    assert _rows(dump) == _reference(path)


@pytest.mark.parametrize(
    "record",
    [b'"secret', b'"secret\\', b'"secret"tail', b'"a""secret"', b'"\xff"', b'"secret","extra"'],
    ids=["unterminated", "unterminated-escape", "text-after-quote", "doubled-quote", "invalid-utf8", "extra-field"],
)
def test_malformed_records_are_refused_without_their_values(tmp_path, record):
    body = b"id\n" + b"".join(b'"%d"\n' % n for n in range(500)) + record + b"\n"
    path = _export(tmp_path, body)
    dump = CourtListenerLocalDump(path, piece_bytes=1024, canary_bytes=128)
    with pytest.raises(CourtListenerCsvError) as refused:
        _rows(dump)
    assert "secret" not in str(refused.value)
    assert not dump.completed


@pytest.mark.parametrize("record", [b'"9"secret"', b'"literal\\path"'], ids=["quote-in-field", "lone-backslash"])
def test_every_piece_is_checked_not_only_the_first(tmp_path, record):
    """DuckDB would misread these; they open a late piece, so only a per-piece canary sees them."""
    body = b"id\n" + b"".join(b'"%d"\n' % n for n in range(2000)) + record + b"\n" + b'"1"\n' * 10
    path = _export(tmp_path, body)
    with pytest.raises(CourtListenerCsvError, match="piece"):
        _rows(CourtListenerLocalDump(path, piece_bytes=1024, canary_bytes=2048))


def test_the_canary_checks_only_the_opening_of_each_piece(tmp_path):
    """Past a piece's canary, DuckDB's leniency is not re-checked: a lone backslash is dropped."""
    body = b"h\n" + b'"1"\n' * 400 + b'"literal\\path"\n'
    path = _export(tmp_path, body)
    rows = _rows(CourtListenerLocalDump(path, piece_bytes=1 << 20, canary_bytes=64))
    assert rows[-1] == ("literalpath",)
    assert _reference(path)[-1] == ("literal\\path",)


def test_an_export_without_record_starts_is_refused_before_a_piece_grows_unbounded(tmp_path, monkeypatch):
    """A first column that is not a numeric id leaves nothing to cut at; the piece may not grow forever."""
    monkeypatch.setattr(local, "MAX_RECORD_CHARACTERS", 4096)
    monkeypatch.setattr(local, "_READ_BYTES", 1024)
    body = b"name\n" + b'"row"\n' * 5000
    with pytest.raises(CourtListenerCsvError, match="not in the dialect"):
        _rows(CourtListenerLocalDump(_export(tmp_path, body), piece_bytes=1024))


@pytest.mark.parametrize(
    ("body", "message"),
    [(b"", "missing header"), (b',b\n"1","2"\n', "nonempty and unique"), (b'a,a\n"1","2"\n', "nonempty and unique")],
)
def test_bad_headers_are_refused(tmp_path, body, message):
    with pytest.raises(CourtListenerCsvError, match=message):
        _rows(CourtListenerLocalDump(_export(tmp_path, body)))


def test_files_bz2_would_refuse_are_refused(tmp_path):
    path = _publisher_export(tmp_path, records=50)
    data = path.read_bytes()
    with pytest.raises(ValueError, match="not in the dump.csv.bz2 header"):
        _rows(CourtListenerLocalDump(path, columns=["missing"]))
    for damaged, error in ((b"PK" + data, OSError), (data + b"JUNK", EOFError), (data[:-7], EOFError)):
        path.write_bytes(damaged)
        with pytest.raises(error):
            _rows(CourtListenerLocalDump(path))
    path.write_bytes(data)
    link = tmp_path / "link.csv.bz2"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular file"):
        _rows(CourtListenerLocalDump(link))


def test_stopping_early_releases_every_thread_and_removes_the_pieces(tmp_path):
    path = _publisher_export(tmp_path, records=3000)
    dump = CourtListenerLocalDump(path, piece_bytes=2048, parse_workers=2, work_dir=tmp_path)
    batches = dump.iter_batches()
    next(batches)
    batches.close()
    assert not dump.completed
    assert not [t for t in threading.enumerate() if t.name.startswith("courtlistener-local")]
    assert not list(tmp_path.glob("courtlistener-local-*"))


CASES = {
    "one": b'"1","a"\n',
    "value-ending-in-newline": b'"1","a\n"\n"2",\n',
    "newline-before-comma-and-crlf": b'"1","x\n","y"\n"22","\n"\r\n',
    "escaped-quote-after-newline": b'"1","a\n\\"12"\n"3",""\n',
    "no-final-newline": b'"1",\n"2","b"',
}


@pytest.mark.parametrize("body", CASES.values(), ids=CASES.keys())
def test_the_dialect_count_of_records_matches_the_reference(body):
    import io

    from spicy_docs.sources.courtlistener.csv import iter_postgres_csv

    assert local._record_count(body) == len(list(iter_postgres_csv(io.BytesIO(body))))


def test_a_piece_spanning_read_buffers_is_scanned_sequentially(tmp_path, monkeypatch):
    """DuckDB's parallel scan guesses record starts at buffer boundaries; decoy lines inside quotes fool it."""
    # DuckDB's buffer must hold four lines; keep that relation at a size a test can cross.
    monkeypatch.setattr(local, "MAX_RECORD_CHARACTERS", 256 << 10)
    monkeypatch.setattr(local, "_BUFFER_BYTES", 4 * (256 << 10))
    decoy = "a,b,c\n" * 3000 + '<p id="x">text</p>\n'
    body = "id,body,tail\n" + "".join(f"{_encode(str(n))},{_encode(decoy)},{_encode('t')}\n" for n in range(1200))
    path = _export(tmp_path, body.encode())
    dump = CourtListenerLocalDump(path, piece_bytes=64 << 20)
    assert _rows(dump) == _reference(path)
    assert dump.pieces == 1
