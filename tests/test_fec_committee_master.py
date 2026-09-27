"""The FEC committee master reader: the bytes it verifies, the header it checks, the rows it keys, and its refusals."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from rulespec_artifacts import ArtifactVerificationError, LocalBlobSource

from spicy_docs.schemas.fec_committee_history import FEC_COMMITTEE_HISTORY, project_committee_master_row
from spicy_docs.sources.fec.committee_master import (
    COMMITTEE_MASTER_FIELDS,
    HEADER_URL,
    committee_master_cycles,
    committee_master_header,
    committee_master_url,
    iter_committee_master_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fec" / "committee_master"
HEADER = (FIXTURES / "cm_header_file.csv").read_bytes()
ROW = b"C1|NAME|T|S1||CITY|ST|00000|U|N||Q|||\n"


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _capture(raw: bytes, url: str, representation: str) -> dict:
    return {
        "requestUrl": url,
        "observedAt": "2026-09-27T01:00:00+00:00",
        "responseSha256": _digest(raw),
        "byteSize": len(raw),
        "representation": representation,
    }


def _store(root: Path, *blobs: bytes, under: str | None = None) -> LocalBlobSource:
    for raw in blobs:
        path = root / "sha256" / (under or _digest(raw)).removeprefix("sha256:")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return LocalBlobSource(root)


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _rows(tmp_path: Path, raw: bytes, cycle: int = 2024, *, capture: dict | None = None, header: bytes = HEADER):
    return list(
        iter_committee_master_rows(
            capture=capture or _capture(raw, committee_master_url(cycle), "zip"),
            header_capture=_capture(header, HEADER_URL, "opaque"),
            blob_source=_store(tmp_path, raw, header),
            cycle=cycle,
        )
    )


def test_the_publishers_header_is_the_one_the_reader_maps():
    assert committee_master_header(HEADER) == COMMITTEE_MASTER_FIELDS
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


def test_rows_are_keyed_by_the_header_with_their_byte_coordinates(tmp_path):
    raw = (FIXTURES / "cm24.zip").read_bytes()
    body = zipfile.ZipFile(io.BytesIO(raw)).read("cm.txt")
    rows = _rows(tmp_path, raw)
    assert [row["fields"]["CMTE_ID"] for row in rows] == ["C00000059", "C00000489", "C00002592"]
    assert rows[2]["fields"]["CAND_ID"] == "H6WA05023" and rows[1]["fields"]["CMTE_PTY_AFFILIATION"] == ""
    for row in rows:
        source = row["source"]
        assert source["sha256"] == _digest(body)
        line = body[source["byte_offset"] : source["byte_offset"] + source["byte_length"]]
        assert line.rstrip(b"\n").split(b"|") == [value.encode() for value in row["fields"].values()]
    assert project_committee_master_row(rows[1])["party"] is None
    assert tuple(project_committee_master_row(rows[2])) == FEC_COMMITTEE_HISTORY.columns


def test_quotes_are_literal_data(tmp_path):
    """A real cm84 name quoted whole keeps its quotes; CSV quoting would strip them."""
    rows = _rows(tmp_path, (FIXTURES / "cm84.zip").read_bytes(), 1984)
    assert rows[1]["fields"]["CMTE_NM"] == '"CALIFORNIA STATE COUNCIL OF CARPENTERS POLITICAL ACTION FUND"'


def test_the_reader_verifies_the_retained_bytes_it_reads(tmp_path):
    raw = _zip({"cm.txt": ROW})
    stated = "sha256:" + "0" * 64
    source = _store(tmp_path, HEADER)
    _store(tmp_path, raw, under=stated)  # the real bytes, filed under a digest they do not have
    with pytest.raises(ArtifactVerificationError, match="content address"):
        list(
            iter_committee_master_rows(
                capture={**_capture(raw, committee_master_url(2024), "zip"), "responseSha256": stated},
                header_capture=_capture(HEADER, HEADER_URL, "opaque"),
                blob_source=source,
                cycle=2024,
            )
        )
    stretched = {**_capture(raw, committee_master_url(2024), "zip"), "byteSize": len(raw) + 1}
    with pytest.raises(ValueError, match="stated byte size"):
        _rows(tmp_path / "size", raw, capture=stretched)


def test_the_reader_reads_the_retained_header_itself(tmp_path):
    with pytest.raises(ValueError, match="header differs"):
        _rows(tmp_path, _zip({"cm.txt": ROW}), header=b"CMTE_ID,CMTE_NM\n")


@pytest.mark.parametrize(
    ("members", "match"),
    [
        ({"cm.txt": ROW, "extra.txt": ROW}, "entry count"),
        ({"other.txt": ROW}, "member identity"),
        ({"cm.txt": b""}, "no rows"),
        ({"cm.txt": b"C1|NAME|T|S1||CITY|ST|00000|U|N||Q||\n"}, "14 fields"),
        ({"cm.txt": ROW.replace(b"NAME", b"N\xe9ME")}, "utf-8"),
        ({"cm.txt": ROW.replace(b"NAME", b"NA\rME")}, "literal pipe-delimited"),
    ],
)
def test_the_reader_refuses_what_is_not_a_committee_master(tmp_path, members, match):
    with pytest.raises(ValueError, match=match):
        _rows(tmp_path, _zip(members))


def test_the_reader_refuses_another_cycles_or_representations_capture(tmp_path):
    raw = _zip({"cm.txt": ROW})
    with pytest.raises(ValueError, match="not this cycle"):
        _rows(tmp_path, raw, capture=_capture(raw, committee_master_url(2022), "zip"))
    with pytest.raises(ValueError, match="not this cycle"):
        _rows(tmp_path, raw, capture=_capture(raw, committee_master_url(2024), "opaque"))


def test_a_blank_committee_id_is_refused_not_published():
    row = {"cycle": 2024, "fields": dict.fromkeys(COMMITTEE_MASTER_FIELDS, "")}
    with pytest.raises(ValueError, match="blank CMTE_ID"):
        project_committee_master_row(row)
