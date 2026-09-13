"""Offline positional filing records, separate from financial field mappings."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from pathlib import Path

from rulespec_artifacts import LocalBlobSource

BEGIN_TEXT = {"[BEGINTEXT]", "[BEGIN TEXT]"}
END_TEXT = {"[ENDTEXT]", "[END TEXT]"}
# Publisher "e-filing headers all versions", TEXT rows 11–14:
# v5.0–5.3 TEXT4000 is field 4 (zero-based 3). Other CSV versions stay positional.
CSV_TEXT_FIELDS = dict.fromkeys(("5.0", "5.1", "5.2", "5.3"), 3)


class _Lines:
    def __init__(self, stream, encoding: str, limit: int):
        self.stream, self.encoding, self.limit = stream, encoding, limit
        self.start = self.end = 0

    def __iter__(self):
        return self

    def __next__(self) -> str:
        raw = self.stream.readline(self.limit - (self.end - self.start) + 1)
        if not raw:
            raise StopIteration
        self.end += len(raw)
        if self.end - self.start > self.limit:
            raise ValueError("FEC record exceeds its byte bound")
        return raw.decode(self.encoding)


def filing_records(
    *, store: Path, sha256: str, encoding: str = "utf-8", max_record_bytes: int = 1024**2
) -> Iterator[dict]:
    """Read verified originals with source byte ranges and literal positional fields.

    ASCII-FS values retain quotes; CSV values follow Python's CSV syntax. No
    financial names, types, amendments or unknown record types are inferred.
    Select a whole-file encoding explicitly; decoding never restarts the stream.
    Memory is bounded by one record. Bracketed free text is counted, not joined.
    Only natural exhaustion establishes a completed parse of the selected file.
    """
    if type(max_record_bytes) is not int or max_record_bytes <= 0:
        raise ValueError("max_record_bytes must be a positive integer")
    if encoding not in {"utf-8", "latin-1", "cp1252"}:
        raise ValueError("select utf-8, latin-1 or cp1252 for the complete filing")
    with LocalBlobSource(store).open(sha256) as stream:
        lines = _Lines(stream, encoding, max_record_bytes)

        def reference(start: int, end: int) -> dict:
            return {"sha256": sha256, "byte_offset": start, "byte_length": end - start, "encoding": encoding}

        first = next(lines, "")
        if first.startswith("/*"):
            header = [first.rstrip("\r\n")]
            for line in lines:
                header.append(line.rstrip("\r\n"))
                if line.startswith("/*"):
                    break
            else:
                raise ValueError("FEC legacy header is unterminated")
            versions = [line.partition("=")[2].strip() for line in header if line.lower().startswith("fec_ver_#")]
            if len(versions) != 1 or not versions[0]:
                raise ValueError("FEC legacy header omitted a unique version")
            version, delimiter = versions[0], ","
        else:
            delimiter = "\x1c" if "\x1c" in first else ","
            header = first.rstrip("\r\n").split(delimiter) if delimiter == "\x1c" else next(csv.reader([first]))
            if len(header) < 3 or header[0] != "HDR":
                raise ValueError("FEC original omitted its filing header")
            version = header[2] if header[1] == "FEC" else header[1]
            if not version:
                raise ValueError("FEC header omitted its version")
        yield {"kind": "header", "format_version": version, "fields": header, "source": reference(0, lines.end)}
        while True:
            lines.start = lines.end
            line = next(lines, None)
            if line is None:
                return
            if line.strip().upper() in BEGIN_TEXT:
                body_start = lines.end
                while True:
                    lines.start = lines.end
                    line = next(lines, None)
                    if line is None:
                        raise ValueError("FEC text block is unterminated")
                    if line.strip().upper() in END_TEXT:
                        yield {"kind": "text", "embedded_bodies": [reference(body_start, lines.start)]}
                        break
                continue
            if line.strip().upper() in END_TEXT:
                raise ValueError("FEC text block has no opening marker")
            if delimiter == "\x1c":
                fields = line.rstrip("\r\n").split(delimiter)
            else:
                # The shared CSV reader consumes quoted multiline records from
                # the same byte-counted iterator, under one total record bound.
                def csv_lines(initial=line):
                    yield initial
                    yield from lines

                fields = next(csv.reader(csv_lines(), strict=True))
            row_source = reference(lines.start, lines.end)
            body_index = 5 if delimiter == "\x1c" else CSV_TEXT_FIELDS.get(version)
            body_fields = (
                [body_index]
                if fields and fields[0] == "TEXT" and body_index is not None and len(fields) > body_index
                else []
            )
            yield {
                "kind": "record",
                "record_type": fields[0] if fields else "",
                "field_count": len(fields),
                "fields": {str(i): value for i, value in enumerate(fields) if i not in body_fields},
                "embedded_bodies": [{**row_source, "field_index": i, "delimiter": delimiter} for i in body_fields],
                "source": row_source,
            }


def filing_body(*, store: Path, body: dict, max_bytes: int = 8 * 1024**2) -> str:
    """Resolve one body, preserving whitespace and verifying the original anew.

    For many references, open the original once with LocalBlobSource and read
    their byte ranges; calling this helper per body repeats whole-file hashing.
    """
    start, length = body["byte_offset"], body["byte_length"]
    if any(type(value) is not int or value < 0 for value in (start, length)):
        raise ValueError("FEC body needs nonnegative integer byte coordinates")
    if type(max_bytes) is not int or max_bytes <= 0 or length > max_bytes:
        raise ValueError("FEC body exceeds its selected byte bound")
    with LocalBlobSource(store).open(body["sha256"]) as stream:
        if start + length > stream.seek(0, 2):
            raise ValueError("FEC body extends beyond its retained original")
        stream.seek(start)
        raw = stream.read(length)
    if len(raw) != length:
        raise ValueError("FEC body extends beyond its retained original")
    text = raw.decode(body["encoding"])
    if "field_index" in body:
        if type(body["field_index"]) is not int or body["field_index"] < 0:
            raise ValueError("FEC body field index must be a nonnegative integer")
        if body["delimiter"] == "\x1c":
            fields = text.rstrip("\r\n").split("\x1c")
        elif body["delimiter"] == ",":
            records = csv.reader(io.StringIO(text, newline=""), strict=True)
            fields = next(records, None)
            if fields is None or next(records, None) is not None:
                raise ValueError("FEC CSV body reference must contain exactly one record")
        else:
            raise ValueError("FEC body field reference requires ASCII FS or CSV")
        if body["field_index"] >= len(fields):
            raise ValueError("FEC body field index is outside its retained record")
        return fields[body["field_index"]]
    return text
