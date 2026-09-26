"""An activity report's bills are keyed in the Congress the report says it covers, not the one it was filed in.

The 2026-09-26 drift audit found the eight Senate activity reports in the print-citations window -- reports on the
117th Congress, filed in the 118th -- publishing 1,915 citations and 369 actions against 118th-Congress bills, and
GovInfo's MODS stamping those bills ``118`` too, so ``bills_congress_mismatch`` stayed 0. The fixtures are four of the
40 reports that window holds, rebuilt from retained PDF bytes, and CRPT-118srpt99's reduced MODS
(``fixtures/document_citations/README.md``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.interpretation.bill_actions import find_bill_actions
from spicy_docs.interpretation.citations import CITATION_RULE_SET_VERSION, find_citations
from spicy_docs.schemas.document_citation_tables import (
    GOVINFO_PACKAGE,
    activity_report_stated_keys,
    document_provenance,
    shape_activity_report,
    shape_document_citation,
)
from spicy_docs.sources.govinfo.activity_reports import (
    COVERED_CONGRESS_RULE_VERSION,
    TITLE_CONGRESS,
    CoveredCongress,
    covered_congress,
    ordinal_congress,
)
from spicy_docs.sources.govinfo.bodies import (
    PackageSummary,
    package_mods_locator,
    parse_package_id,
    validate_package_mods,
)

FIXTURES = Path(__file__).parent / "fixtures" / "document_citations"
AUDIT = json.loads((FIXTURES / "print-citations-2026-09-26.json").read_text(encoding="utf-8"))
COVERED = {case["package"]: case for case in AUDIT["covered"]}
SENATE = "CRPT-118srpt99"


@pytest.mark.parametrize("case", AUDIT["covered"], ids=lambda case: case["package"])
def test_each_retained_report_states_the_congress_it_covers(case: dict) -> None:
    """One report per path: two titles, a cover under a silent title, a transmittal letter under both."""
    expected = case["expected"]
    assert covered_congress(case["title"], case["pages"]) == CoveredCongress(
        expected["congress"], expected["source"], (expected["congress"],)
    )


def test_the_filing_header_and_the_roster_heading_are_not_statements_of_coverage() -> None:
    """With its title withheld, CRPT-118srpt99 still reads 117 from its cover.

    Its front matter prints the 118th twice -- the filing header and page II's
    roster of the *current* committee -- so the assertion that neither is read
    would be empty if the pages did not in fact print it.
    """
    pages = COVERED[SENATE]["pages"]
    assert {ordinal_congress(m.group("ordinal")) for m in TITLE_CONGRESS.finditer("\n".join(pages))} == {117, 118}
    assert covered_congress(None, pages) == CoveredCongress(117, "cover", (117,))


def test_a_header_set_apart_from_its_session_is_still_not_read() -> None:
    """CRPT-118srpt3 sets ``REPORT`` between ``118TH CONGRESS`` and ``1st Session``; its cover still reads 117."""
    pages = COVERED["CRPT-118srpt3"]["pages"]
    assert "118TH CONGRESS\nREPORT" in pages[0]
    assert covered_congress(None, pages) == CoveredCongress(117, "cover", (117,))


def test_a_report_that_states_no_congress_is_left_unstated() -> None:
    """The filing header alone is not a statement of coverage, and nothing falls back to it."""
    cover = "118TH CONGRESS\n2d Session\nREPORT\n118–963\nACTIVITY REPORT\nDECEMBER 31, 2024.—Ordered to be printed"
    assert covered_congress("ACTIVITY REPORT OF THE COMMITTEE ON THE JUDICIARY", [cover, "C O N T E N T S"]) == (
        CoveredCongress(None, None, ())
    )


def test_a_source_stating_two_congresses_decides_nothing_and_a_weaker_one_is_not_asked() -> None:
    covered = covered_congress(
        "REPORT FOR THE 117TH CONGRESS AND THE 118TH CONGRESS", ["DURING THE 117TH CONGRESS ordered to be printed"]
    )
    assert covered == CoveredCongress(None, "title", (117, 118))


def test_a_rendition_with_no_page_split_is_read_by_its_title_alone() -> None:
    assert covered_congress("REPORT ON ACTIVITIES DURING THE 118TH CONGRESS", None) == CoveredCongress(
        118, "title", (118,)
    )
    assert covered_congress("ACTIVITY REPORT", None) == CoveredCongress(None, None, ())


@pytest.mark.parametrize(
    ("spelled", "congress"),
    [
        ("117TH", 117),
        ("102d", 102),
        ("ONE HUNDRED SEVENTEENTH", 117),
        ("One Hundred and Seventeenth", 117),
        ("one hundred twenty-first", 121),
        ("ONE HUNDREDTH", 100),
        ("SEVENTY-FIFTH", 75),
    ],
)
def test_an_ordinal_congress_reads_in_every_spelling_a_cover_uses(spelled: str, congress: int) -> None:
    assert ordinal_congress(spelled) == congress


def test_the_index_titles_own_misspelling_reads_and_an_adjective_does_not() -> None:
    """CRPT-118hrpt953's title says ``118TH CONGRESSS``; ``118th Congressional`` is not a Congress."""
    assert (
        covered_congress("REPORT ON THE ACTIVITY of the COMMITTEE ON SMALL BUSINESS 118TH CONGRESSS", None).congress
        == 118
    )
    assert covered_congress("A 118th Congressional Research Service review", None).congress is None


def test_the_covered_congress_rule_version_is_pinned() -> None:
    """A change to the patterns, the page bound or the source order moves this digest, and a host re-reads."""
    assert COVERED_CONGRESS_RULE_VERSION == "96592be9c053"


# ---------------------------------------------------------------------------
# The row: both Congresses kept, the index's disagreement counted.
# ---------------------------------------------------------------------------


class _Body:
    """A ``BodyText``'s three facts, the way ``tests/test_citations.py`` rebuilds one."""

    rendition = "pdf"
    derivation = "pdf-extraction-gpo-normalized"

    def __init__(self, pages: list[str]) -> None:
        self.pages = tuple(pages)
        self.text = "\n".join(pages)


def _senate_report(extra_pages: list[str]):
    """CRPT-118srpt99's front matter and its retained H.R. 5376 sentence, its summary, and its reduced MODS."""
    snippet = next(s for s in AUDIT["bill_snippets"] if s["package"] == SENATE)
    body = _Body([*COVERED[SENATE]["pages"], snippet["text"], *extra_pages])
    identity = parse_package_id(SENATE)
    summary = PackageSummary(
        identity=identity,
        collection_code="CRPT",
        date_issued="2023-09-20",
        last_modified="2024-11-08T14:25:17Z",
        title=COVERED[SENATE]["title"],
        download_links=(),
        pages=str(COVERED[SENATE]["page_count"]),
    )
    mods = validate_package_mods(
        (FIXTURES / f"mods-{SENATE}.xml").read_bytes(),
        package=identity,
        final_url=package_mods_locator(SENATE),
        max_bytes=1_000_000,
    )
    return body, summary, mods


def _row(body, summary, mods, covered):
    findings = find_citations(body.text, pages=body.pages, kinds=("bill_number",), congress=covered.congress)
    provenance = document_provenance(body, document_key=SENATE, document_kind=GOVINFO_PACKAGE)
    stated = activity_report_stated_keys(mods, covered)
    report = shape_activity_report(
        summary, mods, body, findings, covered=covered, rule_set_version=CITATION_RULE_SET_VERSION
    )
    citations = [shape_document_citation(f, provenance, stated_by_index=stated) for f in findings]
    return findings, report, citations


def test_a_senate_report_keys_its_bills_in_the_congress_it_covers_and_counts_the_index_disagreeing() -> None:
    """H.R. 5376 is the 117th's reconciliation act, and the MODS's ``118`` is what the mismatch column now shows."""
    body, summary, mods = _senate_report([])
    assert {bill.number for bill in mods.bills if bill.congress == 118 and bill.bill_type.upper() == "HR"} >= {"5376"}
    covered = covered_congress(summary.title, body.pages)
    findings, report, citations = _row(body, summary, mods, covered)

    hr5376 = [f for f in findings if f.matched_text == "H.R. 5376"]
    assert [(f.target_key, f.target_resolved) for f in hr5376] == [("117-hr-5376", True)]
    assert (report["congress"], report["covered_congress"], report["covered_congress_source"]) == (
        "118",
        "117",
        "title",
    )
    # Every printed bill the MODS lists, it lists under the 118th.
    assert int(report["bills_congress_mismatch"]) == int(report["distinct_bills"]) >= 1
    assert report["distinct_bills_beyond_index"] == report["distinct_bills"]
    assert {row["stated_by_index"] for row in citations} == {"false"}
    actions = find_bill_actions(body.text, findings)
    assert {(a.bill_id, a.phrasing) for a in actions.findings} >= {("117-hr-5376", "became_public_law")}


def test_a_report_that_states_no_congress_publishes_no_bill_key_comparison_or_action() -> None:
    """Unresolved rather than guessed: the printed form stays, and every comparison that needs a Congress is NULL."""
    body, summary, mods = _senate_report([])
    unstated = CoveredCongress(None, None, ())
    findings, report, citations = _row(body, summary, mods, unstated)

    assert findings and all(not f.target_resolved for f in findings)
    assert "HR5376" in {f.target_key for f in findings}
    assert (report["covered_congress"], report["covered_congress_source"]) == (None, None)
    assert (report["distinct_bills_beyond_index"], report["bills_congress_mismatch"]) == (None, None)
    assert report["distinct_bills"] == str(len({f.target_key for f in findings}))
    assert {row["stated_by_index"] for row in citations} == {None}
    # The phrase is readable -- the stated reading attaches it -- so no action here is the refusal, not a miss.
    assert find_bill_actions(body.text, findings).findings == ()
    assert find_bill_actions(
        body.text, _row(body, summary, mods, covered_congress(summary.title, body.pages))[0]
    ).findings
