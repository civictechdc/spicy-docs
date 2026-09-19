"""Join a roll-call vote to the bill it was taken on, from structured references only.

Publisher fact in: the ``recordedVotes`` entries the publisher attaches to a
bill's own actions, and the ``legislationType``/``legislationNumber`` fields
the House vote route states for a roll call.

Interpretation out: a ``VoteMatch`` per vote naming the bill, the rule that
supplied it and the publisher URL the reference carried.

This replaces a regex over prose. ``BillTrax/src/lib/roll-call-votes.ts:143``
matched ``/\\b([HS])\\.?\\s*R\\.?\\s*(\\d+)\\b/i`` against the vote question, in
which ``R`` is not optional, so the Senate branch one line below it was
unreachable and every Senate vote went silently unmatched -- measured in the
value inventory, where ``On Passage of S. 123`` returns no match at all.
Nothing here reads question text: a recorded vote sits on the bill's own
action, which *is* the join, and the House vote route names the legislation in
two dedicated fields.

The reference shape is sealed by measurement, not by tolerance. A 2026-09-19
pass over 20 bills found 58 ``recordedVotes`` entries on 58 voted actions,
exactly one per action, and all six fields present on all 58 -- ``chamber``,
``congress``, ``date``, ``rollNumber``, ``sessionNumber``, ``url`` -- across
two hosts (clerk.house.gov 49, www.senate.gov 9). So all six are required
here. BillTrax's declared type also carried ``fullActionName``, which the API
emitted 0 times in 58; it is not carried, and ``date`` and ``url`` are not
optional, because the measurement says they are not.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from spicy_docs.sources.congress.bill_status import BILL_TYPES, BillIdentity

RECORDED_VOTE_FIELDS: tuple[str, ...] = ("chamber", "congress", "date", "rollNumber", "sessionNumber", "url")
VOTE_CHAMBERS = frozenset({"house", "senate"})

VOTE_MATCH_RULES: tuple[str, ...] = ("bill_action_recorded_vote", "house_vote_legislation", "unmatched")


class VoteMatchError(ValueError):
    """A reference cannot establish the vote or the bill it names."""


@dataclass(frozen=True, slots=True)
class VoteKey:
    """The publisher's identity for one roll call: congress, chamber, session, roll number."""

    congress: int
    chamber: str
    session: int
    roll_number: int

    def __post_init__(self) -> None:
        for name, value in (("congress", self.congress), ("session", self.session), ("roll", self.roll_number)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise VoteMatchError(f"{name} must be a non-negative integer")
        if self.chamber not in VOTE_CHAMBERS:
            raise VoteMatchError("chamber must be 'house' or 'senate'")


@dataclass(frozen=True, slots=True)
class VoteReference:
    """One structured statement that a roll call belongs to a bill."""

    vote: VoteKey
    bill: BillIdentity
    rule: str
    url: str | None
    date: str | None
    action_index: int | None = None


@dataclass(frozen=True, slots=True)
class VoteMatch:
    """``bill`` is ``None`` and ``rule`` is ``unmatched`` when no reference named this vote."""

    vote: VoteKey
    bill: BillIdentity | None
    rule: str
    url: str | None = None
    date: str | None = None


@dataclass(frozen=True, slots=True)
class VoteIndex:
    """First reference wins per vote; a disagreeing later one is kept as a conflict, not dropped."""

    by_vote: Mapping[VoteKey, VoteReference]
    conflicts: tuple[tuple[VoteReference, VoteReference], ...]


def _get(record: object, *names: str) -> object:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return None
    for name in names:
        value = getattr(record, name, None)
        if value is not None:
            return value
    return None


def _required_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise VoteMatchError(f"recorded vote {field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise VoteMatchError(f"recorded vote {field} must be an integer")


def _required_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VoteMatchError(f"recorded vote {field} must be a non-empty string")
    return value


def bill_type_of(legislation_type: object) -> str:
    """Normalize a publisher legislation type (``HR``, ``S.Res.``) to the lowercase vocabulary."""
    if not isinstance(legislation_type, str):
        raise VoteMatchError("legislation type must be a string")
    normalized = "".join(character for character in legislation_type.lower() if character.isalnum())
    if normalized not in BILL_TYPES:
        raise VoteMatchError(f"unsupported legislation type {legislation_type!r}")
    return normalized


def read_vote_key(entry: object) -> VoteKey:
    """Read the four identity fields of a ``recordedVotes`` entry; all are required."""
    chamber = _required_str(_get(entry, "chamber"), "chamber").strip().lower()
    return VoteKey(
        congress=_required_int(_get(entry, "congress"), "congress"),
        chamber=chamber,
        session=_required_int(_get(entry, "sessionNumber", "session_number", "session"), "sessionNumber"),
        roll_number=_required_int(_get(entry, "rollNumber", "roll_number"), "rollNumber"),
    )


def recorded_vote_references(identity: BillIdentity, actions: Iterable[object]) -> tuple[VoteReference, ...]:
    """Every recorded vote a bill's own actions carry, in publisher order.

    The bill is the enclosing document, so the reference needs no matching at
    all: reading it *is* the join.
    """
    references: list[VoteReference] = []
    for position, action in enumerate(actions):
        entries = _get(action, "recordedVotes", "recorded_votes")
        if entries is None:
            continue
        if isinstance(entries, str | Mapping) or not isinstance(entries, Iterable):
            raise VoteMatchError("recordedVotes must be a list of entries")
        for entry in entries:
            references.append(
                VoteReference(
                    vote=read_vote_key(entry),
                    bill=identity,
                    rule="bill_action_recorded_vote",
                    url=_required_str(_get(entry, "url"), "url"),
                    date=_required_str(_get(entry, "date"), "date"),
                    action_index=position,
                )
            )
    return tuple(references)


def house_vote_references(votes: Iterable[object]) -> tuple[VoteReference, ...]:
    """Read ``legislationType``/``legislationNumber`` off House vote records.

    A House vote that names no legislation -- a procedural roll call, an
    adjournment -- is skipped rather than refused: the absence is the
    publisher's answer, not a malformed record.
    """
    references: list[VoteReference] = []
    for vote in votes:
        legislation_type = _get(vote, "legislationType", "legislation_type")
        legislation_number = _get(vote, "legislationNumber", "legislation_number")
        if legislation_type is None or legislation_number is None:
            continue
        congress = _required_int(_get(vote, "congress"), "congress")
        url = _get(vote, "sourceDataURL", "source_data_url")
        date = _get(vote, "startDate", "start_date", "date")
        references.append(
            VoteReference(
                vote=VoteKey(
                    congress=congress,
                    chamber="house",
                    session=_required_int(_get(vote, "sessionNumber", "session_number", "session"), "sessionNumber"),
                    roll_number=_required_int(
                        _get(vote, "rollCallNumber", "roll_call_number", "rollNumber"), "rollCallNumber"
                    ),
                ),
                bill=BillIdentity(
                    congress=congress,
                    bill_type=bill_type_of(legislation_type),
                    number=_required_int(legislation_number, "legislationNumber"),
                ),
                rule="house_vote_legislation",
                url=url if isinstance(url, str) else None,
                date=date if isinstance(date, str) else None,
            )
        )
    return tuple(references)


def index_vote_references(references: Iterable[VoteReference]) -> VoteIndex:
    """One pass, O(references); later references that name a different bill become conflicts."""
    by_vote: dict[VoteKey, VoteReference] = {}
    conflicts: list[tuple[VoteReference, VoteReference]] = []
    for reference in references:
        held = by_vote.get(reference.vote)
        if held is None:
            by_vote[reference.vote] = reference
        elif held.bill != reference.bill:
            conflicts.append((held, reference))
    return VoteIndex(by_vote=by_vote, conflicts=tuple(conflicts))


def match_votes(votes: Iterable[VoteKey], index: VoteIndex) -> tuple[VoteMatch, ...]:
    """Look each vote up by its publisher identity; O(votes) with no regular expressions."""
    matches: list[VoteMatch] = []
    for vote in votes:
        reference = index.by_vote.get(vote)
        if reference is None:
            matches.append(VoteMatch(vote, None, "unmatched"))
        else:
            matches.append(VoteMatch(vote, reference.bill, reference.rule, reference.url, reference.date))
    return tuple(matches)


__all__ = [
    "RECORDED_VOTE_FIELDS",
    "VOTE_CHAMBERS",
    "VOTE_MATCH_RULES",
    "VoteIndex",
    "VoteKey",
    "VoteMatch",
    "VoteMatchError",
    "VoteReference",
    "bill_type_of",
    "house_vote_references",
    "index_vote_references",
    "match_votes",
    "read_vote_key",
    "recorded_vote_references",
]
