"""What changed between two runs of the bill family, as four sealed event types computed by comparing two snapshots of
already-shaped rows -- never by watching a writer -- so a run that produced no rows produces no events rather than an
empty feed that looks like a quiet night.

Identity is ``(bill_id, event_type, subject_id, occurred_at)`` because two versions of one bill routinely share a date,
and it carries two instants deliberately: the publisher's ``occurred_at`` for a feed and the run's ``detected_at`` for
"what changed tonight".  Deletions are not events -- the four-type vocabulary is sealed, and a row leaving a table is a
fact about the run, stated in the coverage statement, not about the bill.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from spicy_docs.schemas.bill_model_tables import BILL_SUMMARIES
from spicy_docs.schemas.bill_tables import CONGRESS_BILLS
from spicy_docs.schemas.bill_version_tables import BILL_VERSIONS
from spicy_docs.schemas.tables import (
    Reference,
    Row,
    TableContract,
    TableContractError,
    joined,
    json_column,
    table_contract,
    text,
)

#: The sealed event vocabulary.  Adding a fifth type is a contract change.
EVENT_TYPES: tuple[str, ...] = ("bill_added", "version_added", "stage_changed", "summary_generated")

#: A bill-level event has no subject of its own; the empty string keeps the
#: identity tuple non-null rather than making a nullable identity column.
NO_SUBJECT = ""

PUBLIC_ACTIVITY_EVENTS = table_contract(
    "public_activity_events",
    references=(Reference(("bill_id",), "congress_bills", ("bill_id",)),),
    grain="One row per change detected between two runs of the bill family.",
    identity=("bill_id", "event_type", "subject_id", "occurred_at"),
    version_column="detected_at",
    columns={
        "bill_id": "The bill this event is about.",
        "event_type": "One of the four sealed event types.",
        "subject_id": "The version or summary key the event is about, unit-separator joined; empty for a bill event.",
        "occurred_at": "The publisher's own instant for the change, falling back to the run instant.",
        "detected_at": "When the run that found this change ran; the merge prefers the larger value.",
        "event_data_json": "The few fields a reader needs to render the event without joining another table.",
    },
)


@dataclass(frozen=True, slots=True)
class BillFamilySnapshot:
    """Three tables of one run, each keyed by its own contract's identity."""

    bills: Mapping[tuple[str, ...], Row]
    bill_versions: Mapping[tuple[str, ...], Row]
    bill_summaries: Mapping[tuple[str, ...], Row]


def _keyed(contract: TableContract, rows: Iterable[Row]) -> Mapping[tuple[str, ...], Row]:
    return MappingProxyType({contract.key(row): row for row in rows})


def snapshot_from_rows(
    *,
    bills: Iterable[Row] = (),
    bill_versions: Iterable[Row] = (),
    bill_summaries: Iterable[Row] = (),
) -> BillFamilySnapshot:
    """Key each table's rows with its own contract, never with a hand-written key that could quietly stop agreeing with
    the table it compares.
    """
    return BillFamilySnapshot(
        bills=_keyed(CONGRESS_BILLS, bills),
        bill_versions=_keyed(BILL_VERSIONS, bill_versions),
        bill_summaries=_keyed(BILL_SUMMARIES, bill_summaries),
    )


def _event(
    *,
    bill_id: str | None,
    event_type: str,
    subject_id: str,
    occurred_at: str | None,
    detected_at: str,
    data: Mapping[str, object],
) -> Row:
    # The vocabulary is sealed, so it is checked rather than merely declared:
    # a fifth type is a contract change, and this is where that shows up.
    if event_type not in EVENT_TYPES:
        raise TableContractError(f"event_type must be one of {EVENT_TYPES}, not {event_type!r}")
    return {
        "bill_id": text(bill_id),
        "event_type": text(event_type),
        "subject_id": text(subject_id),
        "occurred_at": text(occurred_at if occurred_at else detected_at),
        "detected_at": text(detected_at),
        "event_data_json": json_column(dict(data)),
    }


def activity_events(
    prior: BillFamilySnapshot,
    current: BillFamilySnapshot,
    *,
    detected_at: str,
) -> tuple[Row, ...]:
    """Every event the move from ``prior`` to ``current`` produced, in table order.

    ``O(|prior| + |current|)``: one pass per keyed mapping with constant-time lookups.
    """
    events: list[Row] = []

    for key, row in current.bills.items():
        before = prior.bills.get(key)
        if before is None:
            events.append(
                _event(
                    bill_id=row["bill_id"],
                    event_type="bill_added",
                    subject_id=NO_SUBJECT,
                    occurred_at=row["introduced_date"] or row["update_date"],
                    detected_at=detected_at,
                    data={
                        "title": row["title"],
                        "stage": row["stage"],
                        "sponsor_bioguide_id": row["sponsor_bioguide_id"],
                    },
                )
            )
        elif before["stage"] != row["stage"]:
            events.append(
                _event(
                    bill_id=row["bill_id"],
                    event_type="stage_changed",
                    subject_id=NO_SUBJECT,
                    occurred_at=row["update_date"],
                    detected_at=detected_at,
                    data={
                        "from": before["stage"],
                        "to": row["stage"],
                        "rule": row["stage_rule"],
                        "matcher": row["stage_matcher"],
                    },
                )
            )

    for key, row in current.bill_versions.items():
        if key in prior.bill_versions:
            continue
        events.append(
            _event(
                bill_id=row["bill_id"],
                event_type="version_added",
                subject_id=joined(key),
                occurred_at=row["version_date"],
                detected_at=detected_at,
                data={
                    "version_code": row["version_code"],
                    "source": row["source"],
                    "kind": row["kind"],
                    "kind_rule": row["kind_rule"],
                },
            )
        )

    for key, row in current.bill_summaries.items():
        before = prior.bill_summaries.get(key)
        if before is not None and before["content_hash"] == row["content_hash"]:
            continue
        events.append(
            _event(
                bill_id=row["bill_id"],
                event_type="summary_generated",
                subject_id=joined(key),
                occurred_at=row["completed_at"],
                detected_at=detected_at,
                data={
                    "model": row["model"],
                    "prompt_version": row["prompt_version"],
                    "content_hash": row["content_hash"],
                    "regenerated": before is not None,
                },
            )
        )

    return tuple(PUBLIC_ACTIVITY_EVENTS.checked(event) for event in events)


__all__ = [
    "EVENT_TYPES",
    "NO_SUBJECT",
    "PUBLIC_ACTIVITY_EVENTS",
    "BillFamilySnapshot",
    "activity_events",
    "snapshot_from_rows",
]
