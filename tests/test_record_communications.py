"""The Record's executive-communications parse rule, against the publisher's own decomposition.

The load-bearing test here is not that the rule finds spans; it is that the
spans it finds **equal what Congress.gov published for the same two
communications**. A rule scored only against its own output would be a
formatting assertion. `tests/fixtures/record_communications/README.md` names
every fixture and what it pins.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from spicy_docs.extraction.body_text import rendition_text
from spicy_docs.interpretation.communication_rin import rin_from_report_nature
from spicy_docs.sources.congress.record_communications import (
    AGENCY_HEAD_WORDS,
    RECORD_COMMUNICATION_RULE_VERSION,
    SECTION_COMMUNICATION_TYPE,
    SECTION_TITLE,
    RecordCommunicationEntry,
    RecordCommunicationError,
    contiguity_witness,
    executive_communication_granules,
    expand_public_law_abbreviation,
    expand_section_abbreviation,
    fold_en_dash,
    fold_print_dash,
    normalized_entry_text,
    parse_granule_body,
    parse_record_communications,
    publisher_normalized,
    rejoin_print_wraps,
    split_from_clause,
)
from spicy_docs.transport.captured import CapturedBodyResponse

FIXTURES = Path(__file__).parent / "fixtures"
SECTIONS = FIXTURES / "record_communications"


def section(name: str) -> tuple[RecordCommunicationEntry, ...]:
    """One fixture granule's entries, through the same text derivation production uses."""
    body = (SECTIONS / f"{name}.excerpt.htm").read_bytes()
    return parse_record_communications(
        rendition_text(body, rendition="htm").text,
        package_id=name.split("-pt")[0],
        granule_id=name.replace(".excerpt", ""),
    )


def numbered(name: str) -> dict[int, RecordCommunicationEntry]:
    return {entry.number: entry for entry in section(name)}


def publisher_detail(number: int) -> dict:
    path = FIXTURES / "listings" / f"congress-house-communication-detail-114-ec-{number}.json"
    return json.loads(path.read_text())["houseCommunication"]


# --- the ground truth: the abstract is the printed entry -------------------------------


@pytest.mark.parametrize("number", [4329, 4350])
def test_the_publishers_abstract_equals_the_printed_entry(number: int) -> None:
    """§2's decisive comparison, re-derived here from committed bytes.

    Byte for byte these differ; under the four named normalizations and
    nothing else they are the same string. That is the whole basis for reading
    a pre-114th entry as a communication record.
    """
    entry = numbered("CREC-2016-02-12-pt1-PgH815-4")[number]
    abstract = publisher_detail(number)["abstract"]
    assert publisher_normalized(entry.entry_text) == publisher_normalized(normalized_entry_text(abstract))
    # And the comparison can fail: unnormalized, these two are not equal, so
    # the assertion above is not true of any two strings.
    assert entry.entry_text != normalized_entry_text(abstract)


@pytest.mark.parametrize("number", [4329, 4350])
def test_every_typed_field_is_the_span_the_publisher_published(number: int) -> None:
    entry = numbered("CREC-2016-02-12-pt1-PgH815-4")[number]
    detail = publisher_detail(number)

    assert entry.submitting_official == detail["submittingOfficial"]
    assert entry.submitting_agency == detail["submittingAgency"]
    assert entry.split_resolved

    authority = publisher_normalized(normalized_entry_text(detail["legalAuthority"]))
    assert publisher_normalized(entry.legal_authority or "") == authority

    # The publisher capitalises the subject's first word and closes it with a
    # period; the Record prints it mid-sentence. That is presentation, and it
    # is the only difference.
    published = publisher_normalized(normalized_entry_text(detail["reportNature"])).rstrip(".")
    parsed = publisher_normalized(entry.report_nature or "")
    assert published == parsed[:1].upper() + parsed[1:]

    # The referral: the same committees in the same order. The *names* differ
    # in spelling by design -- the publisher says "Education and Workforce
    # Committee" where the Record says "Education and the Workforce" -- which
    # is exactly why §3.3 sends the names to the roster and not to a tokenizer.
    assert len(entry.committee_names) == len(detail["committees"])


def test_the_rin_rule_this_repository_already_owns_reads_a_reconstructed_subject() -> None:
    """No RIN rule lives in the parser: the existing one runs over its output unchanged."""
    entries = numbered("CREC-2016-02-12-pt1-PgH815-4")
    found = rin_from_report_nature(entries[4329].report_nature)
    assert found.rin == "1218-AC97"
    assert found.rule == "report_nature_rin_label"
    assert rin_from_report_nature(entries[4350].report_nature).rin is None


# --- the publisher normalizations, each on its own -----------------------------------------


def test_each_publisher_normalization_does_one_thing() -> None:
    assert fold_print_dash("final rule--Maine State Plan") == "final rule - Maine State Plan"
    assert fold_print_dash("final rule -- Maine") == "final rule - Maine"
    # 114th EC 1773 prints four hyphens where the publisher prints one dash;
    # `-{2,3}` left the remainder standing and the abstract never matched.
    assert fold_print_dash("Criterion ---- First") == "Criterion - First"
    assert expand_section_abbreviation("Public Law 104-121, Sec. 251") == "Public Law 104-121, section 251"
    assert expand_public_law_abbreviation("pursuant to Pub. L. 95-452") == "pursuant to Public Law 95-452"
    assert fold_en_dash("Public Law 104–121") == "Public Law 104-121"

    # Each leaves what the others own alone, so a failure names one rule.
    assert fold_print_dash("Sec. 251") == "Sec. 251"
    assert expand_section_abbreviation("rule--Maine") == "rule--Maine"
    assert expand_public_law_abbreviation("Sec. 251") == "Sec. 251"
    assert fold_en_dash("Sec. 251") == "Sec. 251"


def test_a_token_gpo_wrapped_across_two_lines_is_rejoined() -> None:
    """The single largest disagreement the overlap run found, and the RIN it was eating."""
    assert rejoin_print_wraps("[Docket No.: FDA-2013-\nC-1008)") == "[Docket No.: FDA-2013-C-1008)"
    assert rejoin_print_wraps("GROB-\nWERKE") == "GROB-WERKE"
    # A line-final print dash is not a wrap, and neither is a hyphen with no
    # word right after it: both are what the alphanumeric guards are for.
    assert rejoin_print_wraps("final rule--\nListing") == "final rule--\nListing"
    assert rejoin_print_wraps("rule -\n     Maine") == "rule -\n     Maine"

    # And through the whole normalization, with a page marker inside the token.
    assert normalized_entry_text("[EPA-R03-OAR-2013-\n\n[[Page H816]]\n\n0423; FRL-9928-78]") == (
        "[EPA-R03-OAR-2013-0423; FRL-9928-78]"
    )


def test_the_record_changed_how_it_numbers_an_entry_and_both_spellings_read() -> None:
    """1996-2020 print `1205.`; 2021 on print `EC-1205.`. Zero entries is the failure this prevents."""
    modern = parse_record_communications(
        "       EC-1205. A letter from the Director, Office of Personnel\n"
        "     Management, transmitting a letter reporting a violation, pursuant\n"
        "     to 31 U.S.C. 1517(b); to the Committee on Appropriations.\n"
    )
    assert [entry.number for entry in modern] == [1205]
    assert modern[0].communication_type == "ec"
    # "Office" is measured-ambiguous, so the split declines and the clause is kept whole.
    assert modern[0].split_resolved is False
    assert modern[0].from_clause == "Director, Office of Personnel Management"
    assert modern[0].committee_names == ("Appropriations",)


def test_the_en_dash_folds_before_the_print_dash() -> None:
    """Order matters: an en dash reaching the print-dash rule would survive as one."""
    assert publisher_normalized("Public Law 104–121") == "Public Law 104-121"


def test_the_page_marker_is_stripped_only_where_gpo_printed_one() -> None:
    """EC 4335 carries ``[[Page H816]]`` mid-authority; its neighbours carry none."""
    raw = rendition_text((SECTIONS / "CREC-2016-02-12-pt1-PgH815-4.excerpt.htm").read_bytes(), rendition="htm").text
    assert "[[Page H816]]" in raw

    marked = numbered("CREC-2016-02-12-pt1-PgH815-4")[4335]
    assert "[[Page" not in marked.entry_text
    # The tail the marker sat in front of survived whole, which is the thing
    # that was lost before the rule existed.
    assert marked.committee_names == ("Foreign Affairs",)
    assert marked.legal_authority is not None
    assert marked.legal_authority.endswith("(91 Stat. 1627)")

    # Gated on the marker's own evidence: an entry with no marker is untouched.
    plain = numbered("CREC-2016-02-12-pt1-PgH815-4")[4329]
    assert plain.entry_text.startswith("A letter from the Deputy Director")


# --- each field ------------------------------------------------------------------------


def test_one_record_per_printed_entry_in_printed_order() -> None:
    entries = section("CREC-2016-02-12-pt1-PgH815-4")
    assert [entry.number for entry in entries] == [4329, 4335, 4340, 4350]
    assert {entry.communication_type for entry in entries} == {SECTION_COMMUNICATION_TYPE}
    assert {entry.rule_version for entry in entries} == {RECORD_COMMUNICATION_RULE_VERSION}
    assert {entry.record_package_id for entry in entries} == {"CREC-2016-02-12"}
    assert {entry.record_granule_id for entry in entries} == {"CREC-2016-02-12-pt1-PgH815-4"}
    # The section's own heading and introductory clause are not an entry.
    assert all(entry.entry_text.startswith("A letter from") for entry in entries)


def test_an_entry_that_cites_no_authority_is_null_not_a_failed_rule() -> None:
    entries = numbered("CREC-2008-06-11-pt1-PgH5326-4")
    assert entries[7093].legal_authority is None
    assert entries[7093].report_nature is not None
    assert entries[7093].committee_names == ("Oversight and Government Reform",)
    assert entries[7094].legal_authority == "5 U.S.C. 801(a)(1)(A)"


def test_a_joint_referral_keeps_every_committee_name_whole() -> None:
    """*House Administration* and *Education and the Workforce*, not four fragments."""
    entry = numbered("CREC-2004-06-16-pt1-PgH4278")[8569]
    assert entry.joint_referral is True
    assert entry.committee_names == ("House Administration and Education and the Workforce",)

    three = numbered("CREC-2016-02-12-pt1-PgH815-4")[4350]
    assert three.joint_referral is True
    assert three.committee_names == ("Appropriations", "Transportation and Infrastructure", "Ways and Means")
    assert all("and" not in name.split()[:1] for name in three.committee_names)


def test_a_single_referral_is_not_marked_joint() -> None:
    entry = numbered("CREC-2016-02-12-pt1-PgH815-4")[4329]
    assert entry.joint_referral is False
    assert entry.committee_names == ("Education and the Workforce",)


# --- the split rule, and its refusal ---------------------------------------------------


def test_the_split_rule_finds_the_boundary_the_publisher_used() -> None:
    assert split_from_clause(
        "Deputy Director, Directorate of Cooperative and State Programs, "
        "Occupational Safety and Health Administration, Department of Labor"
    ) == (
        "Deputy Director, Directorate of Cooperative and State Programs",
        "Occupational Safety and Health Administration, Department of Labor",
    )
    # An agency spelled with its head noun first, which a last-word-only rule
    # could not see.
    assert split_from_clause("General Counsel, Department of Transportation") == (
        "General Counsel",
        "Department of Transportation",
    )


@pytest.mark.parametrize(
    "from_clause",
    [
        "Secretary of Defense",  # one group, all role: no boundary to find
        "Assistant Attorney General of the United States",
        "General Counsel, Peace Corps",  # "Corps" is deliberately not a head word
        "General Counsel, Office of Management and Budget",  # "Office" is measured ambiguous
        "Department of Transportation",  # agency first: no official named before it
    ],
)
def test_an_unresolved_split_is_two_nulls_and_never_a_guess(from_clause: str) -> None:
    assert split_from_clause(from_clause) == (None, None)


def test_the_unresolved_rows_keep_the_whole_from_clause_beside_the_nulls() -> None:
    """The contract rule §5.3 depends on this: a NULL beside the sentence, not a guess."""
    entry = numbered("CREC-2016-02-12-pt1-PgH815-4")[4340]
    assert entry.submitting_official is None
    assert entry.submitting_agency is None
    assert entry.split_resolved is False
    assert entry.from_clause == "General Counsel, Peace Corps"
    assert entry.from_clause in entry.entry_text

    no_official = numbered("CREC-2004-06-16-pt1-PgH4278")[8566]
    assert no_official.split_resolved is False
    assert no_official.from_clause == "Office of the District of Columbia Auditor"


def test_the_excluded_head_words_are_excluded_on_purpose() -> None:
    """A guard on the vocabulary itself: adding one of these silently re-splits rows."""
    assert not AGENCY_HEAD_WORDS & {"Office", "Division", "Directorate", "Branch", "Center", "Corps"}
    assert "Department" in AGENCY_HEAD_WORDS


# --- choosing the granules -------------------------------------------------------------


def test_a_day_that_prints_the_section_twice_yields_both_granules() -> None:
    page = json.loads((SECTIONS / "CREC-2004-06-16-granules.excerpt.json").read_text())
    # The publisher's own title, so the constant cannot drift from the bytes.
    assert {record["title"] for record in page["granules"] if record["granuleClass"] == "HOUSE"} == {SECTION_TITLE}
    assert executive_communication_granules(page["granules"]) == (
        "CREC-2004-06-16-pt1-PgH4278",
        "CREC-2004-06-16-pt2-PgH4285",
    )


def test_the_senate_section_with_a_similar_title_is_not_taken() -> None:
    """`EXECUTIVE AND OTHER COMMUNICATIONS` is the Senate's; the class is what separates them."""
    page = json.loads((SECTIONS / "CREC-2004-06-16-granules.excerpt.json").read_text())
    titles = {record["title"] for record in page["granules"] if record["granuleClass"] == "SENATE"}
    assert "EXECUTIVE AND OTHER COMMUNICATIONS" in titles
    assert not {name for name in executive_communication_granules(page["granules"]) if "PgS" in name}


# --- the completeness witness ----------------------------------------------------------


def test_the_contiguity_witness_reports_the_block_and_can_fail() -> None:
    entries = section("CREC-2016-02-12-pt1-PgH815-4")
    witness = contiguity_witness(entries)
    # The fixture keeps four of the granule's 22 entries, so the excerpt is a
    # block with holes -- and the witness names exactly which numbers are gone.
    assert (witness.first, witness.last, witness.count) == (4329, 4350, 4)
    assert witness.strictly_increasing is True
    assert witness.contiguous is False
    assert 4330 in witness.holes and 4335 not in witness.holes
    assert len(witness.holes) == 22 - 4


def test_a_whole_block_is_contiguous_and_an_empty_one_says_nothing() -> None:
    def made(numbers: list[int]) -> list[RecordCommunicationEntry]:
        return [
            RecordCommunicationEntry(
                number=number,
                communication_type=SECTION_COMMUNICATION_TYPE,
                entry_text="A letter from the X, transmitting y; to the Committee on Z.",
                from_clause=None,
                submitting_official=None,
                submitting_agency=None,
                report_nature=None,
                legal_authority=None,
                committee_names=(),
                joint_referral=False,
                rule_version=RECORD_COMMUNICATION_RULE_VERSION,
            )
            for number in numbers
        ]

    whole = contiguity_witness(made([8544, 8545, 8546]))
    assert whole.contiguous is True and whole.holes == ()

    hole = contiguity_witness(made([8544, 8546]))
    assert hole.contiguous is False and hole.holes == (8545,)

    backwards = contiguity_witness(made([8546, 8545, 8544]))
    assert backwards.holes == () and backwards.strictly_increasing is False
    assert backwards.contiguous is False

    empty = contiguity_witness([])
    assert (empty.first, empty.last, empty.count, empty.holes) == (None, None, 0, ())


# --- the rule identity -----------------------------------------------------------------


def test_the_rule_version_is_pinned_and_moves_when_a_pattern_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Derived, not written: the digest has to follow the patterns it digests."""
    from spicy_docs.sources.congress import record_communications as module

    assert RECORD_COMMUNICATION_RULE_VERSION == "record-communication-dceeb0d93d03"

    monkeypatch.setattr(module, "_PURSUANT", re.compile(r",?\s+in\s+accordance\s+with\s+", re.IGNORECASE))
    assert module._rule_version() != RECORD_COMMUNICATION_RULE_VERSION.removeprefix("record-communication-")


def test_the_rule_version_moves_when_the_vocabulary_or_the_split_policy_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spicy_docs.sources.congress import record_communications as module

    pinned = RECORD_COMMUNICATION_RULE_VERSION.removeprefix("record-communication-")

    monkeypatch.setattr(module, "AGENCY_HEAD_WORDS", AGENCY_HEAD_WORDS | {"Office"})
    assert module._rule_version() != pinned
    monkeypatch.undo()

    # The digest cannot see inside `split_from_clause`, so the hand-moved
    # policy version is what covers a change to its reader.
    monkeypatch.setattr(module, "SPLIT_POLICY_VERSION", "003")
    assert module._rule_version() != pinned


def test_text_that_is_not_text_refuses() -> None:
    with pytest.raises(RecordCommunicationError):
        parse_record_communications(b"<pre>4329. A letter from the X</pre>")  # type: ignore[arg-type]


def test_an_acquired_granule_body_carries_its_own_locator_onto_every_row() -> None:
    """The production seam: `acquire_granule`'s result read through `extraction.body_text`."""

    @dataclass(frozen=True)
    class _Package:
        package_id: str

    @dataclass(frozen=True)
    class _Identity:
        package: _Package
        granule_id: str

    @dataclass(frozen=True)
    class _Rendition:
        media_type: str
        byte_size: int

    @dataclass(frozen=True)
    class _Body:
        format: str
        body: _Rendition
        body_capture: CapturedBodyResponse
        identity: _Identity

    capture = CapturedBodyResponse(
        requested_url="https://www.govinfo.gov/content/pkg/CREC-2016-02-12/html/CREC-2016-02-12-pt1-PgH815-4.htm",
        resolved_url="https://www.govinfo.gov/content/pkg/CREC-2016-02-12/html/CREC-2016-02-12-pt1-PgH815-4.htm",
        status_code=200,
        content_type="text/html",
        body=(SECTIONS / "CREC-2016-02-12-pt1-PgH815-4.excerpt.htm").read_bytes(),
        observed_at="2026-09-20T00:00:00Z",
    )
    body = _Body(
        format="htm",
        body=_Rendition(media_type="text/html", byte_size=capture.byte_size),
        body_capture=capture,
        identity=_Identity(package=_Package("CREC-2016-02-12"), granule_id="CREC-2016-02-12-pt1-PgH815-4"),
    )
    entries = parse_granule_body(body)
    assert [entry.number for entry in entries] == [4329, 4335, 4340, 4350]
    assert {entry.record_package_id for entry in entries} == {"CREC-2016-02-12"}
    assert {entry.record_granule_id for entry in entries} == {"CREC-2016-02-12-pt1-PgH815-4"}
