"""The MODS recheck's readings, and the sidecar the report is written from.

The rollup's "beyond the index" figures were compared against GovInfo's
`published` listing row rather than against the package MODS, and the whole
correction rests on two things being right: which sampled documents GovInfo
serves, and what a MODS actually states about one. Both are pinned here, with
the MODS shapes written as the publisher spells them -- a widened reading would
otherwise silently shrink the surviving yield instead of failing anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.sources.govinfo.mods import parse_govinfo_mods
from tools.analysis.pdf_yield_mods_recheck import (
    DOCUMENT_REFERENCE_ELEMENTS,
    MODS_KINDS,
    GovInfoDocument,
    compare_document,
    element_census,
    mods_facts,
)

SIDECAR = Path(__file__).resolve().parents[1] / "docs/research/pdf-yield-mods-recheck-2026-09-20.json"

#: One package MODS in miniature, spelled as GovInfo spells it: every element
#: this tool reads, with the attribute names and nesting measured on
#: CRPT-118hrpt968 and BUDGET-2027-APP.
MODS = b"""<?xml version="1.0" encoding="UTF-8"?>
<mods xmlns="http://www.loc.gov/mods/v3">
  <extension>
    <accessId>CRPT-118hrpt968</accessId>
    <collectionCode>CRPT</collectionCode>
    <bill congress="118" context="PRIMARY" number="1093" type="HR"/>
    <bill congress="118" context="OTHER" number="21" type="HCONRES"/>
    <bill congress="117" number="5376" type="HR"/>
    <law congress="107" isPrivate="false" number="228"/>
    <law congress="110" isPrivate="true" number="4"/>
    <USCode title="5"><section detail="(a)(1)(B)" number="57a"/><chapter number="8"/></USCode>
    <cfr title="10"><part number="830"/></cfr>
    <statuteAtLarge volume="60"><pages pages="812"/></statuteAtLarge>
    <rin number="0584-AE88"/>
    <congCommittee authorityId="hsif00" chamber="H" congress="119" type="S">
      <name type="authority-standard">Committee on Energy and Commerce</name>
    </congCommittee>
    <congMember bioGuideId="M001157" chamber="H" congress="119" role="SUBMITTEDBY" state="TX">
      <name type="parsed">Mr. McCaul</name>
    </congMember>
    <congReport congress="118" number="52" type="H"/>
    <field name="Fiscal Year">2026</field>
  </extension>
</mods>
"""


@pytest.fixture(scope="module")
def facts() -> dict:
    return mods_facts(MODS)


def test_the_bill_element_reads_as_both_a_natural_key_and_a_congress_blind_key(facts: dict) -> None:
    """The print rule captures no Congress, so both spellings of the key are needed."""
    assert facts["stated"]["bill_number"] == ["HCONRES21", "HR1093", "HR5376"]
    assert facts["bill_natural_keys"] == ["117-hr-5376", "118-hconres-21", "118-hr-1093"]


def test_a_private_law_is_not_read_as_a_public_one(facts: dict) -> None:
    """``isPrivate`` is the only thing that separates them, and it is a string."""
    assert facts["stated"]["public_law"] == ["107-228", "110-4"]
    assert facts["law_natural_keys"] == ["107-public-228", "110-private-4"]


def test_a_code_section_a_chapter_and_a_cfr_part_each_keep_their_own_key(facts: dict) -> None:
    """A chapter cite has no counterpart the print rule can produce, so it must not
    collapse onto the section's key and be read as already stated."""
    assert facts["stated"]["usc_section"] == ["5USC57A", "5USCCHAPTER8"]
    assert facts["stated"]["cfr_section"] == ["10CFR830"]
    assert facts["stated"]["statutes_at_large"] == ["60-812"]
    assert facts["stated"]["rin"] == ["RIN0584AE88"]


def test_the_mods_states_a_committee_system_code_and_a_member_bioguide_id(facts: dict) -> None:
    """Both are hosted-table keys already; neither needs a crosswalk or an extractor."""
    assert facts["stated"]["committee_name"] == ["hsif00"]
    assert facts["stated"]["bioguide_id"] == ["M001157"]


def test_a_member_without_a_bioguide_id_is_not_invented(facts: dict) -> None:
    """One of the eight sampled activity reports states exactly this shape."""
    without = MODS.replace(b'<congMember bioGuideId="M001157" ', b"<congMember ")
    assert mods_facts(without)["stated"]["bioguide_id"] == []


def test_the_document_references_are_read_as_congress_type_number(facts: dict) -> None:
    assert facts["document_references"] == {"congReport": ["118-H-52"]}
    assert set(DOCUMENT_REFERENCE_ELEMENTS) >= {"congReport", "congDoc", "congHearing", "congSerial"}


def test_the_element_census_reports_paths_rather_than_a_guessed_vocabulary() -> None:
    """Which kinds a collection states is measured from the bytes, never assumed."""
    census = element_census(parse_govinfo_mods(MODS).package.element)

    assert census["mods/extension/bill"] == 3
    assert census["mods/extension/USCode/section"] == 1
    assert census["mods/extension/congCommittee/name"] == 1


def test_a_key_the_mods_states_is_not_counted_as_print_only(facts: dict) -> None:
    """The owner's rule, in one case: the print repeats what the MODS already states."""
    printed = {"bill_number": ["HR1093"], "public_law": ["107-228"], "usc_section": ["5USC57A"]}
    compared = compare_document(printed, facts)

    assert compared["bill_number"]["print_only"] == []
    assert compared["public_law"]["print_only"] == []
    assert compared["usc_section"]["print_only"] == []
    # What the index knows that the capped read did not see is its own column.
    assert compared["bill_number"]["mods_only"] == 2


def test_a_key_the_mods_lacks_survives_as_yield(facts: dict) -> None:
    compared = compare_document({"bill_number": ["HR9999"], "gao_product_id": ["GAO26109302"]}, facts)

    assert compared["bill_number"]["print_only"] == ["HR9999"]
    assert compared["gao_product_id"]["print_only"] == ["GAO26109302"]
    assert compared["gao_product_id"]["mods_states_this_kind"] is False


def test_a_printed_committee_is_compared_as_a_resolved_system_code(facts: dict) -> None:
    """Both sides are system codes: the MODS states one, the print's candidate is settled."""
    compared = compare_document({"committee_name": ["COMMITTEEONENERGYANDCOMMERCE", "COMMITTEEONAGRICULTURE"]}, facts)

    assert compared["committee_name"]["print_only"] == ["hsag00"]
    assert compared["committee_name"]["intersection"] == 1


def test_a_fiscal_year_compares_on_the_year_not_the_spelling(facts: dict) -> None:
    """``FY2026`` and ``FISCALYEAR2026`` are two print keys for one year."""
    compared = compare_document({"fiscal_year": ["FY2026", "FISCALYEAR2026", "FY2030"]}, facts)

    assert compared["fiscal_year"]["print_only"] == ["2030"]


@pytest.mark.parametrize(
    ("package_id", "granule_id", "expected"),
    [
        ("CRPT-118hrpt968", None, "https://api.govinfo.gov/packages/CRPT-118hrpt968/mods"),
        # Neither collection is in ``bodies.py``'s package-id grammar, so the
        # locator falls back to the published route shape and identity is
        # proved from the MODS's own accessId instead.
        ("BUDGET-2027-APP", None, "https://api.govinfo.gov/packages/BUDGET-2027-APP/mods"),
        (
            "GPO-CDOC-119sdoc6",
            "GPO-CDOC-119sdoc6-1",
            "https://api.govinfo.gov/packages/GPO-CDOC-119sdoc6/granules/GPO-CDOC-119sdoc6-1/mods",
        ),
    ],
)
def test_the_mods_locator_is_the_repositorys_own_where_the_grammar_reaches(
    package_id: str, granule_id: str | None, expected: str
) -> None:
    document = GovInfoDocument("f", "id", package_id, granule_id, "https://www.govinfo.gov/")

    assert document.mods_url == expected


def test_the_collection_is_read_apart_from_the_gpo_reprints() -> None:
    """``GPO-CDOC-119sdoc3`` is a GPO-collection reprint, not a CDOC package."""
    assert GovInfoDocument("f", "i", "GPO-CDOC-119sdoc3", None, "u").collection == "GPO-CDOC"
    assert GovInfoDocument("f", "i", "CRPT-118hrpt968", None, "u").collection == "CRPT"
    assert GovInfoDocument("f", "i", "BUDGET-2027-APP", None, "u").collection == "BUDGET"


def test_the_committed_sidecar_was_written_by_these_readings() -> None:
    """A report drifting from the code it cites is the failure this prevents."""
    sidecar = json.loads(SIDECAR.read_text())

    assert sidecar["mods_kinds"] == sorted(MODS_KINDS)
    assert sidecar["supersedes"] == "docs/research/pdf-family-rollup-yield-2026-09-20.json"
    assert sorted(sidecar["families"]) == ["budget", "house_activity", "senate_secretary"]


def test_the_committed_sidecar_states_the_number_the_correction_turns_on() -> None:
    """883 distinct bills and 75 laws "the index does not state" are both zero."""
    sidecar = json.loads(SIDECAR.read_text())
    capped = sidecar["families"]["house_activity"]["restated"]
    uncapped = sidecar["uncapped"]["restated"]["house_activity"]

    assert capped["bill_number"]["print_distinct_values"] == 883
    assert capped["bill_number"]["print_only_distinct_values"] == 0
    assert capped["public_law"]["print_distinct_values"] == 75
    assert capped["public_law"]["print_only_distinct_values"] == 0
    # And it is not an artifact of the rollup's 60-page cap: every page, same answer.
    assert sidecar["uncapped"]["pages_read"]["house_activity"] == 1249
    assert uncapped["bill_number"]["print_distinct_values"] == 1406
    assert uncapped["bill_number"]["print_only_distinct_values"] == 0
    assert uncapped["public_law"]["print_only_distinct_values"] == 1


def test_the_committed_sidecar_states_what_survives_as_pdf_only_value() -> None:
    sidecar = json.loads(SIDECAR.read_text())
    activity = sidecar["uncapped"]["restated"]["house_activity"]
    budget = sidecar["uncapped"]["restated"]["budget"]

    # The budget volumes, not the activity reports, are the citation family.
    assert budget["public_law"]["print_only_distinct_values"] == 504
    # What the activity-report print still holds that no MODS states.
    assert activity["rin"]["print_only_distinct_values"] == 87
    assert activity["docket_number"]["print_only_distinct_values"] == 38
    assert activity["committee_name"]["print_only_distinct_values"] == 27
    assert activity["rin"]["mods_states_this_kind"] is False
    assert activity["docket_number"]["mods_states_this_kind"] is False


def test_the_committed_sidecar_states_which_kinds_each_collection_carries() -> None:
    """Per-record counts, because one record stating a kind is not a collection property."""
    stated = json.loads(SIDECAR.read_text())["collection_kinds_stated"]

    assert stated["CRPT"]["records"] == 8
    assert stated["CRPT"]["bill_number"] == 8
    assert stated["CRPT"]["bioguide_id"] == 7, "one sampled report states a congMember with no bioGuideId"
    assert stated["CRPT"]["cfr_section"] == 0
    assert stated["GPO-CDOC"]["bill_number"] == 0
    assert stated["BUDGET"]["committee_name"] == 0


def test_the_committed_sidecar_carries_no_per_document_key_lists() -> None:
    """The full sets are receipt-sized; the repository keeps the counts and a sample."""
    sidecar = json.loads(SIDECAR.read_text())
    cells = [
        cell
        for family in sidecar["families"].values()
        for document in family["documents"]
        for cell in (document.get("comparison") or {}).values()
    ]

    assert cells, "the sidecar states no document it compared"
    assert all(isinstance(cell["print_distinct"], int) for cell in cells)
    assert all("mods_values" not in cell for cell in cells)
    assert all(len(cell["print_only"]) <= 12 for cell in cells)
