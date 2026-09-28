"""Native U.S. Code and eCFR observations shaped through their table contracts, held to the rows the host published."""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from spicy_docs.schemas import TABLE_CONTRACTS, TableContractError
from spicy_docs.schemas.native_reference_rows import (
    NATIVE_LEGAL_REFERENCE_READS,
    NATIVE_LEGAL_REFERENCES,
    native_reference_scope_id,
    shape_ecfr_note,
    shape_uscode_reference,
    shape_uscode_source_credit,
)
from spicy_docs.sources.cfr.authority import scan_ecfr_authority_notes
from spicy_docs.sources.uscode.references import scan_uscode_references

FIXTURES = Path(__file__).parent / "fixtures"
#: The columns the host fills after shaping: its interpretation of each observation, and the rule it ran.
HOST_COLUMNS = ("interpretation_status", "target_candidates_json", "rule_version")


def _published() -> dict[str, list[dict[str, str | None]]]:
    return json.loads((FIXTURES / "native_legal_references/published-rows.json").read_text(encoding="utf-8"))


def _sha256(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def test_native_uscode_occurrences_and_source_credit_keep_fragment_uncertainty() -> None:
    path = FIXTURES / "uscode/title-05-s423.xml"
    body = path.read_bytes()
    refs, credits = [], []
    scan = scan_uscode_references(body, on_reference=refs.append, on_source_credit=credits.append)
    assert (scan.references, scan.source_credits) == (30, 1)
    context = {
        "source_record_key": "/us/usc/t5/s423",
        "input_sha256": _sha256(body),
        "source_locator": "retained:title-05-s423.xml",
    }
    rows = [shape_uscode_reference(r, occurrence_index=i, **context) for i, r in enumerate(refs)]
    assert len(rows) == 30
    assert all(r["edition"] is None for r in rows)
    assert "/us/usc/t5/s401" in {r["href"] for r in rows}
    assert len({r["source_path"] for r in rows}) == 30
    for raw, row in zip(refs, rows, strict=True):
        assert json.loads(row["attributes_json"]) == raw.element.attributes
        assert len(json.loads(row["ancestors_json"])) == len(raw.ancestors)
    credit = shape_uscode_source_credit(credits[0], occurrence_index=0, **context)
    assert "117–286" in credit["text"] and "136 Stat. 4255" in credit["text"]
    assert credit["observation_kind"] == "source_credit"
    # The scope is the input's family, record key and stated edition, none of which the fragment states for itself.
    expected_scope = _sha256(b'["uscode","/us/usc/t5/s423",null]')
    assert {row["scope_id"] for row in [*rows, credit]} == {expected_scope}
    assert {row["source_family"] for row in [*rows, credit]} == {"uscode"}


def test_ecfr_authority_and_source_notes_keep_distinct_roles_and_complete_text() -> None:
    body = (FIXTURES / "cfr/ecfr-authority-title1-part18.xml").read_bytes()
    auth, source = [], []
    scan = scan_ecfr_authority_notes(body, on_authority=auth.append, on_source=source.append)
    context = {
        "source_record_key": "retained:part18-fragment",
        "input_sha256": "sha256:" + scan.input_sha256,
        "source_locator": "retained:ecfr-authority-title1-part18.xml",
    }
    a = shape_ecfr_note(auth[0], occurrence_index=0, **context)
    s = shape_ecfr_note(source[0], occurrence_index=1, **context)
    assert (a["observation_kind"], s["observation_kind"]) == ("authority", "source_note")
    assert a["cfr_title"] is a["edition"] is None  # the filename is not source metadata
    assert a["cfr_part"] == "18"
    assert "44 U.S.C. 1506" in a["text"] and "E.O. 10530" in a["text"]
    assert "37 FR 23609" in s["text"]
    assert a["text"] == "".join(json.loads(a["text_runs_json"]))
    assert a["source_path"] != s["source_path"]
    assert a["source_family"] == s["source_family"] == "ecfr"


def test_unknown_empty_and_absent_hrefs_are_preserved() -> None:
    # Synthetic controls, not newly qualified publisher shapes.
    body = b'<section><ref href="opaque:unknown#fragment"/><ref href=""/><ref/></section>'
    refs = []
    scan_uscode_references(body, on_reference=refs.append)
    rows = [
        shape_uscode_reference(
            r,
            source_record_key="synthetic",
            input_sha256=_sha256(body),
            source_locator="synthetic:test",
            occurrence_index=i,
        )
        for i, r in enumerate(refs)
    ]
    assert [r["href"] for r in rows] == ["opaque:unknown#fragment", "", None]


def _usc01_rows() -> list[dict[str, str | None]]:
    """Every observation of the U.S. Code Title 1 release point the host published, shaped in the host's order.

    One ordinal per input over both kinds, in the order the scanner reports them: the host's callback counter. The
    record key, edition and locator are the ones the host's manifest stated, written here.
    """
    with zipfile.ZipFile(io.BytesIO((FIXTURES / "uscode/xml_usc01@119-103.zip").read_bytes())) as archive:
        body = archive.read("usc01.xml")
    context = {
        "source_record_key": "/us/usc/t1",
        "edition": "119-103",
        "input_sha256": _sha256(body),
        "source_locator": "https://uscode.house.gov/download/releasepoints/us/pl/119/103/xml_usc01@119-103.zip",
    }
    rows: list[dict[str, str | None]] = []
    scan_uscode_references(
        body,
        on_reference=lambda o: rows.append(shape_uscode_reference(o, occurrence_index=len(rows), **context)),
        on_source_credit=lambda o: rows.append(shape_uscode_source_credit(o, occurrence_index=len(rows), **context)),
    )
    return rows


def test_the_shapers_reproduce_every_column_they_fill_of_the_published_us_code_rows() -> None:
    """The published rows came from the archive's own ``usc01.xml``; adopting the contract moves none of their values.

    The host fills three columns after shaping, so a shaped row holds them NULL and the rest equal the published row.
    """
    shaped = {row["occurrence_index"]: row for row in _usc01_rows()}
    published = _published()
    usc = [row for row in published["native_legal_references"] if row["source_family"] == "uscode"]
    assert len(usc) == 8
    for row in usc:
        mine = shaped[row["occurrence_index"]]
        assert list(mine) == list(row)
        assert {c: mine[c] for c in row if c not in HOST_COLUMNS} == {c: row[c] for c in row if c not in HOST_COLUMNS}
        assert [mine[c] for c in HOST_COLUMNS] == [None, None, None]
        assert all(row[c] is not None for c in HOST_COLUMNS)
    # The read row the host published for this input counts exactly these observations over exactly these bytes.
    (read,) = [row for row in published["native_legal_reference_reads"] if row["source_family"] == "uscode"]
    assert read["occurrence_count"] == str(len(shaped))
    assert read["input_sha256"] == usc[0]["input_sha256"] == next(iter(shaped.values()))["input_sha256"]
    with zipfile.ZipFile(io.BytesIO((FIXTURES / "uscode/xml_usc01@119-103.zip").read_bytes())) as archive:
        assert read["source_bytes"] == str(archive.getinfo("usc01.xml").file_size)


def test_every_shaped_row_spells_its_member_key_reversibly() -> None:
    rows = _usc01_rows()
    keys = [NATIVE_LEGAL_REFERENCES.spelled_key(row) for row in rows]
    assert len(set(keys)) == len(rows)
    for row, key in zip(rows, keys, strict=True):
        assert tuple(key.split("@")) == (row["scope_id"], row["input_sha256"], row["occurrence_index"])


def test_the_scope_id_is_the_spelling_the_host_published() -> None:
    published = _published()
    for table in ("native_legal_references", "native_legal_reference_reads"):
        for row in published[table]:
            scope = native_reference_scope_id(row["source_family"], row["source_record_key"], row["edition"])
            assert scope == row["scope_id"]
    # Every published observation's scope is a published read's: the reference the contract declares holds here.
    reads = {row["scope_id"] for row in published["native_legal_reference_reads"]}
    assert {row["scope_id"] for row in published["native_legal_references"]} == reads
    assert [(r.child_columns, r.parent_table, r.parent_columns) for r in NATIVE_LEGAL_REFERENCES.references] == [
        (("scope_id",), "native_legal_reference_reads", ("scope_id",))
    ]
    # The preimage keeps a non-ASCII character literal, as the host minted it; json_column would escape it.
    assert native_reference_scope_id("uscode", "/us/usc/t1/§1", None) == _sha256(
        '["uscode","/us/usc/t1/§1",null]'.encode()
    )


def _one_reference():
    refs = []
    scan_uscode_references(b'<section><ref href="/us/usc/t1/s1"/></section>', on_reference=refs.append)
    return refs[0]


_GOOD: dict[str, Any] = {
    "source_record_key": "synthetic",
    "input_sha256": "sha256:" + "0" * 64,
    "source_locator": "synthetic:test",
    "occurrence_index": 0,
    "edition": None,
}


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"source_record_key": ""}, "record key and locator"),
        ({"source_locator": ""}, "record key and locator"),
        ({"input_sha256": "0" * 64}, "sha256:"),
        ({"input_sha256": "sha256:" + "A" * 64}, "sha256:"),
        ({"input_sha256": "sha256:" + "0" * 63}, "sha256:"),
        ({"input_sha256": None}, "sha256:"),
        ({"occurrence_index": -1}, "nonnegative integer"),
        ({"occurrence_index": True}, "nonnegative integer"),
        ({"occurrence_index": "0"}, "nonnegative integer"),
        ({"edition": ""}, "non-empty string or None"),
    ],
)
def test_the_shapers_refuse_what_would_publish_a_wrong_scope_or_key(change: dict, refusal: str) -> None:
    reference = _one_reference()
    assert shape_uscode_reference(reference, **_GOOD)["href"] == "/us/usc/t1/s1"
    with pytest.raises(TableContractError, match=refusal):
        shape_uscode_reference(reference, **{**_GOOD, **change})


def test_an_ecfr_heading_is_not_a_note() -> None:
    headings = []
    scan_ecfr_authority_notes(
        (FIXTURES / "cfr/ecfr-authority-title1-part18.xml").read_bytes(), on_heading=headings.append
    )
    with pytest.raises(TableContractError, match="AUTH and SOURCE"):
        shape_ecfr_note(headings[0], **_GOOD)


@pytest.mark.parametrize(
    ("column", "value", "refusal"),
    [
        ("scope_id", None, "is null"),
        ("input_sha256", "", "empty identity component"),
        ("occurrence_index", "0@1", "holding '@'"),
        ("scope_id", "sha256:a@b", "holding '@'"),
    ],
)
def test_the_observation_key_refuses_a_component_it_cannot_spell(column: str, value: str | None, refusal: str) -> None:
    row = dict(_published()["native_legal_references"][0])
    assert NATIVE_LEGAL_REFERENCES.spelled_key(row).count("@") == 2
    row[column] = value
    with pytest.raises(TableContractError, match=refusal):
        NATIVE_LEGAL_REFERENCES.spelled_key(row)


@pytest.mark.parametrize(("value", "refusal"), [(None, "is null"), ("", "empty identity value")])
def test_the_read_key_refuses_a_scope_it_cannot_spell(value: str | None, refusal: str) -> None:
    row = dict(_published()["native_legal_reference_reads"][0])
    assert NATIVE_LEGAL_REFERENCE_READS.spelled_key(row) == row["scope_id"]
    row["scope_id"] = value
    with pytest.raises(TableContractError, match=refusal):
        NATIVE_LEGAL_REFERENCE_READS.spelled_key(row)


def test_both_contracts_are_registered_under_their_published_names() -> None:
    assert TABLE_CONTRACTS["native_legal_references"] is NATIVE_LEGAL_REFERENCES
    assert TABLE_CONTRACTS["native_legal_reference_reads"] is NATIVE_LEGAL_REFERENCE_READS
