"""The FEC committee master: one row per committee per two-year cycle, from the bulk ``cm<yy>.zip`` files.

The bulk bucket holds one file per cycle from 1980, each a ZIP whose only member is ``cm.txt``: pipe-delimited rows
with no header and no quoting, whose fields ``cm_header_file.csv`` names. Measured on 2026-09-27 over all 24 files,
1980 to 2026, fetched from the bucket: 298,395 rows naming 89,710 distinct committees, every row 15 fields, and no
byte above 0x7F in any file. The rows are ASCII, so they are read as UTF-8, as the retained ``cm24`` scope of
2026-09-12 reads them. A byte that is not UTF-8 refuses rather than decoding to other characters, which latin-1 would
do silently.

Fields stay the publisher's literal strings; no code is expanded. Consumers own acquisition and retention: this
module names the URLs and reads retained bytes.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Mapping

from spicy_docs.sources.fec.bulk_profile import MAX_DECODED_BYTES
from spicy_docs.sources.fec.catalog import BUCKET_URL
from spicy_docs.sources.fec.delimited import delimited_rows, selected_stream
from spicy_docs.sources.fec.originals import original_capture

#: ``cm_header_file.csv``, in order (retained 2026-09-12 as sha256:9b5bfd77…).
COMMITTEE_MASTER_FIELDS: tuple[str, ...] = (
    "CMTE_ID",
    "CMTE_NM",
    "TRES_NM",
    "CMTE_ST1",
    "CMTE_ST2",
    "CMTE_CITY",
    "CMTE_ST",
    "CMTE_ZIP",
    "CMTE_DSGN",
    "CMTE_TP",
    "CMTE_PTY_AFFILIATION",
    "CMTE_FILING_FREQ",
    "ORG_TP",
    "CONNECTED_ORG_NM",
    "CAND_ID",
)
HEADER_URL = f"{BUCKET_URL}bulk-downloads/data_dictionaries/cm_header_file.csv"
FIRST_CYCLE = 1980
ENCODING = "utf-8"
#: The one member every cycle's ZIP holds.
MEMBER = {"ordinal": 0, "name": "cm.txt"}
#: The longest row of the 24 files measured on 2026-09-27 is 408 bytes; a row past this is not a committee-master row.
MAX_RECORD_BYTES = 16 * 1024


def _cycle(cycle: int) -> int:
    if type(cycle) is not int or cycle < FIRST_CYCLE or cycle % 2:
        raise ValueError(f"FEC committee master cycles are even years from {FIRST_CYCLE}")
    return cycle


def committee_master_cycles(through: int) -> tuple[int, ...]:
    """Every cycle from 1980 through ``through``: the even years the bucket files the committee master by."""
    return tuple(range(FIRST_CYCLE, _cycle(through) + 1, 2))


def committee_master_url(cycle: int) -> str:
    """The bucket URL of one cycle's committee master, ``bulk-downloads/<cycle>/cm<yy>.zip``."""
    return f"{BUCKET_URL}bulk-downloads/{_cycle(cycle)}/cm{cycle % 100:02d}.zip"


def committee_master_header(raw: bytes) -> tuple[str, ...]:
    """Read ``cm_header_file.csv`` and refuse any field list but :data:`COMMITTEE_MASTER_FIELDS`.

    The data files carry no header, so this is the only statement of what each position means; a publisher change
    must stop a reader, not shift every column.
    """
    rows = [row for row in csv.reader(io.StringIO(raw.decode(ENCODING))) if row]
    if rows != [list(COMMITTEE_MASTER_FIELDS)]:
        raise ValueError("FEC committee master header differs from the fields this reader maps")
    return COMMITTEE_MASTER_FIELDS


def iter_committee_master_rows(stream, *, capture: Mapping, cycle: int, header: tuple[str, ...]) -> Iterator[dict]:
    """Yield each row of one cycle's retained file as ``{cycle, fields, source}``, fields keyed by the header.

    ``capture`` is the retained original's capture facts and ``stream`` its bytes. The capture must be the cycle's
    own file, requested at :func:`committee_master_url`, and a ZIP whose only member is ``cm.txt``. ``header`` is
    what :func:`committee_master_header` returned for the retained header file. A row with another field count
    refuses. ``source`` gives the member's sha256 and the row's byte offset and length in it.
    """
    capture = original_capture(capture)
    if capture["requestUrl"] != committee_master_url(cycle) or capture["representation"] != "zip":
        raise ValueError("FEC committee master capture is not this cycle's ZIP")
    if tuple(header) != COMMITTEE_MASTER_FIELDS:
        raise ValueError("FEC committee master rows need the checked header")
    with selected_stream(
        stream, capture=capture, member=MEMBER, max_members=1, max_decoded_bytes=MAX_DECODED_BYTES
    ) as (decoded, _, sha256):
        for row in delimited_rows(
            decoded,
            sha256=sha256,
            encoding=ENCODING,
            delimiter="|",
            quoting="literal",
            max_record_bytes=MAX_RECORD_BYTES,
        ):
            fields = row["fields"]
            if len(fields) != len(COMMITTEE_MASTER_FIELDS):
                raise ValueError(
                    f"FEC committee master row has {len(fields)} fields, not {len(COMMITTEE_MASTER_FIELDS)}"
                )
            yield {
                "cycle": cycle,
                "fields": dict(zip(COMMITTEE_MASTER_FIELDS, fields, strict=True)),
                "source": row["source"],
            }


__all__ = [
    "COMMITTEE_MASTER_FIELDS",
    "FIRST_CYCLE",
    "HEADER_URL",
    "committee_master_cycles",
    "committee_master_header",
    "committee_master_url",
    "iter_committee_master_rows",
]
