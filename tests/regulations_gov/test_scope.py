"""Regulations Gov: scope behavior."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from spicy_docs.regulations_gov_source_native import (
    MAX_QUERY_DAYS,
    RegulationsGovSourceError,
    docket_acquisition_policy,
    document_acquisition_policy,
    regulations_gov_docket_query_scope,
    regulations_gov_document_query_scope,
)
from tests.regulations_gov.fixtures import (
    _docket_scope,
    _document_scope,
)


@pytest.mark.parametrize(
    ("scope", "validator", "message"),
    [
        (
            {
                "agencies": ["EPA", "EPA"],
                "publishedFrom": "2026-08-24",
                "publishedThrough": "2026-08-24",
            },
            regulations_gov_document_query_scope,
            "sorted, and distinct",
        ),
        (
            {
                "agencies": ["EPA"],
                "modifiedFrom": "2026-08-25",
                "modifiedThrough": "2026-08-24",
            },
            regulations_gov_docket_query_scope,
            "reversed",
        ),
        (
            {
                "agencies": ["EPA"],
                # MAX_QUERY_DAYS is ~40 years (regulations.gov/FDMS source
                # history begins in the 1990s); this span exceeds it.
                "publishedFrom": "1900-01-01",
                "publishedThrough": "2026-08-24",
            },
            regulations_gov_document_query_scope,
            "date bound",
        ),
    ],
)
def test_query_scopes_are_closed_ascii_and_bounded(scope, validator, message: str) -> None:
    with pytest.raises(RegulationsGovSourceError, match=message):
        validator(scope)


def test_query_scope_spans_a_full_source_history_up_to_the_inclusive_bound() -> None:
    """One window per agency must cover a source's whole history (2026-09-02
    amendment); the superseded 366-day bound refused every such scope.
    """
    start = date(1990, 1, 1)
    full_history = regulations_gov_document_query_scope(
        {"agencies": ["EPA"], "publishedFrom": start.isoformat(), "publishedThrough": "2026-09-02"}
    )
    assert full_history["publishedFrom"] == "1990-01-01"
    assert full_history["publishedThrough"] == "2026-09-02"

    def scope(inclusive_days: int) -> dict[str, object]:
        through = start + timedelta(days=inclusive_days - 1)
        return {"agencies": ["EPA"], "publishedFrom": start.isoformat(), "publishedThrough": through.isoformat()}

    assert MAX_QUERY_DAYS == 14_640
    widest = regulations_gov_document_query_scope(scope(MAX_QUERY_DAYS))
    assert widest["publishedThrough"] == "2030-01-30"  # 1990-01-01 + 14,639 days
    with pytest.raises(RegulationsGovSourceError, match="date bound"):
        regulations_gov_document_query_scope(scope(MAX_QUERY_DAYS + 1))

    # The bound is a sealed acquisition-policy member, not just a guard.
    assert document_acquisition_policy(_document_scope())["maxQueryDays"] == 14_640


def test_docket_and_document_acquisition_policies_declare_the_newest_observation_collapse() -> None:
    document_selection = document_acquisition_policy(_document_scope())["observationSelection"]
    assert document_selection == {
        "groupBy": "/data/id",
        "orderBy": "coalesce(/data/attributes/modifyDate, /data/attributes/postedDate) DESC NULLS LAST",
        "tieDisposition": "refuse-differing-record-digest-at-normalized-instant",
    }

    docket_selection = docket_acquisition_policy(_docket_scope())["observationSelection"]
    assert docket_selection == {
        "groupBy": "/data/id",
        "orderBy": "/data/attributes/modifyDate DESC NULLS LAST",
        "tieDisposition": "refuse-differing-record-digest-at-normalized-instant",
    }
