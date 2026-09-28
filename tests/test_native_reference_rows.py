"""Native U.S. Code and eCFR observations shaped and read through their table contracts, held to the published rows."""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from spicy_docs.interpretation.native_legal_references import (
    interpret_native_reference,
    interpret_native_references,
)
from spicy_docs.schemas import TABLE_CONTRACTS, TableContractError
from spicy_docs.schemas.native_reference_rows import (
    NATIVE_LEGAL_REFERENCE_READS,
    NATIVE_LEGAL_REFERENCES,
    native_reference_scope_id,
    shape_ecfr_note,
    shape_native_reference_read,
    shape_uscode_reference,
    shape_uscode_source_credit,
)
from spicy_docs.schemas.tables import json_column
from spicy_docs.sources.cfr.authority import scan_ecfr_authority_notes
from spicy_docs.sources.uscode.references import scan_uscode_references

FIXTURES = Path(__file__).parent / "fixtures"
#: The columns the reading fills after shaping: what it read, the targets it found, and the rule it ran under.
READING_COLUMNS = ("interpretation_status", "target_candidates_json", "rule_version")


def no_target_tables(candidates: list[dict[str, object]], texts: dict[tuple[str, str], str]) -> list[dict[str, object]]:
    """A stub lookup for a fixture with no target tables: every candidate unchanged, marked as never looked up."""
    return [
        {**candidate, "target_status": "not_checked", "reason": "no_target_tables_in_fixture"}
        for candidate in candidates
    ]


def _published() -> dict[str, list[dict[str, Any]]]:
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


def _usc01() -> bytes:
    with zipfile.ZipFile(io.BytesIO((FIXTURES / "uscode/xml_usc01@119-103.zip").read_bytes())) as archive:
        return archive.read("usc01.xml")


#: The context the host's manifest stated for the U.S. Code input it published, written here.
_USC01_CONTEXT: dict[str, Any] = {
    "source_record_key": "/us/usc/t1",
    "edition": "119-103",
    "source_locator": "https://uscode.house.gov/download/releasepoints/us/pl/119/103/xml_usc01@119-103.zip",
}


def _usc01_rows() -> list[dict[str, str | None]]:
    """Every observation of the U.S. Code Title 1 release point the host published, shaped in the host's order.

    One ordinal per input over both kinds, in the order the scanner reports them: the host's callback counter.
    """
    body = _usc01()
    context = {**_USC01_CONTEXT, "input_sha256": _sha256(body)}
    rows: list[dict[str, str | None]] = []
    scan_uscode_references(
        body,
        on_reference=lambda o: rows.append(shape_uscode_reference(o, occurrence_index=len(rows), **context)),
        on_source_credit=lambda o: rows.append(shape_uscode_source_credit(o, occurrence_index=len(rows), **context)),
    )
    return rows


def _replayed_lookup(published: list[dict[str, str | None]]):
    """A lookup that answers each candidate with the outcome the host published for it, after checking that the
    candidate is the published one on every field the reading writes.

    It cannot check the lookup's own fields, which come from the published rows; the reading's fields, their order and
    count, and the spelling of the column are what it holds.
    """
    outcomes = {
        outcome["occurrence_key"]: outcome
        for row in published
        for outcome in json.loads(row["target_candidates_json"] or "[]")
    }

    def lookup(candidates, texts):
        answered = []
        for candidate in candidates:
            outcome = outcomes[candidate["occurrence_key"]]
            assert {field: outcome[field] for field in candidate} == candidate
            if "text_sha256" in candidate:
                assert texts[(candidate["document_kind"], candidate["document_key"])] == candidate["text_sha256"]
            answered.append(outcome)
        return answered

    return lookup


def test_the_shaped_and_read_us_code_rows_are_the_published_rows() -> None:
    """The published rows came from the archive's own ``usc01.xml``: shaping and the reading reproduce every column.

    A shaped row holds the reading's three columns NULL and every other column as published. Completed, it is the
    published row on all of them, ``target_candidates_json`` spelled by ``json_column``: that re-spells only source
    credit 94's, whose ``Pub. L. 104–199`` the host wrote with a literal en dash.
    """
    shaped = {row["occurrence_index"]: row for row in _usc01_rows()}
    published = [row for row in _published()["native_legal_references"] if row["source_family"] == "uscode"]
    assert len(published) == 8
    mine = [shaped[row["occurrence_index"]] for row in published]
    for row, shaped_row in zip(published, mine, strict=True):
        assert list(shaped_row) == list(row)
        assert {c: shaped_row[c] for c in row if c not in READING_COLUMNS} == {
            c: row[c] for c in row if c not in READING_COLUMNS
        }
        assert [shaped_row[c] for c in READING_COLUMNS] == [None, None, None]
    completed = interpret_native_references(mine, resolve=_replayed_lookup(published))
    respelled = []
    for row, done in zip(published, completed, strict=True):
        assert {c: done[c] for c in row if c != "target_candidates_json"} == {
            c: row[c] for c in row if c != "target_candidates_json"
        }
        assert done["target_candidates_json"] == json_column(json.loads(row["target_candidates_json"] or ""))
        if done["target_candidates_json"] != row["target_candidates_json"]:
            respelled.append(row["occurrence_index"])
    assert respelled == ["94"]


def test_the_reading_reproduces_each_published_rows_reading() -> None:
    """Every published row, eCFR notes included, read again from its own observation columns."""
    published = _published()["native_legal_references"]
    stripped = [{**row, **dict.fromkeys(READING_COLUMNS)} for row in published]
    completed = interpret_native_references(stripped, resolve=_replayed_lookup(published))
    for row, done in zip(published, completed, strict=True):
        assert done["interpretation_status"] == row["interpretation_status"]
        assert done["rule_version"] == row["rule_version"]
        assert json.loads(done["target_candidates_json"] or "") == json.loads(row["target_candidates_json"] or "")
    assert {row["interpretation_status"] for row in completed} == {
        "unsupported_href",
        "native_statute_href",
        "native_section_href",
        "native_public_law_href",
        "partial_text_findings",
    }


def _reading(**row: str | None):
    base = dict.fromkeys(NATIVE_LEGAL_REFERENCES.columns)
    base.update(scope_id="sha256:" + "0" * 64, occurrence_index="7", source_family="uscode", source_record_key="r")
    base.update(row)
    return interpret_native_reference(base)


@pytest.mark.parametrize(
    ("tag", "href", "expected"),
    [
        ("{http://xml.house.gov/schemas/uslm/1.0}ref", "/us/usc/t26/s1400Z–1", ("usc_section", "26-1400z-1")),
        ("ref", "/us/usc/t5a/s2", ("usc_section", "5A-2")),
        ("{http://www.w3.org/1999/xhtml}a", "/us/stat/61/633", ("statutes_at_large", "61-633")),
        ("ref", "/us/pl/57/1", ("public_law", "57-public-1")),
        ("ref", "/us/pl/56/1", None),
        ("ref", "/us/usc/t1/s1/a", None),
        ("ref", "/us/usc/t1/s1#note", None),
        ("ref", "/us/act/1947-07-30/ch388/s1", None),
        ("{urn:unknown}ref", "/us/usc/t1/s1", None),
        ("ref", None, None),
    ],
)
def test_an_href_is_typed_only_in_its_exact_native_shapes(tag: str, href: str | None, expected) -> None:
    reading = _reading(observation_kind="native_reference", element_tag=tag, href=href)
    if expected is None:
        assert (reading.status, reading.candidates) == ("unsupported_href", ())
        return
    (candidate,) = reading.candidates
    assert (candidate["cite_kind"], candidate["target_key"]) == expected
    assert candidate["occurrence_key"] == "sha256:" + "0" * 64 + ":7:href"
    assert candidate["derivation_rule"] == "native-legal-exact-href/002"


def test_a_note_is_read_for_its_citations_and_a_part_stays_a_part() -> None:
    reading = _reading(observation_kind="authority", text="5 U.S.C. 301; 1 CFR part 18; 19 FR 2709.")
    assert reading.status == "partial_text_findings"
    kinds = [(c["cite_kind"], c["target_key"]) for c in reading.candidates]
    assert ("usc_section", "5-301") in kinds and ("federal_register_cite", "19-2709") in kinds
    assert ("cfr_part", "1-18") in kinds and not [k for k in kinds if k == ("cfr_section", "1-18")]
    assert [c["occurrence_key"] for c in reading.candidates] == [
        f"{'sha256:' + '0' * 64}:7:{i}" for i in range(len(kinds))
    ]
    assert {c["text_sha256"] for c in reading.candidates} == {_sha256(b"5 U.S.C. 301; 1 CFR part 18; 19 FR 2709.")}
    assert _reading(observation_kind="source_note", text="Unrelated prose.").status == "no_qualified_text_findings"


def _looked_up_rows() -> list[dict[str, Any]]:
    """Three href rows with one candidate each and a source credit with several, from the published archive."""
    rows = _usc01_rows()
    single = [row for row in rows if len(interpret_native_reference(row).candidates) == 1][:3]
    several = next(row for row in rows if len(interpret_native_reference(row).candidates) > 1)
    return [*single, several]


def _sort_in_place(candidates, texts):
    candidates.sort(key=lambda candidate: candidate["occurrence_key"], reverse=True)
    return candidates


def _pop_in_place(candidates, texts):
    candidates.pop(0)
    return candidates


def _rekey_in_place(candidates, texts):
    for candidate in candidates:
        candidate["occurrence_key"] = "x"
    return candidates


@pytest.mark.parametrize(
    "lookup",
    [
        _sort_in_place,
        _pop_in_place,
        _rekey_in_place,
        lambda candidates, texts: [{**c, "target_key": "WRONG"} for c in candidates],
        lambda candidates, texts: [{**c, "document_key": "WRONG"} for c in candidates],
        lambda candidates, texts: [{k: v for k, v in c.items() if k != "matched_text"} for c in candidates],
        lambda candidates, texts: [dict(c) for c in reversed(candidates)],
        lambda candidates, texts: [dict(c) for c in candidates][:-1],
    ],
    ids=[
        "sort-in-place",
        "pop-in-place",
        "rekey-in-place",
        "new-target-key",
        "new-document-key",
        "drop-a-field",
        "reversed-copy",
        "one-short",
    ],
)
def test_a_lookup_that_moves_loses_or_rewrites_a_candidate_refuses(lookup) -> None:
    """A lookup gets copies, so mutating them in place changes nothing it is checked against, and every outcome must
    keep its candidate's fields: which candidate it is, and which row it lands in, are never the lookup's to choose."""
    rows = _looked_up_rows()
    readings = [interpret_native_reference(row) for row in rows]
    with pytest.raises(TableContractError, match="one outcome per candidate"):
        interpret_native_references(rows, resolve=lookup)
    assert [interpret_native_reference(row) for row in rows] == readings
    control = interpret_native_references(rows, resolve=lambda candidates, texts: [dict(c) for c in candidates])
    assert [json.loads(row["target_candidates_json"] or "") for row in control] == [
        list(reading.candidates) for reading in readings
    ]


def test_the_lookup_is_required_so_every_row_carries_its_outcome() -> None:
    import inspect

    parameter = inspect.signature(interpret_native_references).parameters["resolve"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is inspect.Parameter.empty


def test_two_rows_naming_one_observation_refuse_before_the_lookup() -> None:
    """Their identities differ in input_sha256 alone, so both are keyable, but their candidates would share keys."""
    (row,) = _looked_up_rows()[:1]
    twin = {**row, "input_sha256": "sha256:" + "1" * 64}
    asked = []
    with pytest.raises(TableContractError, match="two rows name observation"):
        interpret_native_references([row, twin], resolve=lambda candidates, texts: asked.append(1) or candidates)
    assert asked == []


def test_each_note_is_hashed_once_and_its_digest_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    from spicy_docs.interpretation import native_legal_references as reading

    rows = _looked_up_rows()
    hashed: list[str] = []

    def counted(value):
        hashed.append(value)
        return json_column(value)  # any stable spelling; only the count matters here

    monkeypatch.setattr(reading, "digest", counted)
    texts_seen: list[dict] = []
    interpret_native_references(rows, resolve=lambda candidates, texts: texts_seen.append(texts) or candidates)
    notes = [row["text"] for row in rows if row["observation_kind"] != "native_reference"]
    assert hashed == notes and len(notes) == 1
    assert list(texts_seen[0].values()) == [json_column(notes[0])]


def test_every_rule_version_is_the_rule_constant_its_descriptions_name() -> None:
    from spicy_docs.schemas.native_reference_rows import NATIVE_LEGAL_REFERENCE_RULE

    for contract in (NATIVE_LEGAL_REFERENCES, NATIVE_LEGAL_REFERENCE_READS):
        sentence = contract.descriptions["rule_version"]
        assert f"`{NATIVE_LEGAL_REFERENCE_RULE}`" in sentence and "`NATIVE_LEGAL_REFERENCE_RULE`" in sentence
    rows = interpret_native_references(_looked_up_rows(), resolve=no_target_tables)
    assert {row["rule_version"] for row in rows} == {NATIVE_LEGAL_REFERENCE_RULE}
    published = _published()
    assert {row["rule_version"] for table in published.values() for row in table} == {NATIVE_LEGAL_REFERENCE_RULE}


def test_the_read_rows_are_the_published_read_rows() -> None:
    """The U.S. Code read from the archive's own bytes and count; the eCFR read from its published values."""
    body = _usc01()
    published = {row["source_family"]: row for row in _published()["native_legal_reference_reads"]}
    manifest = published["uscode"]["manifest_sha256"]
    usc = shape_native_reference_read(
        source_family="uscode",
        input_sha256=_sha256(body),
        source_bytes=len(body),
        occurrence_count=len(_usc01_rows()),
        manifest_sha256=manifest,
        **_USC01_CONTEXT,
    )
    assert list(usc.items()) == list(published["uscode"].items())
    ecfr = published["ecfr"]
    stated = ("source_family", "source_record_key", "edition", "input_sha256", "source_locator", "manifest_sha256")
    counts = {"source_bytes": int(ecfr["source_bytes"] or ""), "occurrence_count": int(ecfr["occurrence_count"] or "")}
    assert list(shape_native_reference_read(**{c: ecfr[c] for c in stated}, **counts).items()) == list(ecfr.items())


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"source_family": "cfr"}, "no native reference scanner"),
        ({"manifest_sha256": "0" * 64}, "manifest_sha256 must be spelled"),
        ({"source_bytes": -1}, "source_bytes must be a nonnegative integer"),
        ({"occurrence_count": "3"}, "occurrence_count must be a nonnegative integer"),
        ({"input_sha256": "sha256:" + "0" * 63}, "input_sha256 must be spelled"),
        ({"edition": ""}, "non-empty string or None"),
    ],
)
def test_the_read_shaper_refuses_what_would_publish_a_wrong_read(change: dict, refusal: str) -> None:
    good: dict[str, Any] = {
        "source_family": "ecfr",
        "source_record_key": "ecfr/title/1",
        "edition": None,
        "input_sha256": "sha256:" + "0" * 64,
        "source_locator": "synthetic:test",
        "source_bytes": 10,
        "occurrence_count": 0,
        "manifest_sha256": "sha256:" + "1" * 64,
    }
    assert shape_native_reference_read(**good)["unsupported_shapes_json"] == '["PARAUTH","SECAUTH"]'
    with pytest.raises(TableContractError, match=refusal):
        shape_native_reference_read(**{**good, **change})


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


def test_an_ecfr_note_refuses_an_empty_title_as_it_refuses_an_empty_edition() -> None:
    notes = []
    scan_ecfr_authority_notes(
        (FIXTURES / "cfr/ecfr-authority-title1-part18.xml").read_bytes(), on_authority=notes.append
    )
    assert shape_ecfr_note(notes[0], **_GOOD, title="1")["cfr_title"] == "1"
    assert shape_ecfr_note(notes[0], **_GOOD)["cfr_title"] is None
    with pytest.raises(TableContractError, match="title must be a non-empty string or None"):
        shape_ecfr_note(notes[0], **_GOOD, title="")


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
