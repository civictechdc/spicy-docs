"""Decode a retained CourtListener export in record-aligned pieces, parsed by DuckDB in parallel.

The streaming reader decodes one record after another; on the 54.6 GB ``opinions`` export that is
about an hour even with parallel decompression. The publisher's dialect makes the text splittable:
with ``FORCE_QUOTE *`` every value is quoted and every quote inside a value is escaped, so a newline
followed by an unescaped quote and a digit can only begin a record whose first field is its numeric
``id`` (a value ending in a newline is closed by a quote followed by a comma or newline, never a
digit). On the first 6.0 GB of that export the 134,310 such points were exactly its records.

So one thread decompresses on several cores (indexed_bzip2), cuts the text at those points into
pieces of about ``piece_bytes`` and writes each, under the header line, to a temporary file; a pool
parses the pieces with DuckDB, one sequential scan each, and batches come back in file order. On the
same 6.0 GB: 2,277 MB/s for DuckDB over 23 pieces against 137 MB/s for the reference decoder, with
identical values, NULLs and empty strings; decompression, not parsing, is then the limit.

Each piece is a seekable file because DuckDB keeps every buffer it reads from a pipe (a pass through
one ran out of memory 160 GB into the opinions export), and each is scanned sequentially because its
parallel reader guesses where records start and refused a valid one of that export at a buffer
boundary. DuckDB is also more lenient than the reference decoder about text this export cannot
contain: inside quotes it drops a backslash before any character but a quote or backslash, and it
accepts a quote in an unquoted field. So the opening ``canary_bytes`` of every piece is decoded with
``iter_postgres_csv`` too and must match DuckDB's rows; that samples the dialect through the whole
file, not every record. Scanning sequentially, DuckDB also drops an unterminated last record without
error, so every piece's row count must equal the dialect's count of record starts in it.
"""

from __future__ import annotations

import io
import queue
import re
import shutil
import tempfile
import threading
from collections import deque
from collections.abc import Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from .bulk import check_whole_bzip2_file
from .csv import MAX_COLUMNS, MAX_RECORD_CHARACTERS, CourtListenerCsvError, iter_postgres_csv

if TYPE_CHECKING:
    import pyarrow as pa

#: A record start: the newline, an unescaped quote and the first digit of the record's ``id``.
_RECORD_START = re.compile(rb'\n"\d')
#: Text read from the decompressor per step while looking for the next cut.
_READ_BYTES = 16 << 20
#: DuckDB's read buffer. Its documentation requires room for four lines (default: sixteen, 1 GiB at
#: the reference decoder's 64 Mi-character bound); four keep that guarantee at a quarter the memory.
_BUFFER_BYTES = 4 * MAX_RECORD_CHARACTERS
#: DuckDB's refusals of the CSV content itself; their messages quote the offending source line.
_DUCKDB_CSV_REFUSALS = ("Invalid Input Error", "Conversion Error")
_DUCKDB_LINE = re.compile(r"CSV Error on Line: (\d+)")
_DONE = object()


def _record_count(body: bytes) -> int:
    """Records in a record-aligned piece under the publisher's dialect.

    Every record after the first begins with a newline, an unescaped quote and a digit. Any other
    newline-quote closes a value that ends in a newline, so a comma, newline or carriage return
    follows it. Four byte counts give the number without a pass through a parser.
    """
    if not body:
        return 0
    starts = body.count(b'\n"') - body.count(b'\n",') - body.count(b'\n"\n') - body.count(b'\n"\r')
    return 1 + starts - body.endswith(b'\n"')


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


class CourtListenerLocalDump:
    """Arrow batches of string columns from one retained ``.csv.bz2`` export, in file order.

    Values match ``CourtListenerBulkReader``: an unquoted empty field is NULL and ``""`` stays an
    empty string. ``columns`` selects source columns in the order given (default: the header's).
    At most ``parse_workers`` pieces plus one being cut are on disk at once, in ``work_dir``
    (default: the system temporary directory). ``completed`` is set only once the whole file has
    been read, cut, parsed and checked.
    """

    def __init__(
        self,
        local_file: Path,
        *,
        columns: Sequence[str] | None = None,
        piece_bytes: int = 256 << 20,
        parse_workers: int = 8,
        decompression_threads: int = 0,
        canary_bytes: int = 1 << 20,
        work_dir: Path | None = None,
    ) -> None:
        if piece_bytes <= 0 or parse_workers <= 0 or canary_bytes <= 0 or decompression_threads < 0:
            raise ValueError("piece_bytes, parse_workers and canary_bytes must be positive")
        self.local_file = Path(local_file)
        self.columns = tuple(columns) if columns is not None else None
        self.piece_bytes = piece_bytes
        self.parse_workers = parse_workers
        self.decompression_threads = decompression_threads
        self.canary_bytes = canary_bytes
        self.work_dir = work_dir
        self.header: tuple[str, ...] = ()
        self.rows = 0
        self.pieces = 0
        self.canary_rows = 0
        self.decompressed_bytes = 0
        self.completed = False

    def _read_header(self, source) -> tuple[bytes, bytes]:
        """Take the header line off the stream, check it as the reference decoder would, return it and the rest."""
        start = source.read(1 << 20)
        end = start.find(b"\n")
        if end < 0:
            raise CourtListenerCsvError("CourtListener CSV record 1: missing header")
        line = start[:end].rstrip(b"\r")
        header = next(iter_postgres_csv(io.BytesIO(line)), None) or []
        if not header or any(name is None or name == "" for name in header) or len(set(header)) != len(header):
            raise CourtListenerCsvError("CourtListener CSV record 1: header names must be nonempty and unique")
        if len(header) > MAX_COLUMNS:
            raise CourtListenerCsvError(f"CourtListener CSV record 1: exceeds {MAX_COLUMNS} columns")
        self.header = tuple(str(name) for name in header)
        if missing := [name for name in self.columns or () if name not in self.header]:
            raise ValueError(f"columns not in the {self.local_file.name} header: {missing}")
        self.decompressed_bytes += len(start)
        return start[: end + 1], start[end + 1 :]

    def _cut(self, workspace: Path, pieces: queue.Queue, stop: threading.Event) -> None:
        """Decompress the file, write record-aligned pieces under the header line, and queue their paths."""
        import indexed_bzip2

        try:
            with indexed_bzip2.open(str(self.local_file), parallelization=self.decompression_threads) as source:
                header_line, text = self._read_header(source)
                limit = self.piece_bytes + MAX_RECORD_CHARACTERS + _READ_BYTES
                number, ended = 0, False
                while not stop.is_set():
                    cut = None
                    if len(text) >= self.piece_bytes:
                        found = _RECORD_START.search(text, self.piece_bytes - 1)
                        cut = found.start() + 1 if found else None
                    if cut is None and ended:
                        cut = len(text)
                    if cut is None:
                        if len(text) > limit:
                            raise CourtListenerCsvError(
                                "CourtListener CSV: no record start within a piece and the record limit; "
                                "the export is not in the dialect this reader splits"
                            )
                        # Read up to the next cut in blocks and join once: appending each block to
                        # one buffer would copy the whole piece per block.
                        blocks, size = [text], len(text)
                        target = max(self.piece_bytes, size + _READ_BYTES)
                        while size < target:
                            block = source.read(_READ_BYTES)
                            if not block:
                                ended = True
                                break
                            self.decompressed_bytes += len(block)
                            blocks.append(block)
                            size += len(block)
                        text = b"".join(blocks)
                        continue
                    if cut:
                        body = memoryview(text)[:cut]
                        path = workspace / f"piece-{number:06d}.csv"
                        with path.open("wb") as sink:
                            sink.write(header_line)
                            sink.write(body)
                        pieces.put((path, _record_count(text[:cut])))
                        number += 1
                    text = text[cut:]
                    if ended and not text:
                        break
            pieces.put(_DONE)
        except BaseException as exc:  # noqa: BLE001 - reported on the consumer's thread
            pieces.put(exc)

    def _query(self, path: Path) -> str:
        declared = "{" + ", ".join(f"{_literal(name)}: 'VARCHAR'" for name in self.header) + "}"
        selected = ", ".join(_identifier(name) for name in self.columns or self.header)
        # The dialect is stated, never sniffed; each piece is scanned sequentially (see module notes).
        return (
            f"SELECT {selected} FROM read_csv({_literal(str(path))}, header = true, auto_detect = false, "
            f"columns = {declared}, delim = ',', quote = '\"', escape = '\\', allow_quoted_nulls = false, "
            f"strict_mode = true, parallel = false, max_line_size = {MAX_RECORD_CHARACTERS}, "
            f"buffer_size = {_BUFFER_BYTES})"
        )

    def _parse(self, path: Path, expected_rows: int, number: int) -> tuple[pa.Table, int]:
        """Parse one piece with DuckDB; hold its record count to the dialect and its opening to the reference."""
        import duckdb

        try:
            with duckdb.connect() as connection:
                connection.execute("SET threads = 1")
                try:
                    table = connection.execute(self._query(path)).to_arrow_table()
                except duckdb.Error as exc:
                    message = str(exc)
                    if not message.startswith(_DUCKDB_CSV_REFUSALS):
                        raise
                    line = _DUCKDB_LINE.search(message)
                    where = f"piece {number} line {line.group(1)}" if line else f"piece {number}"
                    kind = message.split(":", 1)[0]
                    # DuckDB's message quotes the offending source line; keep values out of the error.
                    raise CourtListenerCsvError(f"CourtListener CSV {where}: refused by DuckDB ({kind})") from None
            if table.num_rows != expected_rows:
                # DuckDB drops an unterminated last record without error when scanning sequentially.
                raise CourtListenerCsvError(
                    f"CourtListener CSV piece {number}: DuckDB read {table.num_rows} records "
                    f"where the dialect has {expected_rows}"
                )
            with path.open("rb") as handle:
                prefix = handle.read(self.canary_bytes)
            truncated = len(prefix) == self.canary_bytes
            records = iter_postgres_csv(io.BytesIO(prefix), is_truncated=lambda: truncated)
            next(records)  # the header line this reader wrote
            positions = [self.header.index(name) for name in self.columns or self.header]
            expected = []
            for offset, record in enumerate(records):
                if len(record) != len(self.header):
                    raise CourtListenerCsvError(
                        f"CourtListener CSV piece {number} record {offset + 2}: "
                        f"expected {len(self.header)} columns, got {len(record)}"
                    )
                expected.append(tuple(record[i] for i in positions))
            sample = table.slice(0, len(expected))
            found = list(zip(*(column.to_pylist() for column in sample.columns), strict=True)) if expected else []
            for offset, (want, got) in enumerate(zip(expected, found + [None] * (len(expected) - len(found)))):
                if want != got:
                    raise CourtListenerCsvError(
                        f"CourtListener CSV piece {number} record {offset + 2}: DuckDB and the reference decoder disagree"
                    )
            if not truncated and len(expected) != table.num_rows:
                raise CourtListenerCsvError(
                    f"CourtListener CSV piece {number}: DuckDB read {table.num_rows} records, "
                    f"the reference decoder {len(expected)}"
                )
            checked = len(expected)
            return table, checked
        finally:
            path.unlink(missing_ok=True)

    def iter_batches(self) -> Iterator[pa.RecordBatch]:
        """Yield the selected columns in file order, refusing at the first piece that fails a check."""
        if self.local_file.is_symlink() or not self.local_file.is_file():
            raise ValueError("a retained CourtListener export must be a regular file")
        check_whole_bzip2_file(self.local_file)
        self.completed = False
        workspace = Path(tempfile.mkdtemp(prefix="courtlistener-local-", dir=self.work_dir))
        pieces: queue.Queue = queue.Queue(maxsize=self.parse_workers)
        stop = threading.Event()
        cutter = threading.Thread(
            target=self._cut, args=(workspace, pieces, stop), name="courtlistener-local-cut", daemon=True
        )
        pool = ThreadPoolExecutor(self.parse_workers, thread_name_prefix="courtlistener-local-parse")
        running: deque[Future] = deque()
        cutter.start()
        try:
            finished = False
            while not finished or running:
                while not finished and len(running) < self.parse_workers:
                    item = pieces.get()
                    if item is _DONE:
                        finished = True
                    elif isinstance(item, BaseException):
                        raise item
                    else:
                        path, expected_rows = item
                        running.append(pool.submit(self._parse, path, expected_rows, self.pieces))
                        self.pieces += 1
                if running:
                    table, checked = running.popleft().result()
                    self.canary_rows += checked
                    self.rows += table.num_rows
                    yield from table.to_batches()
            cutter.join()
            self.completed = True
        finally:
            stop.set()
            for future in running:
                future.cancel()
            # A cutter blocked on a full queue needs room to see the stop flag.
            while cutter.is_alive():
                try:
                    item = pieces.get(timeout=0.05)
                except queue.Empty:
                    continue
                if isinstance(item, tuple):
                    item[0].unlink(missing_ok=True)
            pool.shutdown(wait=True, cancel_futures=True)
            shutil.rmtree(workspace, ignore_errors=True)
