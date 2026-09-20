"""The PDF-family rollup's rules, and the sidecar the report is written from.

The measurement's numbers are only as good as its rules, and two of those rules
were wrong until the sample corrected them: ``bill_number`` read the U.S.
Reports cite ``600 U. S. 183`` as Senate bill ``S. 183`` and the GPO running
head ``HR974`` as a House bill. Both corrections are pinned here, because a
rule that widens again would raise a presence rate rather than fail anything.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.analysis.pdf_family_rollup import (
    JOIN_KEY_RULES,
    STRUCTURE_RULES,
    compact,
    index_text,
    measure_keys,
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
    sidecar = json.loads(SIDECAR.read_text())
    families = sidecar["families"]

    # CBO: blocked, no document read at all.
    assert families["cbo"]["presence"]["documents_read"] == 0
    # CRS: every bill the prints discuss is already in the index.
    assert families["crs"]["presence"]["bill_number"]["distinct_values_beyond_index"] == 0
    # The activity reports are the densest join surface measured.
    assert families["house_activity"]["presence"]["bill_number"]["distinct_values_beyond_index"] > 900
    # No print in any family states a bioguide id.
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


def test_compact_keeps_the_summary_and_drops_the_pages() -> None:
    report = {
        "families": {
            "x": {
                "documents": [
                    {
                        "join_keys": {"bill_number": {"count": 1}, "rin": {"count": 0}},
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
    assert list(document["structure"]) == ["recommendation_list"]
