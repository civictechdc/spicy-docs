"""The PDF-family rollup's rules, and the sidecar the report is written from.

The measurement's numbers are only as good as its rules, and four of those rules
were wrong until the sample and the review corrected them: ``bill_number`` read
the U.S. Reports cite ``600 U. S. 183`` as Senate bill ``S. 183`` and the GPO
running head ``HR974`` as a House bill; ``public_law`` could not read the
Bluebook ``Pub. L. No. 89-136`` at all; ``case_docket_number`` read the ``No.``
inside that same cite as a circuit docket; and ``committee_name`` reported 90
line-wrapped fragments as 90 committees. Every correction is pinned here,
because a rule that widens again raises a presence rate rather than failing
anything.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.analysis.pdf_family_rollup import (
    JOIN_KEY_RULES,
    STRUCTURE_RULES,
    committee_vocabulary,
    compact,
    index_text,
    measure_keys,
    resolve_committee_names,
    spot_check,
)

SIDECAR = Path(__file__).resolve().parents[1] / "docs/research/pdf-family-rollup-yield-2026-09-20.json"


def rule(name: str):
    return next(candidate for candidate in JOIN_KEY_RULES if candidate.name == name)


def test_every_rule_rejects_the_lookalikes_it_names() -> None:
    assert spot_check() == {}


@pytest.mark.parametrize(
    "text",
    ["H.R. 7806", "H.R.\n5509", "S. 3948", "H. Res. 5", "H.J. Res. 45", "HR 7806", "S 394"],
)
def test_the_bill_rule_reads_every_spelling_the_sample_printed(text: str) -> None:
    assert rule("bill_number").compiled().search(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "600 U. S. 183",  # a U.S. Reports page cite, not Senate bill 183
        "603 U.S. 25",
        "HR974",  # a GPO running head, not a House bill
        "S4601",  # a Congressional Record locator
        "STATISTICAL ANALYSIS. 12",
    ],
)
def test_the_bill_rule_rejects_what_the_sample_proved_it_is_not(text: str) -> None:
    assert rule("bill_number").compiled().search(text) is None


def test_a_two_field_index_key_is_readable_whichever_order_it_was_serialized_in() -> None:
    """Key order in a retained record is the serializer's, not the publisher's."""
    publisher_order = {"type": "HR", "number": 7806, "congress": 119, "title": "A bill"}
    sorted_order = {"congress": 119, "number": 7806, "title": "A bill", "type": "HR"}
    for record in (publisher_order, sorted_order):
        found = {
            rule("bill_number").canonical(m) for m in rule("bill_number").compiled_index().findall(index_text(record))
        }
        assert "HR7806" in found


def test_a_key_the_index_already_states_is_not_counted_as_yield() -> None:
    """The owner's first rule, in one case: Congress.gov states the bill, the print repeats it."""
    text = "This report discusses H.R. 7806 and S. 3948, and P.L. 98-369."
    index_row = {
        "id": "IF13314",
        "relatedMaterials": [
            {"congress": 119, "number": 7806, "title": "A bill", "type": "HR"},
            {"congress": 119, "number": 3948, "title": "A bill", "type": "S"},
            {"congress": 98, "number": "98-369", "title": "An act", "type": "PUB"},
        ],
    }
    measured = measure_keys(text, index_row)["join_keys"]

    assert measured["bill_number"]["distinct_count"] == 2
    assert measured["bill_number"]["not_in_index_count"] == 0
    assert measured["public_law"]["not_in_index_count"] == 0


def test_a_key_the_index_lacks_is_counted_as_yield() -> None:
    text = "The Committee reported H.R. 1234 during the 118th Congress."
    index_row = {"packageId": "CRPT-118hrpt970", "title": "REPORT ON THE ACTIVITIES OF THE COMMITTEE"}
    measured = measure_keys(text, index_row)["join_keys"]

    assert measured["bill_number"]["not_in_index"] == ["HR1234"]


def test_the_public_law_rule_reads_the_two_publishers_spellings_as_one_key() -> None:
    law = rule("public_law")
    assert law.canonical("P.L. 98-369") == law.canonical("Public Law 98–369") == "98-369"
    stated = {law.canonical(m) for m in law.compiled_index().findall("PUB 98-369")}
    assert stated == {"98-369"}


@pytest.mark.parametrize(
    "text",
    ["Public Law 98-369", "P.L. 98-369", "PL 98-369", "Pub. L. No. 89-136", "Pub. L. 119-21"],
)
def test_the_public_law_rule_reads_the_bluebook_spelling_too(text: str) -> None:
    """The first rule could not, and so missed 35 occurrences across the sample."""
    assert rule("public_law").compiled().search(text) is not None


def test_a_bluebook_law_cite_is_not_read_as_a_case_docket() -> None:
    """``Pub. L. No. 89-136`` put a circuit docket in the GAO row until this rule moved."""
    assert rule("case_docket_number").compiled().search("Pub. L. No. 89-136") is None
    assert rule("case_docket_number").compiled().search("No. 24-1260") is not None


def test_a_month_is_not_a_committee() -> None:
    assert rule("committee_name").compiled().search("Committee on June 5, 2024") is None
    assert rule("committee_name").compiled().search("Committee on Agriculture") is not None


def test_the_committee_vocabulary_comes_from_the_pinned_chamber_rosters() -> None:
    vocabulary = dict(committee_vocabulary())
    assert vocabulary["COMMITTEEONAGRICULTURE"] == "hsag00"
    assert vocabulary["COMMITTEEONWAYSANDMEANS"] == "hswm00"
    assert any(code.startswith("ss") for code in vocabulary.values()), "the Senate roster should contribute too"


def test_a_wrapped_or_run_on_committee_name_resolves_to_one_system_code() -> None:
    """The failure this fixes: 90 candidates reported as 90 committees.

    The resolver is the library's now, and this measurement supplies the
    vocabulary its own pinned rosters state.  ``COMMITTEEONAG`` is no longer
    among the resolved: the sibling route refuses a fragment shorter than
    ``Committee on`` plus four characters, because below that it takes
    whichever single sibling happens to share the prefix.  The three system
    codes are unchanged, since the prints that wrap a name also spell it out.
    """
    resolved = resolve_committee_names(
        [
            "COMMITTEEONAGRICULTURE",
            "COMMITTEEONAGRI",  # a line wrap; ambiguous against the roster alone
            "COMMITTEEONAG",  # too short for the sibling route to settle
            "COMMITTEEONWAYSANDMEANSREPUB",  # runs into following prose
            "COMMITTEEONNATURALRE",
            "COMMITTEEONTHEPRESENTDANGER",  # not a congressional committee
        ],
        committee_vocabulary(),
    )
    codes = {name: outcome.system_code for name, outcome in resolved.items()}

    assert codes["COMMITTEEONAGRICULTURE"] == "hsag00"
    assert codes["COMMITTEEONAGRI"] == "hsag00"
    assert codes["COMMITTEEONAG"] is None
    assert codes["COMMITTEEONWAYSANDMEANSREPUB"] == "hswm00"
    assert codes["COMMITTEEONNATURALRE"] == "hsii00"
    assert codes["COMMITTEEONTHEPRESENTDANGER"] is None
    assert len({code for code in codes.values() if code}) == 3
    assert resolved["COMMITTEEONAGRI"].route == "sibling_prefix"


def test_an_ambiguous_fragment_alone_stays_unresolved() -> None:
    """Without a sibling in the same document, ``Committee on Agri`` names two chambers' committees."""
    settled = resolve_committee_names(["COMMITTEEONAGRI"], committee_vocabulary())
    assert settled["COMMITTEEONAGRI"].system_code is None


def test_a_senate_committee_is_not_resolved_to_the_house_one_it_starts_with() -> None:
    """Two measured cases where the run-on route published the wrong chamber's code.

    Found in the budget and GAO samples: the Senate's Homeland Security and
    Governmental Affairs starts with the House's Homeland Security, and the
    Senate's Small Business and Entrepreneurship with the House's Small
    Business.  The run-on route read both as the House committee with prose
    after it.
    """
    settled = resolve_committee_names(
        [
            "COMMITTEEONHOMELANDSECURITYANDGOVERNMENTALAFFAIRS",
            "COMMITTEEONSMALLBUSINESSANDENTREPRENEURSHIP",
        ],
        committee_vocabulary(),
    )
    assert [outcome.system_code for outcome in settled.values()] == [None, None]


def test_the_recommendation_marker_reads_the_publishers_heading_not_a_verb() -> None:
    """``We recommend that`` alone found GAO recommendations in 1 report of 8."""
    marker = dict(STRUCTURE_RULES)["recommendation_list"]
    for heading in ("Recommendations for Executive Action", "Recommendation 3", "GAO is making 4 recommendations"):
        assert re.search(marker, heading) is not None


def test_the_committed_sidecar_was_written_by_these_rules() -> None:
    """A report drifting from the code it cites is the failure this prevents."""
    sidecar = json.loads(SIDECAR.read_text())

    assert sidecar["spot_check_failures"] == {}
    assert [entry["name"] for entry in sidecar["join_key_rules"]] == [entry.name for entry in JOIN_KEY_RULES]
    assert [entry["pattern"] for entry in sidecar["join_key_rules"]] == [entry.pattern for entry in JOIN_KEY_RULES]


def test_the_committed_sidecar_states_the_numbers_the_report_leads_with() -> None:
    """The sidecar as run, not as it should have been.

    ``distinct_values_beyond_index`` for the activity reports is **883 and
    wrong**: it was measured against the ``published`` listing row rather than
    the package MODS, and
    ``docs/research/pdf-yield-mods-recheck-2026-09-20.md`` puts the real
    print-only figure at 0 of 1,406. The number is pinned here because the
    sidecar is a retained artifact of a dated run and this test's job is to
    hold the committed file to what that run produced -- regenerating it would
    contradict the prose the report quotes from it. The corrected claim lives
    in the report's own correction section and in ``docs/tables.md``.
    """
    sidecar = json.loads(SIDECAR.read_text())
    families = sidecar["families"]

    # CBO: blocked, no document read at all.
    assert families["cbo"]["presence"]["documents_read"] == 0
    # CRS: every bill the prints discuss is already in the index -- the one
    # family this measurement compared against the right record.
    assert families["crs"]["presence"]["bill_number"]["distinct_values_beyond_index"] == 0
    # The row count and the distinct-key count are different numbers, which is
    # the distinction the report makes correctly whatever it compared against.
    activity = families["house_activity"]["presence"]["bill_number"]
    assert activity["distinct_values_beyond_index"] == 883
    assert activity["link_rows_beyond_index"] == 940
    # Committee names are reported as resolved system codes, never as candidates.
    assert len(families["house_activity"]["presence"]["committee_system_codes"]) == 20
    # No print in any family states a bioguide id. The *index* does: a CRPT
    # MODS names the submitting member's, on seven of eight sampled reports.
    assert all(family["presence"].get("bioguide_id", {}).get("documents", 0) == 0 for family in families.values())


def test_the_committed_sidecar_carries_no_per_page_detail() -> None:
    """The per-page rows are receipt-sized; the repository keeps the summary."""
    sidecar = json.loads(SIDECAR.read_text())
    read = [
        document
        for family in sidecar["families"].values()
        for document in family["documents"]
        if document.get("extraction")
    ]

    assert read, "the sidecar states no document it read"
    assert all("page_detail" not in document["extraction"] for document in read)
    assert all("pages_read" in document["extraction"] for document in read)
    # The timer measures the work, so no page can cost exactly nothing.
    assert all(document["extraction"]["slowest_page_seconds"] > 0 for document in read)


def test_the_capture_witness_compares_the_blocks_against_the_page_text() -> None:
    """``source_sha256_matches`` compared a digest to itself and would pass on anything."""
    sidecar = json.loads(SIDECAR.read_text())
    captures = [
        document["capture"]
        for family in sidecar["families"].values()
        for document in family["documents"]
        if document.get("capture")
    ]

    assert len(captures) == 9
    assert all(capture["round_trip_matches"] for capture in captures)
    assert all("source_sha256_matches" not in capture for capture in captures)


def test_compact_keeps_the_summary_and_drops_the_pages() -> None:
    report = {
        "families": {
            "x": {
                "documents": [
                    {
                        "join_keys": {
                            "bill_number": {"count": 1, "distinct": ["HR1"] * 20, "not_in_index": ["HR1"] * 20},
                            "rin": {"count": 0, "distinct": [], "not_in_index": []},
                        },
                        "structure": {"recommendation_list": 2, "cost_table_marker": 0},
                        "extraction": {
                            "pages_read": 2,
                            "page_detail": [
                                {"characters": 10, "blocks": 2, "seconds": 0.1, "tables": [{"rows": 3, "columns": 4}]},
                                {"characters": 5, "blocks": 1, "seconds": 0.2, "tables": []},
                            ],
                        },
                    }
                ]
            }
        }
    }
    document = compact(report)["families"]["x"]["documents"][0]

    assert "page_detail" not in document["extraction"]
    assert document["extraction"]["characters"] == 15
    assert document["extraction"]["tables"] == 1
    assert document["extraction"]["table_shapes"] == [[3, 4]]
    assert document["extraction"]["slowest_page_seconds"] == 0.2
    assert list(document["join_keys"]) == ["bill_number"]
    # The full sets feed the family's union; the committed sidecar keeps a sample.
    assert len(document["join_keys"]["bill_number"]["distinct"]) == 12
    assert list(document["structure"]) == ["recommendation_list"]
