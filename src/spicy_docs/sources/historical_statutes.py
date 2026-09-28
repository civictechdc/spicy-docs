"""Literal community statute metadata from Legisworks and the Nabors table.

The caller retains the original bytes. Row ordinals identify observations;
statute pages and early bill numbers can name more than one record. These
readers neither merge those records nor infer missing Congress/session values.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re

from spicy_docs.reading.yaml_input import load_bounded_yaml
from spicy_docs.transport.source_acquirer import check_payload

_COMMIT = re.compile(r"[0-9a-f]{40}")
_FILE = re.compile(r"STATUTE-\d+-Pg[0-9A-Za-z.-]+\.pdf")
_NABORS_FIELDS = (
    "nabors-page",
    "congress",
    "slip-chapter",
    "slip-number",
    "stat-volume",
    "stat-page-start",
    "stat-page-end",
    "date",
    "bill-type",
    "bill-number",
    "has-note",
)


class HistoricalStatutesError(ValueError):
    """Retained bytes cannot establish the selected historical metadata file."""


def _input(raw: bytes, commit: str, max_bytes: int, max_rows: int) -> None:
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise HistoricalStatutesError("historical metadata requires a full lowercase Git commit")
    if type(max_rows) is not int or max_rows <= 0:
        raise HistoricalStatutesError("max_rows must be a positive integer")
    check_payload(raw, max_bytes, label="historical metadata", error_type=HistoricalStatutesError, allow_empty=False)


def _result(raw: bytes, repo: str, path: str, commit: str, rows: list[dict]) -> dict:
    return {
        "source_url": f"https://raw.githubusercontent.com/unitedstates/{repo}/{commit}/{path}",
        "commit": commit,
        "input_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "records": rows,
    }


def parse_legisworks_volume(
    raw: bytes, *, volume: int, commit: str, max_bytes: int = 4 * 1024**2, max_rows: int = 20_000
) -> dict:
    """Read one pinned volume using the ``yaml`` extra, retaining every field.

    Each result has a zero-based ``source_record_index``, the literal ``fields``
    and a metadata-derived ``pdf_url``. A URL is a locator, not a fetched PDF.
    Shared pages, fractional law numbers, nulls, and unknown fields survive.
    The supplied commit describes the caller's acquisition; bytes are independently
    hashed here, but the reader makes no network claim that Git served those bytes.
    """
    _input(raw, commit, max_bytes, max_rows)
    if type(volume) is not int or volume <= 0:
        raise HistoricalStatutesError("volume must be a positive integer")
    values = load_bounded_yaml(
        raw,
        source="Legisworks statute volume",
        error_type=HistoricalStatutesError,
        max_bytes=max_bytes,
    )
    if not isinstance(values, list) or not values or len(values) > max_rows:
        raise HistoricalStatutesError("Legisworks volume must be a nonempty list within max_rows")
    rows = []
    for index, fields in enumerate(values):
        if not isinstance(fields, dict) or any(not isinstance(key, str) for key in fields):
            raise HistoricalStatutesError(f"Legisworks row {index} must have named fields")
        if type(fields.get("volume")) is not int or fields["volume"] != volume:
            raise HistoricalStatutesError(f"Legisworks row {index} does not state the requested volume")
        if any(type(fields.get(key)) is not int or fields[key] <= 0 for key in ("page", "npages")):
            raise HistoricalStatutesError(f"Legisworks row {index} needs positive page and npages")
        file = fields.get("file")
        if not isinstance(file, str) or _FILE.fullmatch(file) is None or not file.startswith(f"STATUTE-{volume}-"):
            raise HistoricalStatutesError(f"Legisworks row {index} has an unsupported PDF filename")
        rows.append(
            {
                "source_record_index": index,
                "fields": fields,
                "pdf_url": f"https://govtrackus.s3.amazonaws.com/legislink/pdf/stat/{volume}/{file}",
            }
        )
    return _result(raw, "legisworks-historical-statutes", f"data/{volume:03d}.yaml", commit, rows)


def parse_nabors_table(raw: bytes, *, commit: str, max_bytes: int = 4 * 1024**2, max_rows: int = 30_000) -> dict:
    """Read the exact CSV columns as strings, including blanks and odd numbers.

    The CSV's Congress column is often blank. The reader leaves it blank; resolving
    an early bill requires separately qualified context. ``line_start`` and
    ``line_end`` are one-based physical CSV lines, inclusive. Header and malformed
    CSV decoding completes before any result returns. Rows with the source's
    ERROR marker or a different cell count remain ``unmapped`` with their exact
    cells and no guessed field assignment; they are not silently skipped.
    """
    _input(raw, commit, max_bytes, max_rows)
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
        if tuple(next(reader)) != _NABORS_FIELDS:
            raise HistoricalStatutesError("Nabors table has an unexpected header")
        rows = []
        previous_line = reader.line_num
        for cells in reader:
            if len(rows) >= max_rows:
                raise HistoricalStatutesError("Nabors table exceeds max_rows")
            reason = (
                "source_error_marker"
                if "ERROR" in cells
                else ("field_count" if len(cells) != len(_NABORS_FIELDS) else None)
            )
            rows.append(
                {
                    "source_record_index": len(rows),
                    "line_start": previous_line + 1,
                    "line_end": reader.line_num,
                    "status": "unmapped" if reason else "parsed",
                    "reason": reason,
                    "cells": cells,
                    "fields": None if reason else dict(zip(_NABORS_FIELDS, cells, strict=True)),
                }
            )
            previous_line = reader.line_num
    except (UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise HistoricalStatutesError("Nabors table must be a valid UTF-8 CSV with its expected header") from error
    if not rows:
        raise HistoricalStatutesError("Nabors table contains no data records")
    return _result(raw, "nabors", "table.csv", commit, rows)
