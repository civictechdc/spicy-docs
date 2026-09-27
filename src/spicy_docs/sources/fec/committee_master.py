"""The FEC committee master: one row per committee per two-year cycle, from the bulk ``cm<yy>.zip`` files.

The bulk bucket holds one file per cycle from 1980, each a ZIP whose only member is ``cm.txt``: pipe-delimited rows
with no header and literal quotes, whose fields ``cm_header_file.csv`` names. Quotes are data: a name such as
``"CALIFORNIA STATE COUNCIL OF CARPENTERS POLITICAL ACTION FUND"`` (cm84, ``C00065862``) keeps them, where CSV
quoting would strip them and join fields. The rules below rest on the 24 files of 1980-2026 fetched on 2026-09-27
and pinned by digest in ``~/Work/corpora/fork-execution-2026-09-21/committee-master-measure-2026-09-27/measure.json``
(``measure.py`` beside it): every row has 15 fields, the highest byte is 0x7C, and the longest row is 408 bytes.
The rows are ASCII, so they are read as UTF-8, as the retained ``cm24`` scope of 2026-09-12 reads them; a byte
that is not UTF-8 refuses rather than decoding to other characters, which latin-1 would do silently.

Fields stay the publisher's literal strings; no code is expanded. Consumers own acquisition and retention: this
module names the URLs and reads retained bytes through a blob source that verifies them by digest.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

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
#: The longest measured row is 408 bytes; a row past this is not a committee-master row.
MAX_RECORD_BYTES = 16 * 1024
#: The header file is 158 bytes.
MAX_HEADER_BYTES = 4 * 1024


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


@contextmanager
def _retained(blob_source, capture: Mapping):
    """Open retained bytes by their digest, which the blob source verifies, and hold them to the stated size."""
    with blob_source.open(capture["responseSha256"]) as stream:
        size = stream.seek(0, io.SEEK_END)
        stream.seek(0)
        if size != capture["byteSize"]:
            raise ValueError("FEC retained original differs from its stated byte size")
        yield stream


def iter_committee_master_rows(*, capture: Mapping, header_capture: Mapping, blob_source, cycle: int) -> Iterator[dict]:
    """Yield each row of one cycle's retained file as ``{cycle, fields, source}``, fields keyed by the header.

    ``capture`` and ``header_capture`` are the retained originals' capture facts: the cycle's own ZIP, requested at
    :func:`committee_master_url`, and ``cm_header_file.csv`` at :data:`HEADER_URL`. ``blob_source`` opens each by
    its digest and must verify it, as ``rulespec_artifacts.LocalBlobSource`` does; its size must match too. The
    header is read and checked here. ``source`` gives the member's sha256 and the row's byte offset and length.

    It refuses a ZIP with any member but ``cm.txt``, a member with no rows, a row of another width, and bytes that
    are not UTF-8 or not literal pipe-delimited text. Only natural exhaustion establishes a complete parse: a
    refusal part-way stops the reader after earlier rows were yielded, so keep nothing from a file until it ends.
    """
    capture, header_capture = original_capture(capture), original_capture(header_capture)
    if capture["requestUrl"] != committee_master_url(cycle) or capture["representation"] != "zip":
        raise ValueError("FEC committee master capture is not this cycle's ZIP")
    if header_capture["requestUrl"] != HEADER_URL or header_capture["representation"] != "opaque":
        raise ValueError("FEC committee master header capture is not cm_header_file.csv")
    with _retained(blob_source, header_capture) as stream:
        committee_master_header(stream.read(MAX_HEADER_BYTES))
    rows = 0
    with (
        _retained(blob_source, capture) as original,
        selected_stream(
            original, capture=capture, member=MEMBER, max_members=1, max_decoded_bytes=MAX_DECODED_BYTES
        ) as (decoded, _, sha256),
    ):
        try:
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
                rows += 1
                yield {
                    "cycle": cycle,
                    "fields": dict(zip(COMMITTEE_MASTER_FIELDS, fields, strict=True)),
                    "source": row["source"],
                }
        except csv.Error as error:
            raise ValueError(f"FEC committee master row is not literal pipe-delimited text: {error}") from error
    if not rows:
        raise ValueError("FEC committee master member has no rows")


__all__ = [
    "COMMITTEE_MASTER_FIELDS",
    "FIRST_CYCLE",
    "HEADER_URL",
    "committee_master_cycles",
    "committee_master_header",
    "committee_master_url",
    "iter_committee_master_rows",
]
