"""The budget_volume contract, pinned on two of the eight retained volumes.

Four things are asserted here and nowhere else:

1. **The fixture is the measurement's own text.** Each ``.txt`` is the
   *every-page* extract the MODS re-check's ``uncapped`` phase read, rebuilt
   from the same retained PDF blob, and its digest is the one the fixture's
   provenance sidecar states.
2. **The contract reproduces a published per-document row.** For
   ``BUDGET-2026-MSR`` -- 16 pages, so the re-check's 60-page cap never bit --
   the shaped rows reproduce ``recheck.json``'s own print-only counts exactly.
   For ``BUDGET-2027-BUD`` the cap *did* bite, and the two published rows
   disagree; the test asserts both numbers and names which is right.
3. **A printed bill on a budget volume is NULL, not ``false``.** A BUDGET
   summary states no Congress, so the print's bill key and the MODS's are not
   the same shape and no comparison is possible.
4. **The two keyed records state the fields the contract reads from them**,
   including the fiscal year, which the package id and the MODS state
   independently and which this holds equal.

The fixtures were built from retained bytes only; the three package summaries
are the only acquisition, receipt
``corpora/supply-2026-09-02/receipts/budget-volumes-2026-09-20/``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from spicy_docs.interpretation.citations import CITATION_RULE_SET_VERSION, find_citations
from spicy_docs.schemas.budget_volume_tables import (
    BUDGET_VOLUME,
    budget_index_stated_keys,
    congress_blind_bill_keys,
    shape_budget_volume,
)
from spicy_docs.schemas.document_citation_tables import (
    document_provenance,
    index_stated_bill_pairs,
    index_stated_keys,
    shape_document_citation,
)
from spicy_docs.sources.govinfo.bodies import (
    package_mods_locator,
    package_summary_locator,
    parse_package_id,
    validate_package_mods,
    validate_package_summary,
)

FIXTURES = Path(__file__).parent / "fixtures" / "budget_volumes"

#: 16 pages of 16, so the re-check's 60-page cap never bit and its capped and
#: uncapped rows are the same row. Its MODS states the one public law and the
#: one Code section the print names: the ``stated_by_index = true`` side.
WHOLE = "BUDGET-2026-MSR"
#: 92 pages of 92. The capped read saw two public laws; the volume names three,
#: and its MODS states no ``<law>`` at all, so all three are print-only.
BEYOND_CAP = "BUDGET-2027-BUD"
VOLUMES = (WHOLE, BEYOND_CAP)


@dataclass(frozen=True, slots=True)
class FixtureBody:
    """A ``BodyText``'s three facts, rebuilt from the retained text and its page map.

    Structural for the same reason ``tests/test_citations.py``'s is: what
    ``rendition_text`` would produce for these bytes is what the re-check
    already produced, and re-running PyMuPDF here would make this a PDF-library
    test. ``test_the_retained_text_is_the_one_the_measurement_read`` holds the
    two equal.
    """

    text: str
    pages: tuple[str, ...]
    rendition: str = "pdf"
    derivation: str = "pdf-extraction-gpo-normalized"


def provenance(package: str) -> dict:
    return json.loads((FIXTURES / f"{package}.json").read_text())


def body_for(package: str) -> FixtureBody:
    """The retained normalized text, split back into pages by the recorded lengths."""
    text = (FIXTURES / f"{package}.txt").read_text()
    pages: list[str] = []
    cursor = 0
    for length in provenance(package)["page_lengths"]:
        pages.append(text[cursor : cursor + length])
        cursor += length + 1
    return FixtureBody(text=text, pages=tuple(pages))


def summary_for(package: str):
    return validate_package_summary(
        (FIXTURES / f"summary-{package}.json").read_bytes(),
        package=package,
        final_url=package_summary_locator(package),
        max_bytes=1_000_000,
    )


def mods_for(package: str):
    return validate_package_mods(
        (FIXTURES / f"mods-{package}.xml").read_bytes(),
        package=package,
        final_url=package_mods_locator(package),
        max_bytes=1_000_000,
    )


def citations_for(package: str):
    """Every cite the shared rules find, with **no** Congress supplied.

    Deliberate and measured: a BUDGET summary states none, so passing one
    would be inventing the Congress every printed bill belongs to.
    """
    body = body_for(package)
    return find_citations(body.text, pages=body.pages, congress=summary_for(package).identity.congress)


def rows_for(package: str):
    """The document row and its citation rows, as a caller would shape them."""
    body, summary, mods = body_for(package), summary_for(package), mods_for(package)
    findings = citations_for(package)
    stated = budget_index_stated_keys(mods)
    provenance_record = document_provenance(body, document_key=package, document_kind=BUDGET_VOLUME)
    document = shape_budget_volume(summary, mods, body, findings, rule_set_version=CITATION_RULE_SET_VERSION)
    rows = [shape_document_citation(finding, provenance_record, stated_by_index=stated) for finding in findings]
    return document, rows, findings, mods


# ---------------------------------------------------------------------------
# The fixtures are the measurement's own bytes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("package", VOLUMES)
def test_the_retained_text_is_the_one_the_measurement_read(package: str) -> None:
    recorded = provenance(package)
    body = body_for(package)
    assert hashlib.sha256(body.text.encode()).hexdigest() == recorded["text_sha256"]
    assert "\n".join(body.pages) == body.text
    assert len(body.pages) == recorded["pages_read"] == recorded["page_count"]
    # Every page, not a capped window: this is what makes the print-only counts
    # below comparable with the re-check's uncapped row.
    assert recorded["page_range"] == [1, recorded["page_count"]]


@pytest.mark.parametrize("package", VOLUMES)
def test_every_span_re_reads_as_its_own_matched_text(package: str) -> None:
    body = body_for(package)
    findings = citations_for(package)
    assert findings
    for finding in findings:
        assert body.text[finding.span_start : finding.span_end] == finding.matched_text


@pytest.mark.parametrize("package", VOLUMES)
def test_the_keyed_records_state_the_fields_the_contract_reads_from_them(package: str) -> None:
    """Page count, title and date are the publisher's, so the row never re-derives them."""
    summary, mods, recorded = summary_for(package), mods_for(package), provenance(package)
    assert summary.collection_code == "GPO"
    assert summary.pages == str(recorded["page_count"])
    assert summary.title
    # The fiscal year, stated twice and held equal: once in the package id the
    # grammar parses and once as the MODS's own labelled field. A single source
    # would agree with itself whatever it said.
    assert mods.fiscal_year == summary.identity.fiscal_year
    assert mods.fiscal_year == package.split("-")[1]
    # And it is not the year the volume was issued, which is the mistake this
    # column exists to make impossible to publish: BUDGET-2026-MSR was issued
    # in 2025 and BUDGET-2027-BUD in 2026.
    assert summary.date_issued is not None
    assert mods.fiscal_year != summary.date_issued[:4]


def test_the_collection_is_not_the_collection_code_these_records_state() -> None:
    """The fact the grammar widening turns on, asserted on real publisher bytes."""
    assert parse_package_id(WHOLE).collection == "BUDGET"
    assert summary_for(WHOLE).collection_code == "GPO"
    assert mods_for(WHOLE).collection_code == "GPO"


# ---------------------------------------------------------------------------
# The contract reproduces a published per-document row.
# ---------------------------------------------------------------------------


def test_the_whole_volume_reproduces_the_rechecks_own_print_only_counts() -> None:
    """``BUDGET-2026-MSR``: 16 pages, so capped and uncapped are one row.

    ``recheck.json``'s row for this volume states 1 printed public law of
    which 0 is print-only, and 1 printed U.S. Code section of which 0 is
    print-only -- its MODS states both. The shaped row reproduces all four.
    """
    document, rows, findings, mods = rows_for(WHOLE)
    assert document["pages_read"] == "16"
    assert document["stated_page_count"] == "16"
    assert document["pages_capped"] == "false"

    assert document["distinct_laws"] == "1"
    assert document["distinct_laws_beyond_index"] == "0"
    assert document["distinct_usc_sections"] == "1"
    assert document["distinct_usc_sections_beyond_index"] == "0"
    assert document["distinct_cfr_parts"] == "0"
    assert document["distinct_statutes"] == "0"

    # The index side, read off the MODS rather than off the row under test.
    stated = index_stated_keys(mods)
    assert {f.target_key for f in findings if f.kind == "public_law"} == stated["public_law"]
    assert {f.target_key for f in findings if f.kind == "usc_section"} == stated["usc_section"]
    # And the per-row column carries the same comparison as the summary column.
    laws = [row for row in rows if row["cite_kind"] == "public_law"]
    assert laws and all(row["stated_by_index"] == "true" for row in laws)


def test_the_capped_read_understated_this_volume_and_the_whole_read_is_the_right_one() -> None:
    """``BUDGET-2027-BUD``: the two published rows disagree, and by exactly the cap.

    ``recheck.json`` states 2 printed public laws, both print-only;
    ``uncapped.json`` states 3, all three print-only. **The uncapped row is the
    right one for this text**, and the reason is not a judgement call: the
    re-check read 60 pages of a 92-page volume, and a capped read can only
    understate what a print names -- the third law is printed past page 60.
    The shaped row states 3, and ``pages_read == stated_page_count`` is what
    says the count is the volume's rather than a window's.
    """
    document, rows, _findings, mods = rows_for(BEYOND_CAP)
    assert document["pages_read"] == document["stated_page_count"] == "92"
    assert document["pages_capped"] == "false"

    assert document["distinct_laws"] == "3"
    assert document["distinct_laws_beyond_index"] == "3"
    # The MODS states no <law> at all, which is why every one is print-only --
    # and why each row carries `false` (compared, and absent) rather than NULL.
    assert mods.laws == ()
    assert index_stated_keys(mods)["public_law"] == frozenset()
    laws = [row for row in rows if row["cite_kind"] == "public_law"]
    assert {row["target_key"] for row in laws} == {"119-public-21", "119-public-37", "119-public-75"}
    assert all(row["stated_by_index"] == "false" for row in laws)

    # The capped number, kept here so the difference is a stated fact rather
    # than a silent one: a 60-page read of this volume names two of the three.
    capped = {f.target_key for f in find_citations("\n".join(body_for(BEYOND_CAP).pages[:60]), kinds=("public_law",))}
    assert len(capped) == 2
    assert capped < {row["target_key"] for row in laws}


# ---------------------------------------------------------------------------
# What cannot be compared says so.
# ---------------------------------------------------------------------------


def test_a_budget_volume_states_no_congress_so_a_printed_bill_is_not_comparable() -> None:
    """NULL, not ``false``: the comparison the print side cannot spell.

    ``BUDGET-2027-APP``'s MODS names six bills, so the kind is not absent from
    the family's vocabulary -- it is absent from the *comparison*, because a
    budget volume's summary states no Congress and the print writes none.
    """
    assert summary_for(BEYOND_CAP).identity.congress is None
    assert "bill_number" not in budget_index_stated_keys(mods_for(BEYOND_CAP))
    assert "bill_number" in index_stated_keys(mods_for(BEYOND_CAP))

    provenance_record = document_provenance(body_for(WHOLE), document_key=WHOLE, document_kind=BUDGET_VOLUME)
    (finding,) = find_citations("H.R. 7806", kinds=("bill_number",))
    assert (finding.target_key, finding.target_resolved) == ("HR7806", False)
    row = shape_document_citation(finding, provenance_record, stated_by_index=budget_index_stated_keys(mods_for(WHOLE)))
    assert row["stated_by_index"] is None
    # Under the shared mapping it would have been a `false` the comparison
    # never earned, which is the failure this drop prevents.
    assert (
        shape_document_citation(finding, provenance_record, stated_by_index=index_stated_keys(mods_for(WHOLE)))[
            "stated_by_index"
        ]
        == "false"
    )


def test_the_congress_blind_bill_count_is_published_and_named_for_what_it_is() -> None:
    """The one bill comparison this family supports, held against the re-check's own.

    Neither fixture volume prints a bill -- the ones that do are the 1,340-page
    Appendix and the 158-page Analytical Perspectives, both too large to commit
    -- so the reduction is exercised on a MODS written for the purpose and the
    print side taken from the shared rules, which is what the comparison
    actually joins. ``HR2`` is stated by this index and ``HR3288`` is not, the
    same split the re-check measured across the eight volumes.
    """
    mods = validate_package_mods(
        (
            b'<mods xmlns="http://www.loc.gov/mods/v3"><extension>'
            b"<collectionCode>GPO</collectionCode><accessId>BUDGET-2027-APP</accessId>"
            b'<bill congress="119" type="HR" number="2" context="OTHER"/>'
            b'<bill congress="118" type="HCONRES" number="14" context="OTHER"/>'
            b"</extension></mods>"
        ),
        package="BUDGET-2027-APP",
        final_url=package_mods_locator("BUDGET-2027-APP"),
        max_bytes=100_000,
    )
    # The index side, reduced to meet a print that states no Congress.
    assert index_stated_bill_pairs(mods) == {"hr-2", "hconres-14"}
    assert congress_blind_bill_keys(mods) == {"HR2", "HCONRES14"}

    # And the print side, through the rules the measurement ran, with no
    # Congress supplied -- which is what leaves the key congress-free.
    findings = find_citations("H.R. 2, H. Con. Res. 14 and H.R. 3288", kinds=("bill_number",))
    printed = {finding.target_key for finding in findings}
    assert printed == {"HR2", "HCONRES14", "HR3288"}
    assert all(not finding.target_resolved for finding in findings)
    assert printed - congress_blind_bill_keys(mods) == {"HR3288"}


@pytest.mark.parametrize("package", VOLUMES)
def test_neither_fixture_volume_prints_a_bill_so_both_counts_are_zero(package: str) -> None:
    """Stated rather than left implicit: a zero here is the document, not a gap.

    The family's 6-of-8 congress-blind figure is carried by BUDGET-2027-APP and
    BUDGET-2027-PER, neither of which is committable; these two volumes name no
    bill at all at full page depth, in the re-check's own rows as well.
    """
    document, _rows, findings, _mods = rows_for(package)
    assert [f for f in findings if f.kind == "bill_number"] == []
    assert document["distinct_bills"] == "0"
    assert document["distinct_bills_beyond_index_congress_blind"] == "0"


@pytest.mark.parametrize("package", VOLUMES)
def test_every_citation_row_carries_this_volumes_kind_and_digest(package: str) -> None:
    document, rows, findings, _mods = rows_for(package)
    assert rows
    assert {row["document_kind"] for row in rows} == {"budget_volume"}
    assert {row["document_key"] for row in rows} == {package}
    assert {row["text_sha256"] for row in rows} == {document["text_sha256"]}
    assert document["citation_rows"] == str(len(findings))
    assert document["rule_set_version"] == CITATION_RULE_SET_VERSION
