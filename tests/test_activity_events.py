"""What changed between two runs, built from the contracts' own shaped rows.

Every snapshot here comes from ``build_bill_family`` output, never from a
hand-written dict: an event comparison that reads rows the contracts did not
shape would agree with itself whatever the shapers did.

The comparison itself needs no diff engine -- it reads published rows -- but the
rows do, so the cases that need real ``bill_versions`` or ``bill_summaries``
skip with the extra, the way ``tests/test_section_diff.py`` does.
"""

from __future__ import annotations

import json

import pytest

from spicy_docs.interpretation.bill_family import BillFamilyCapture
from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.activity_events import (
    EVENT_TYPES,
    NO_SUBJECT,
    PUBLIC_ACTIVITY_EVENTS,
    activity_events,
    snapshot_from_rows,
)
from spicy_docs.schemas.tables import joined
from tests.test_bill_family import (
    StubSummarizer,
    captured_pair_capture,
    family,
    modelled_family,
    needs_engine,
)

DETECTED_AT = "2026-09-20T03:00:00Z"
EMPTY = snapshot_from_rows()


def _status_only_capture() -> BillFamilyCapture:
    """One BILLSTATUS document and no printings: enough for every bill-level event."""
    return BillFamilyCapture(status=captured_pair_capture().status, observed_at=DETECTED_AT)


def _snapshot(tables) -> object:
    return snapshot_from_rows(
        bills=tables.bills,
        bill_versions=tables.bill_versions,
        bill_summaries=tables.bill_summaries,
    )


def _events(prior, current) -> tuple[dict[str, str | None], ...]:
    return activity_events(prior, current, detected_at=DETECTED_AT)


@needs_engine
def test_a_first_run_reports_one_event_per_row_it_found() -> None:
    tables = modelled_family()
    events = _events(EMPTY, _snapshot(tables))
    by_type: dict[str, list] = {name: [] for name in EVENT_TYPES}
    for row in events:
        by_type[row["event_type"]].append(row)

    assert len(by_type["bill_added"]) == 1
    assert len(by_type["version_added"]) == len(tables.bill_versions)
    assert len(by_type["summary_generated"]) == len(tables.bill_summaries)
    # Nothing changed from nothing, so no stage change is reported.
    assert by_type["stage_changed"] == []
    for row in events:
        assert PUBLIC_ACTIVITY_EVENTS.checked(row) is row
        assert PUBLIC_ACTIVITY_EVENTS.key(row)


@needs_engine
def test_identical_snapshots_produce_nothing() -> None:
    snapshot = _snapshot(modelled_family())
    assert _events(snapshot, snapshot) == ()


@needs_engine
def test_a_row_only_in_prior_produces_no_event() -> None:
    """Deletions are not events: the four-type vocabulary is sealed."""
    full = _snapshot(modelled_family())
    assert _events(full, EMPTY) == ()


@needs_engine
def test_two_versions_of_one_bill_on_one_date_produce_two_events() -> None:
    """The study's key collides here; ``subject_id`` is what keeps the two apart (C8)."""
    tables = modelled_family()
    one_date = tuple({**row, "version_date": "2026-06-08T04:00:00Z"} for row in tables.bill_versions)
    events = activity_events(
        EMPTY,
        snapshot_from_rows(bills=tables.bills, bill_versions=one_date),
        detected_at=DETECTED_AT,
    )
    added = [row for row in events if row["event_type"] == "version_added"]
    assert len(added) == 2
    assert {row["occurred_at"] for row in added} == {"2026-06-08T04:00:00Z"}
    assert len({PUBLIC_ACTIVITY_EVENTS.key(row) for row in added}) == 2
    assert {row["subject_id"] for row in added} == {
        joined(TABLE_CONTRACTS["bill_versions"].key(row)) for row in one_date
    }


@needs_engine
def test_a_changed_stage_names_the_rule_that_moved_it() -> None:
    tables = modelled_family()
    before = tuple({**row, "stage": "introduced"} for row in tables.bills)
    events = _events(
        snapshot_from_rows(bills=before, bill_versions=tables.bill_versions),
        snapshot_from_rows(bills=tables.bills, bill_versions=tables.bill_versions),
    )
    assert [row["event_type"] for row in events] == ["stage_changed"]
    data = json.loads(events[0]["event_data_json"])
    assert data["from"] == "introduced"
    assert data["to"] == tables.bills[0]["stage"]
    assert data["rule"] == tables.bills[0]["stage_rule"]
    assert data["matcher"] == tables.bills[0]["stage_matcher"]
    assert events[0]["subject_id"] == NO_SUBJECT


@needs_engine
def test_a_changed_content_hash_marks_the_summary_regenerated() -> None:
    first = modelled_family()
    again = family(
        classify=None,
        summarize=StubSummarizer(content_hash="sha256:" + "9" * 64),
    )
    events = _events(_snapshot(first), _snapshot(again))
    regenerated = [row for row in events if row["event_type"] == "summary_generated"]
    assert regenerated
    assert all(json.loads(row["event_data_json"])["regenerated"] is True for row in regenerated)

    # The same hash twice is not an event, even across two separate passes.
    assert [
        row
        for row in _events(_snapshot(first), _snapshot(modelled_family()))
        if row["event_type"] == "summary_generated"
    ] == []


@needs_engine
def test_an_event_falls_back_to_the_run_instant_only_when_the_publisher_states_none() -> None:
    tables = modelled_family()
    undated = tuple({**row, "version_date": None} for row in tables.bill_versions)
    events = activity_events(
        EMPTY,
        snapshot_from_rows(bills=tables.bills, bill_versions=undated),
        detected_at=DETECTED_AT,
    )
    added = [row for row in events if row["event_type"] == "version_added"]
    assert {row["occurred_at"] for row in added} == {DETECTED_AT}
    assert {row["detected_at"] for row in added} == {DETECTED_AT}


def test_a_bill_with_no_introduced_date_falls_back_to_its_update_date() -> None:
    """The fallback chain is introduced, then update, then the run instant."""
    tables = family(_status_only_capture(), diff=False)
    row = dict(tables.bills[0])
    assert row["introduced_date"]
    events = activity_events(EMPTY, snapshot_from_rows(bills=(row,)), detected_at=DETECTED_AT)
    assert [event["occurred_at"] for event in events] == [row["introduced_date"]]

    without = {**row, "introduced_date": None}
    events = activity_events(EMPTY, snapshot_from_rows(bills=(without,)), detected_at=DETECTED_AT)
    assert [event["occurred_at"] for event in events] == [row["update_date"]]

    bare = {**row, "introduced_date": None, "update_date": None}
    events = activity_events(EMPTY, snapshot_from_rows(bills=(bare,)), detected_at=DETECTED_AT)
    assert [event["occurred_at"] for event in events] == [DETECTED_AT]


def test_the_event_vocabulary_is_sealed_at_four_types() -> None:
    assert EVENT_TYPES == ("bill_added", "version_added", "stage_changed", "summary_generated")


def test_snapshot_keys_come_from_each_contracts_own_identity() -> None:
    """A hand-written key is how a comparison quietly stops agreeing with its table."""
    tables = family(_status_only_capture(), diff=False)
    snapshot = snapshot_from_rows(bills=tables.bills)
    assert set(snapshot.bills) == {TABLE_CONTRACTS["congress_bills"].key(row) for row in tables.bills}


def test_a_row_that_cannot_be_keyed_refuses_rather_than_snapshotting_none() -> None:
    from spicy_docs.schemas.tables import TableContractError

    tables = family(_status_only_capture(), diff=False)
    broken = {**tables.bills[0], "bill_id": None}
    with pytest.raises(TableContractError, match="is null"):
        snapshot_from_rows(bills=(broken,))
