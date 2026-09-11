"""Replay of stored Federal Register acquisition requests.

SD-20: a Federal Register rebuild (DocSpec decision 0003) replays 1.76 GB of
retained evidence with no refetch. ``federal_register_request_window`` used to
regenerate today's canonical URL from the module-level ``DOCUMENT_FIELDS`` and
demand exact equality against the stored request, so it refused every stored
page the moment ``DOCUMENT_FIELDS`` changed -- including pages recorded under
the field list still in force today. These tests pin the replacement: the
field list a stored request declares is parsed from the request itself and
checked against ``ACCEPTED_DOCUMENT_FIELD_SETS``, a small table of field sets
this project has accepted, keyed by the acquisition policy version each was
minted under.
"""

from __future__ import annotations

from datetime import date

import pytest

import spicy_docs.federal_register_source_native as federal_register
from spicy_docs.federal_register_source_native import (
    ACCEPTED_DOCUMENT_FIELD_SETS,
    DOCUMENT_FIELDS,
    FederalRegisterSourceError,
    federal_register_documents_url,
    federal_register_request_window,
)

QUERY_SCOPE = {"publishedFrom": "2026-08-25", "publishedThrough": "2026-08-25"}
EXPECTED_WINDOW = (date(2026, 8, 25), date(2026, 8, 25))


def test_a_request_carrying_the_current_field_list_replays() -> None:
    stored_request = federal_register_documents_url(QUERY_SCOPE)

    assert federal_register_request_window(stored_request) == EXPECTED_WINDOW


def test_a_request_carrying_an_unknown_field_set_is_refused_and_names_the_drift() -> None:
    drifted_fields = frozenset(DOCUMENT_FIELDS) - {"topics"}
    assert drifted_fields not in ACCEPTED_DOCUMENT_FIELD_SETS.values()
    stored_request = federal_register_documents_url(QUERY_SCOPE, fields=drifted_fields)

    with pytest.raises(FederalRegisterSourceError, match="field set"):
        federal_register_request_window(stored_request)


def test_a_hypothetical_future_accepted_field_set_also_replays(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mechanism generalises: any table entry -- not just today's -- replays.

    This is the property SD-20 exists for: on a real rebuild, evidence
    acquired under the current policy and evidence acquired under a future
    policy (once one is added to the table) must both replay untouched.
    ``correction_of`` was deferred out and never became a table entry (DocSpec
    0003), so the table holds only "1.0" and the addition here is hypothetical
    against a table of one. Keep it a field the schema genuinely does not
    carry.
    """

    future_fields = frozenset(DOCUMENT_FIELDS | {"some_future_field"})
    monkeypatch.setattr(
        federal_register,
        "ACCEPTED_DOCUMENT_FIELD_SETS",
        {**ACCEPTED_DOCUMENT_FIELD_SETS, "2.0": future_fields},
    )
    stored_request = federal_register_documents_url(QUERY_SCOPE, fields=future_fields)

    assert federal_register_request_window(stored_request) == EXPECTED_WINDOW


def test_a_request_carrying_the_1_0_field_set_still_replays() -> None:
    """SD-24: 1.0 evidence must replay exactly, which is what the rebuild did.

    This docstring claimed correction_of joins the requested fields as 1.1. It
    was deferred out and never landed, so "1.0" is not a historical entry being
    kept alive beside a newer one -- it is the only entry, and the property
    under test is that replay reads the field list from the evidence rather
    than from today's constant.
    """

    stored_request = federal_register_documents_url(QUERY_SCOPE, fields=ACCEPTED_DOCUMENT_FIELD_SETS["1.0"])

    assert federal_register_request_window(stored_request) == EXPECTED_WINDOW


def test_documents_url_with_explicit_fields_round_trips_through_the_window_parser() -> None:
    explicit_request = federal_register_documents_url(QUERY_SCOPE, fields=DOCUMENT_FIELDS)
    default_request = federal_register_documents_url(QUERY_SCOPE)

    assert explicit_request == default_request
    assert federal_register_request_window(explicit_request) == EXPECTED_WINDOW


def test_existing_callers_with_no_fields_argument_are_unchanged() -> None:
    assert federal_register_documents_url(QUERY_SCOPE) == federal_register_documents_url(
        QUERY_SCOPE, fields=DOCUMENT_FIELDS
    )
    assert federal_register_documents_url(QUERY_SCOPE, per_page=500) == federal_register_documents_url(
        QUERY_SCOPE, per_page=500, fields=DOCUMENT_FIELDS
    )


def test_the_1_0_field_set_is_frozen_and_never_follows_the_current_constant() -> None:
    """The historical entry must be a literal, not an alias of the live constant.

    The first draft of this table wrote ``{"1.0": DOCUMENT_FIELDS}``, which made
    the 1.0 entry a reference to whatever the current constant holds. Adding
    ``correction_of`` would then have silently rewritten the 1.0 entry to the
    23-field set and refused every stored 22-field page -- reintroducing exactly
    the defect this table exists to fix, under the table's own new error message.

    Spelling the expected members out here is the guard: editing the 1.0 literal
    fails this test, which is what should happen, because a published release was
    recorded under it.
    """

    assert ACCEPTED_DOCUMENT_FIELD_SETS["1.0"] == frozenset(
        {
            "abstract",
            "agencies",
            "agency_names",
            "body_html_url",
            "cfr_references",
            "comments_close_on",
            "docket_ids",
            "document_number",
            "effective_on",
            "end_page",
            "executive_order_number",
            "html_url",
            "pdf_url",
            "publication_date",
            "regulation_id_numbers",
            "signing_date",
            "start_page",
            "subtype",
            "title",
            "topics",
            "type",
            "volume",
        }
    )
    assert "correction_of" not in ACCEPTED_DOCUMENT_FIELD_SETS["1.0"]


def test_the_current_field_set_is_always_one_the_replay_path_accepts() -> None:
    """A field addition that forgets a table entry must fail here, not at rebuild.

    Without this, adding a field to ``DOCUMENT_FIELDS`` without adding the
    matching accepted set would leave the acquirer requesting fields the replay
    path refuses -- discovered only when a rebuild of retained evidence fails.
    """

    assert DOCUMENT_FIELDS in ACCEPTED_DOCUMENT_FIELD_SETS.values()


def test_the_current_field_set_is_one_the_replay_path_accepts_by_key() -> None:
    """The field-set version and the acquisition policy version are separate sequences.

    This test used to assert they are equal. That was wrong, and the composite
    identity change proved it: the acquisition policy moved 1.0 -> 1.1 because
    `source_record_id` became (document_number, publication_date), while the
    requested fields did not change at all. Tying the two together would force a
    meaningless field-set entry every time the policy moves for any other
    reason, and each such entry would be a second literal holding the same 22
    fields -- exactly the duplication the table exists to avoid.

    What must hold is weaker and true: the key the acquirer requests under names
    a set the replay path accepts.
    """

    assert federal_register._CURRENT_FIELD_POLICY in ACCEPTED_DOCUMENT_FIELD_SETS
    assert ACCEPTED_DOCUMENT_FIELD_SETS[federal_register._CURRENT_FIELD_POLICY] is DOCUMENT_FIELDS


def test_no_two_accepted_field_sets_are_the_same_object() -> None:
    """Aliasing at any version, not just the one the spelled-out test pins.

    Catches the recurrence: a future entry written as ``{"1.1": DOCUMENT_FIELDS}``
    passes every other test here until the 1.2 addition silently rewrites it.
    """

    assert len({id(value) for value in ACCEPTED_DOCUMENT_FIELD_SETS.values()}) == len(ACCEPTED_DOCUMENT_FIELD_SETS)
