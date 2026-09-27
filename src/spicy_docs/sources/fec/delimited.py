"""One FEC original or selected ZIP member, decoded and split into literal delimited rows with byte coordinates.

The positional-row release profile and the committee-master reader both read through here, so the bounded ZIP
selection and the row split exist once.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from zipfile import ZipFile

from spicy_docs.reading.zip_archive import inspect_archive_stream, seekable_stream
from spicy_docs.sources.fec.bulk_profile import MAX_INVENTORY_BYTES
from spicy_docs.sources.fec.filings import _Lines


@contextmanager
def selected_stream(stream, *, capture: Mapping, member: Mapping | None, max_members: int, max_decoded_bytes: int):
    """Yield ``(decoded stream, member, sha256)`` for an opaque original, or for the one ZIP member ``member`` selects.

    ``capture`` is a validated original capture. For a ZIP the whole archive's bounded inventory is decoded first,
    so every member is verified before a row is read; a missing ordinal, a differing name or a directory refuses.
    ``sha256`` is the original's digest, or the selected member's.
    """
    if member is None:
        if capture["byteSize"] > max_decoded_bytes:
            raise ValueError("FEC original exceeds its decoded byte bound")
        yield stream, None, capture["responseSha256"]
        return
    with seekable_stream(stream, byte_size=capture["byteSize"]) as original:
        inventory = inspect_archive_stream(
            original,
            byte_size=capture["byteSize"],
            max_entries=max_members,
            max_decoded_bytes=max_decoded_bytes,
            max_metadata_bytes=MAX_INVENTORY_BYTES,
        )
        ordinal = member["ordinal"]
        if ordinal >= len(inventory["members"]):
            raise ValueError("FEC selected ZIP member is missing")
        selected = inventory["members"][ordinal]
        if selected["name"] != member["name"] or selected["isDirectory"]:
            raise ValueError("FEC selected ZIP member identity differs or is a directory")
        # The complete bounded decoder has verified every member. Reuse the same
        # original for standard streaming reads; never reopen it for each row/page.
        with ZipFile(original) as archive, archive.open(archive.infolist()[ordinal]) as decoded:
            yield decoded, member, selected["sha256"]


def delimited_rows(
    stream, *, sha256: str, encoding: str, delimiter: str, quoting: str, max_record_bytes: int
) -> Iterator[dict]:
    """Split a decoded stream into rows of literal fields, each with its byte offset and length in that stream.

    ``quoting`` ``"csv"`` follows Python's CSV syntax; ``"literal"`` keeps quote characters as data. A row longer
    than ``max_record_bytes`` refuses.
    """
    lines = _Lines(stream, encoding, max_record_bytes)
    while True:
        lines.start = lines.end
        fields = next(
            csv.reader(
                lines,
                delimiter=delimiter,
                quoting=csv.QUOTE_MINIMAL if quoting == "csv" else csv.QUOTE_NONE,
                strict=True,
            ),
            None,
        )
        if fields is None:
            return
        yield {
            "kind": "row",
            "fields": fields,
            "source": {
                "sha256": sha256,
                "byte_offset": lines.start,
                "byte_length": lines.end - lines.start,
                "encoding": encoding,
            },
        }
