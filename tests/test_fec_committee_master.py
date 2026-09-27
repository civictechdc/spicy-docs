"""The FEC committee master reader: the header it checks, the rows it keys, and what it refuses."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from spicy_docs.schemas.fec_committee_history import FEC_COMMITTEE_HISTORY, project_committee_master_row
from spicy_docs.sources.fec.committee_master import (
    COMMITTEE_MASTER_FIELDS,
    committee_master_cycles,
    committee_master_header,
    committee_master_url,
    iter_committee_master_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fec" / "committee_master"


def _capture(raw: bytes, cycle: int = 2024) -> dict:
    return {
        "requestUrl": committee_master_url(cycle),
        "observedAt": "2026-09-27T01:00:00+00:00",
        "responseSha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "byteSize": len(raw),
        "representation": "zip",
    }


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _rows(raw: bytes, cycle: int = 2024) -> list[dict]:
    return list(
        iter_committee_master_rows(
            io.BytesIO(raw), capture=_capture(raw, cycle), cycle=cycle, header=COMMITTEE_MASTER_FIELDS
        )
    )


def test_the_publishers_header_is_the_one_the_reader_maps():
    assert committee_master_header((FIXTURES / "cm_header_file.csv").read_bytes()) == COMMITTEE_MASTER_FIELDS
    with pytest.raises(ValueError, match="header differs"):
        committee_master_header(b"CMTE_ID,CMTE_NM\n")


def test_cycles_and_urls_are_the_buckets_even_years():
    cycles = committee_master_cycles(2026)
    assert (cycles[0], cycles[-1], len(cycles)) == (1980, 2026, 24)
    assert committee_master_url(2024).endswith("/bulk-downloads/2024/cm24.zip")
    assert committee_master_url(1980).endswith("/bulk-downloads/1980/cm80.zip")
    for bad in (1978, 2025, "2024"):
        with pytest.raises(ValueError, match="even years"):
            committee_master_url(bad)


def test_rows_are_keyed_by_the_header_with_their_byte_coordinates():
    raw = (FIXTURES / "cm24.zip").read_bytes()
    body = zipfile.ZipFile(io.BytesIO(raw)).read("cm.txt")
    rows = _rows(raw)
    assert [row["fields"]["CMTE_ID"] for row in rows] == ["C00000059", "C00000489", "C00002592"]
    assert rows[2]["fields"]["CAND_ID"] == "H6WA05023" and rows[1]["fields"]["CMTE_PTY_AFFILIATION"] == ""
    for row in rows:
        source = row["source"]
        assert source["sha256"] == "sha256:" + hashlib.sha256(body).hexdigest()
        line = body[source["byte_offset"] : source["byte_offset"] + source["byte_length"]]
        assert line.rstrip(b"\n").split(b"|") == [value.encode() for value in row["fields"].values()]
    assert project_committee_master_row(rows[1])["party"] is None
    assert tuple(project_committee_master_row(rows[2])) == FEC_COMMITTEE_HISTORY.columns


def test_the_reader_refuses_what_is_not_one_cycles_committee_master():
    row = b"C1|NAME|T|S1||CITY|ST|00000|U|N||Q|||\n"
    with pytest.raises(ValueError, match="not this cycle"):
        list(
            iter_committee_master_rows(
                io.BytesIO(raw := _zip({"cm.txt": row})),
                capture=_capture(raw, 2022),
                cycle=2024,
                header=COMMITTEE_MASTER_FIELDS,
            )
        )
    with pytest.raises(ValueError):
        _rows(_zip({"cm.txt": row, "extra.txt": row}))
    with pytest.raises(ValueError, match="14 fields"):
        _rows(_zip({"cm.txt": b"C1|NAME|T|S1||CITY|ST|00000|U|N||Q||\n"}))
    with pytest.raises(UnicodeDecodeError):
        _rows(_zip({"cm.txt": row.replace(b"NAME", b"N\xe9ME")}))
    with pytest.raises(ValueError, match="checked header"):
        list(
            iter_committee_master_rows(
                io.BytesIO(raw := _zip({"cm.txt": row})),
                capture=_capture(raw),
                cycle=2024,
                header=COMMITTEE_MASTER_FIELDS[:-1],
            )
        )
