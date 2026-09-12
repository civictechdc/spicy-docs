"""Bounded decoding of CourtListener's PostgreSQL CSV export.

The publisher uses UTF-8, HEADER, ESCAPE '\\', and FORCE_QUOTE *:
https://github.com/freelawproject/courtlistener/blob/main/scripts/make_bulk_data.sh
Unquoted empty fields are NULL; quoted empty fields are empty strings. Python
3.12's csv.QUOTE_NOTNULL reader does not preserve that distinction.
"""

from __future__ import annotations

import codecs
import io
import re
from collections.abc import Callable, Iterator
from typing import BinaryIO

MAX_RECORD_CHARACTERS = 64 * 1024 * 1024
MAX_COLUMNS = 1024
_TEXT_CHUNK = 64 * 1024
_UNQUOTED_RUN = re.compile(r'[^,"\r\n]+')
_QUOTED_RUN = re.compile(r'[^"\\]+')


class CourtListenerCsvError(ValueError):
    """The source CSV cannot be decoded faithfully within its limits."""


def validate_record_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_record_characters must be a positive integer")


def iter_postgres_csv(
    stream: BinaryIO,
    *,
    max_record_characters: int = MAX_RECORD_CHARACTERS,
    is_truncated: Callable[[], bool] = lambda: False,
) -> Iterator[list[str | None]]:
    """Decode one record at a time, counting the header as record 1.

    The record limit includes CSV quoting and delimiters, but excludes its line
    ending. A deliberate compressed-byte cutoff discards the unfinished record.
    Backslashes only escape quotes/backslashes inside quoted fields; they are
    literal otherwise. This is the publisher's dialect, without auto-detection.
    """
    validate_record_limit(max_record_characters)
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    state = "start"
    field = io.StringIO()
    fields: list[str | None] = []
    record_number = 1
    record_characters = 0
    skip_lf = False

    def error(reason: str) -> CourtListenerCsvError:
        return CourtListenerCsvError(f"CourtListener CSV record {record_number}: {reason}")

    def count(size: int) -> None:
        nonlocal record_characters
        record_characters += size
        if record_characters > max_record_characters:
            raise error(f"exceeds {max_record_characters} characters")

    def finish_field() -> None:
        if len(fields) >= MAX_COLUMNS:
            raise error(f"exceeds {MAX_COLUMNS} columns")
        fields.append(None if state == "start" else field.getvalue())
        field.seek(0)
        field.truncate(0)

    while True:
        encoded = stream.read(_TEXT_CHUNK)
        invalid_utf8 = False
        try:
            chunk = decoder.decode(encoded, final=not encoded and not is_truncated())
        except UnicodeDecodeError as exc:
            # Process the valid prefix first so the error names its actual CSV
            # record, even when a single input block contains many records.
            chunk = exc.object[: exc.start].decode("utf-8")
            invalid_utf8 = True
        position = 0
        while position < len(chunk):
            char = chunk[position]
            if skip_lf:
                skip_lf = False
                if char == "\n":
                    position += 1
                    continue
            if state in {"start", "unquoted", "quoted"}:
                pattern = _QUOTED_RUN if state == "quoted" else _UNQUOTED_RUN
                if match := pattern.match(chunk, position):
                    value = match.group()
                    count(len(value))
                    field.write(value)
                    if state == "start":
                        state = "unquoted"
                    position = match.end()
                    continue
            position += 1
            if state == "escaped":
                count(1)
                field.write(char if char in {'"', "\\"} else "\\" + char)
                state = "quoted"
            elif state == "quoted":
                count(1)
                state = "escaped" if char == "\\" else "closed"
            elif char in "\r\n":
                finish_field()
                yield fields
                fields = []
                state = "start"
                record_number += 1
                record_characters = 0
                skip_lf = char == "\r"
            elif char == ",":
                count(1)
                finish_field()
                state = "start"
            elif char == '"' and state == "start":
                count(1)
                state = "quoted"
            else:
                raise error(
                    "unexpected character after a closing quote" if state == "closed" else "quote in unquoted field"
                )
        if invalid_utf8:
            raise error("invalid UTF-8") from None
        if not encoded:
            break

    if is_truncated():
        return
    if state in {"quoted", "escaped"}:
        raise error("unterminated quoted field")
    if record_characters:
        finish_field()
        yield fields
