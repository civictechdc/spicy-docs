"""The CRPT activity-report title rule, offline.

Every title here is a real one from the ``published`` CRPT window
2025-01-01..2025-03-31 that the PDF-family rollup retained, re-derived
2026-09-20 in ``activity-report-title-rule-2026-09-20/``: 71 packages walked,
20 titles carrying the bare word, 15 the phrase rule matches. Both classes the
rule is answerable for are pinned -- the false positives it rejects and the
two real activity reports it misses -- so widening it has to move a test and
not only a pattern.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spicy_docs.sources.govinfo.activity_reports import (
    ACTIVITY_REPORT_RULE_VERSION,
    ACTIVITY_REPORT_TITLE,
    is_activity_report,
    names_activity,
)

#: The measured matches, one per clause of the rule and then some. Publisher
#: spelling and casing exactly as the index states them.
MATCHES = (
    ("CRPT-118hrpt968", "LEGISLATIVE REVIEW AND OVERSIGHT ACTIVITIES of the COMMITTEE ON FOREIGN AFFAIRS"),
    (
        "CRPT-118hrpt974",
        "Summary of the Activities of the Committee on Transportation and Infrastructure for the 118th Congress",
    ),
    (
        "CRPT-118hrpt965",
        (
            "ACTIVITY REPORT of the COMMITTEE ON ENERGY AND COMMERCE of the HOUSE OF REPRESENTATIVES "
            "for the ONE HUNDRED EIGHTEENTH CONGRESS"
        ),
    ),
    # The fixed phrase, with no committee named anywhere in the title.
    ("CRPT-118hrpt976", "REPORT ON ACTIVITIES DURING THE 118TH CONGRESS"),
    # Committee first, activities second -- the second clause.
    (
        "CRPT-119srpt2",
        "LEGISLATIVE AND OVERSIGHT ACTIVITIES DURING THE 118TH CONGRESS BY THE SENATE COMMITTEE ON VETERANS' AFFAIRS",
    ),
)

#: The false-positive class, measured. Each carries the bare word and is not an
#: activity report.
REJECTED_FALSE_POSITIVES = (
    (
        "CRPT-119hrpt10",
        (
            "DIRECTING THE SECRETARY OF HOMELAND SECURITY TO TRANSMIT TO THE HOUSE OF REPRESENTATIVES CERTAIN "
            "DOCUMENTS RELATING TO DEPARTMENT OF HOMELAND SECURITY POLICIES AND ACTIVITIES RELATED TO DOMESTIC "
            "PREPAREDNESS AND COLLECTIVE RESPONSE TO TERRORISM AND THE DEPARTMENT'S CYBERSECURITY ACTIVITIES"
        ),
    ),
    (
        "CRPT-119hrpt1",
        (
            "PROVIDING FOR CONSIDERATION OF THE BILL (H.R. 471) TO EXPEDITE UNDER THE NATIONAL ENVIRONMENTAL "
            "POLICY ACT OF 1969 AND IMPROVE FOREST MANAGEMENT ACTIVITIES ON NATIONAL FOREST SYSTEM LANDS"
        ),
    ),
)

#: The miss class, measured and deliberately not fixed here: both name a
#: Congress and no committee, and reaching them means dropping the committee
#: requirement that rejects the two above.
MISSED_ACTIVITY_REPORTS = (
    ("CRPT-118hrpt973", "SUMMARY OF ACTIVITIES ONE HUNDRED EIGHTEENTH CONGRESS"),
    ("CRPT-119srpt5", "REVIEW OF LEGISLATIVE ACTIVITY DURING THE 118TH CONGRESS"),
)


@pytest.mark.parametrize(("package_id", "title"), MATCHES)
def test_the_phrase_rule_selects_a_real_activity_report(package_id: str, title: str) -> None:
    assert is_activity_report(package_id, title)
    assert names_activity(title)


@pytest.mark.parametrize(("package_id", "title"), REJECTED_FALSE_POSITIVES + MISSED_ACTIVITY_REPORTS)
def test_the_bare_word_takes_what_the_phrase_rule_refuses(package_id: str, title: str) -> None:
    """The measured 20-against-15 gap, in both directions, on the real titles.

    ``names_activity`` is the rejected alternative and has to keep matching, or
    the precision the rule is chosen on stops being measurable.
    """
    assert names_activity(title)
    assert not is_activity_report(package_id, title)


def test_the_collection_is_checked_on_the_row_not_the_request() -> None:
    """A collection-scoped walk serves neighbours, so the id is checked too."""
    title = MATCHES[0][1]
    assert not is_activity_report("GPO-J6-REPORT", title)
    assert not is_activity_report("CDOC-119tdoc2", title)
    # And the prefix alone is not enough: an ordinary committee report is not
    # selected by carrying the right collection.
    assert not is_activity_report("CRPT-119hrpt1", "REPORT ON H.R. 471")


def test_a_missing_publisher_field_is_a_skipped_row_not_an_error() -> None:
    assert not is_activity_report(None, "ACTIVITIES OF THE COMMITTEE")  # type: ignore[arg-type]
    assert not is_activity_report("CRPT-118hrpt968", None)  # type: ignore[arg-type]
    assert not names_activity(None)  # type: ignore[arg-type]


def test_the_rule_version_is_derived_from_the_rule() -> None:
    """A hand-set version can be left behind by an edit; a digest cannot."""
    assert ACTIVITY_REPORT_RULE_VERSION == "89855b6512d9"
    assert len(ACTIVITY_REPORT_RULE_VERSION) == 12
    assert "activit" in ACTIVITY_REPORT_TITLE.pattern


def test_the_tools_and_the_package_select_with_one_object() -> None:
    """The restatement this move exists to delete must not come back.

    ``tools/analysis/pdf_family_rollup.py`` measured this family's yield and
    a host publishes it; a second copy of the regex in either is how the
    measurement and the product drift apart.
    """
    from tools.analysis import pdf_family_rollup

    assert pdf_family_rollup.is_activity_report is is_activity_report
    assert pdf_family_rollup.names_activity is names_activity
    assert "activit(?:y|ies)" not in Path(pdf_family_rollup.__file__).read_text(encoding="utf-8")
