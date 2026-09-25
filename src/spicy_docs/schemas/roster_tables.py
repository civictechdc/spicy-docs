"""The ``committees`` table (Congress.gov ``committee/{congress}`` list rows with the ``committee-detail`` record folded
on where captured) and ``committee_assignments`` (today's seats from the House Clerk's ``MemberData.xml`` and the
Senate's ``cvc_member_data.xml``), closing gap A9.

The committee list route is read whole, so nothing here relies on its order.  ``committee_assignments`` keys on
``bioguide_id`` because both roster files state it on every seated member, and its ``lis_id`` is the Senate file's own
statement rather than a second crosswalk.  No ``members`` contract is invented here: that table already exists over the
legislators crosswalk.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from spicy_docs.schemas.tables import VALUE_KEY, Row, TableContractError, flag, json_column, table_contract, text

#: The Senate file states no Congress; a row shaped from it carries the
#: Congress the caller supplied and says so here.
CONGRESS_BASES = ("file", "caller")

COMMITTEES = table_contract(
    "committees",
    grain="One row per committee or subcommittee the Congress.gov committee list route states, with its detail record where captured.",
    identity=("system_code",),
    version_column="update_date",
    key_spelling=VALUE_KEY,
    columns={
        "system_code": "The publisher's systemCode, the identifier every bill, report and communication refers to.",
        "chamber": "The chamber as the publisher spells it: House, Senate or Joint.",
        "name": "The committee's name as the list route states it.",
        "committee_type": "The publisher's committeeTypeCode (Standing, Select, Subcommittee, Joint, and the rest).",
        "parent_system_code": "The parent committee's systemCode, where the publisher states a parent.",
        "parent_name": "The parent committee's name as the publisher states it.",
        "is_subcommittee": "true when the publisher states a parent, false otherwise.",
        "subcommittee_count": "How many subcommittees the publisher lists under this committee.",
        "subcommittees_json": "The listed subcommittees' systemCodes, as a JSON array in the publisher's order.",
        "update_date": "The list row's updateDate; the merge prefers the larger value.",
        "url": "The publisher's own URL for this committee.",
        "detail_captured": "true when the committee-detail record was captured and folded onto this row.",
        "is_current": "The detail record's isCurrent, where captured.",
        "detail_type": "The detail record's type, where captured.",
        "website_url": "The detail record's committeeWebsiteUrl, where captured.",
        "history_count": "How many history entries the detail record carries.",
        "history_json": "The detail record's history entries, verbatim, as a JSON array in the publisher's order.",
        "bill_count": "The detail record's stated count of bills referred to this committee, that day's statement.",
        "report_count": "The detail record's stated count of reports, that day's statement.",
        "communication_count": "The detail record's stated count of communications, that day's statement.",
        "detail_update_date": "The detail record's own updateDate.",
    },
)

COMMITTEE_ASSIGNMENTS = table_contract(
    "committee_assignments",
    grain="One row per member per committee or subcommittee seat a chamber roster file lists today.",
    identity=("congress", "system_code", "bioguide_id"),
    version_column="observed_at",
    columns={
        "congress": "The Congress the assignment belongs to.",
        "congress_basis": (
            "`file` when the file states that Congress itself (the House file does), `caller` when it "
            "states none and the caller supplied it (the Senate file states only its update date)."
        ),
        "session": "The session the House file states; the Senate file states none.",
        "chamber": "Which file the seat came from: house or senate.",
        "system_code": (
            "Derived join code: House native standing/select type selects hs/hl; the Senate code is lowercased. "
            "House joint codes keep their unresolved legacy spelling and do not establish a Congress.gov join."
        ),
        "committee_code": "The file's own committee code, verbatim.",
        "is_subcommittee": "true for a House subcommittee seat; the Senate file lists full committees only.",
        "parent_system_code": "The parent committee's systemCode for a subcommittee seat.",
        "committee_name": "The committee's name as the file itself states it.",
        "bioguide_id": "The member's bioguide id, which both files state; the key's target is members.bioguide_id.",
        "lis_id": "The Senate file's own LIS id for the senator; the crosswalk table stays the LIS crosswalk.",
        "name_last": "The member's last name as the file spells it.",
        "name_first": "The member's first name as the file spells it.",
        "party": "The member's party as the file states it.",
        "state": "The member's state code as the file states it.",
        "district": "The House member's district as the file states it.",
        "rank": "The House file's rank on the committee; the Senate file states none.",
        "position": "The seat's stated role, verbatim: the House leadership attribute or the Senate position attribute.",
        "file_date": "The date the file states for itself: the House publish-date or the Senate lastUpdate date.",
        "observed_at": "When the file was captured; the merge prefers the larger value.",
    },
)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _codes(subcommittees: object) -> list[str]:
    """The listed subcommittees' systemCodes in publisher order; an entry without one is refused, not spelled None."""
    if not isinstance(subcommittees, list):
        return []
    codes: list[str] = []
    for entry in subcommittees:
        code = entry.get("systemCode") if isinstance(entry, Mapping) else None
        if not code:
            raise TableContractError("committees: a subcommittees[] entry needs a systemCode")
        codes.append(str(code))
    return codes


def shape_committee(record: Mapping[str, Any], detail: Mapping[str, Any] | None = None) -> Row:
    """One ``committees`` row from a list-route record and, where captured, its detail record.

    The detail's ``systemCode`` must equal the record's or the fold is refused, and where a detail was captured its
    ``subcommittees`` are the row's -- the list row's copy is read only when no detail was.
    """
    if detail is not None and detail.get("systemCode") != record.get("systemCode"):
        raise TableContractError(f"committees: detail {detail.get('systemCode')!r} is not {record.get('systemCode')!r}")
    parent = _mapping(record.get("parent")) or (_mapping(detail.get("parent")) if detail else None)
    subcommittees = _codes((record if detail is None else detail).get("subcommittees"))
    history = (detail or {}).get("history")
    history = history if isinstance(history, list) else []

    def count(key: str) -> str | None:
        pointer = _mapping((detail or {}).get(key))
        return None if pointer is None else text(pointer.get("count"))

    return {
        "system_code": text(record.get("systemCode")),
        "chamber": text(record.get("chamber")),
        "name": text(record.get("name")),
        "committee_type": text(record.get("committeeTypeCode")),
        "parent_system_code": None if parent is None else text(parent.get("systemCode")),
        "parent_name": None if parent is None else text(parent.get("name")),
        "is_subcommittee": flag(parent is not None),
        "subcommittee_count": text(len(subcommittees)),
        "subcommittees_json": json_column(subcommittees),
        "update_date": text(record.get("updateDate")),
        "url": text(record.get("url")),
        "detail_captured": flag(detail is not None),
        "is_current": None if detail is None else flag(detail.get("isCurrent")),
        "detail_type": None if detail is None else text(detail.get("type")),
        "website_url": None if detail is None else text(detail.get("committeeWebsiteUrl")),
        "history_count": None if detail is None else text(len(history)),
        "history_json": None if detail is None else json_column(history),
        "bill_count": count("bills"),
        "report_count": count("reports"),
        "communication_count": count("communications"),
        "detail_update_date": None if detail is None else text(detail.get("updateDate")),
    }


def shape_house_assignment(member: object, assignment: object, *, roster: object, observed_at: str) -> Row:
    """One ``committee_assignments`` row from a ``HouseMember`` and one of its ``HouseAssignment`` entries.

    A vacancy has no bioguide and never reaches here; a member with a bioguide of ``None`` refuses rather than keying on
    NULL.
    """
    if member.bioguide_id is None:
        raise TableContractError("committee_assignments: a vacant seat has no member to key on")
    is_subcommittee = assignment.kind == "subcommittee"
    parent_code = roster.parent_system_code(assignment.code) if is_subcommittee else None
    return {
        "congress": text(roster.congress),
        "congress_basis": "file",
        "session": text(roster.session),
        "chamber": "house",
        "system_code": text(roster.system_code(assignment.code)),
        "committee_code": text(assignment.code),
        "is_subcommittee": flag(is_subcommittee),
        "parent_system_code": parent_code,
        "committee_name": text(roster.committee_names.get(assignment.code)),
        "bioguide_id": text(member.bioguide_id),
        "lis_id": None,
        "name_last": text(member.fields.get("lastname")),
        "name_first": text(member.fields.get("firstname")),
        "party": text(member.fields.get("party")),
        "state": text(member.state_code),
        "district": text(member.fields.get("district")),
        "rank": text(assignment.rank),
        "position": text(assignment.leadership),
        "file_date": text(roster.publish_date),
        "observed_at": text(observed_at),
    }


def shape_senate_assignment(
    senator: object, assignment: object, *, congress: int, roster: object, observed_at: str
) -> Row:
    """One ``committee_assignments`` row from a ``Senator`` and one of its committee entries.

    The Senate file states no Congress, so ``congress`` is the caller's and
    ``congress_basis`` says so.
    """
    return {
        "congress": text(congress),
        "congress_basis": "caller",
        "session": None,
        "chamber": "senate",
        "system_code": text(assignment.system_code),
        "committee_code": text(assignment.code),
        "is_subcommittee": flag(False),
        "parent_system_code": None,
        "committee_name": text(assignment.name),
        "bioguide_id": text(senator.bioguide_id),
        "lis_id": text(senator.lis_id),
        "name_last": text(senator.last),
        "name_first": text(senator.first),
        "party": text(senator.party),
        "state": text(senator.state),
        "district": None,
        "rank": None,
        "position": text(assignment.position),
        "file_date": text(roster.last_update_date),
        "observed_at": text(observed_at),
    }


__all__ = [
    "COMMITTEES",
    "COMMITTEE_ASSIGNMENTS",
    "CONGRESS_BASES",
    "shape_committee",
    "shape_house_assignment",
    "shape_senate_assignment",
]
