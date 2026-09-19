"""Amendments, committee press releases, and roll-call votes.

Three identity decisions, each one a correction the placement study called for:

* ``amendments`` is keyed ``(congress, amendment_type, amendment_number)`` (C6).
  The study used the amended bill's key, but an amendment has its own publisher
  identity and can amend another amendment; the two amended-* columns stay as
  ordinary foreign keys.
* ``press_releases`` is keyed on ``release_id = sha256(chamber, link)`` (C7).
  BillTrax's unique key was a 255-byte prefix of the source URL, which collides
  on two releases sharing a long path; the full ``link`` stays its own column.
* ``roll_call_votes`` is keyed on the publisher's own roll call identity, and
  its four tally columns fold two publishers' different count names onto one
  vocabulary -- the Clerk's ``not-voting-total`` and the Senate's ``absent``
  are one column here, and :data:`TALLY_COLUMNS` says so rather than leaving a
  reader to infer it.
* ``member_votes`` is keyed on ``member_key`` rather than on ``bioguide_id``.
  The design named the bioguide id, but ``MemberVote.bioguide_id`` is nullable
  by measurement -- roughly four of ninety-nine Senate voters on any one roll
  call -- and an identity column cannot be null.  It keys on the *file-stated*
  id for the same reason: a Senate bioguide comes from the crosswalk, so
  preferring it would give one member two permanent rows across a run where the
  crosswalk resolved and one where it did not.  The bioguide keeps its own
  column, where a change is a correction rather than a new row.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from spicy_docs.schemas.tables import (
    Row,
    digest,
    flag,
    joined,
    json_column,
    table_contract,
    text,
)
from spicy_docs.schemas.tables import bill_id as bill_key

AMENDMENTS = table_contract(
    "amendments",
    grain="One row per amendment, as the Congress.gov amendment list route states it.",
    identity=("congress", "amendment_type", "amendment_number"),
    version_column="update_date",
    columns={
        "amendment_id": "Natural key: congress, lowercase amendment type and number joined with hyphens.",
        "congress": "The numbered Congress this amendment belongs to.",
        "amendment_type": "The publisher's amendment type, lowercased (samdt, hamdt, suamdt).",
        "amendment_number": "The amendment's number within its Congress and type.",
        "purpose": "The publisher's stated purpose of the amendment.",
        "description": "The publisher's description of the amendment.",
        "proposed_date": "The date the amendment was proposed, where the publisher states one.",
        "submitted_date": "The date the amendment was submitted, where the publisher states one.",
        "chamber": "The chamber the amendment was offered in.",
        "update_date": "The publisher's updateDate; the merge prefers the larger value.",
        "latest_action_date": "Date of the publisher's latestAction entry on this amendment.",
        "latest_action_text": "Text of the publisher's latestAction entry on this amendment.",
        "sponsor_bioguide_id": "Bioguide id of the first sponsor the publisher lists.",
        "sponsor_full_name": "Full name of that sponsor, exactly as the publisher spells it.",
        "sponsor_party": "The sponsor's party string in full, not a single letter.",
        "amended_bill_id": "Natural key of the bill this amendment amends, where it amends a bill.",
        "amended_amendment_id": "Natural key of the amendment this amendment amends, where it amends one.",
        "url": "The publisher's own URL for this amendment.",
    },
)

PRESS_RELEASES = table_contract(
    "press_releases",
    grain="One row per item in one appropriations committee press-release feed capture.",
    identity=("release_id",),
    version_column="observed_at",
    columns={
        "release_id": "Digest of the chamber and the item's full link; replaces a truncated-URL unique key.",
        "chamber": "Which committee feed this item came from.",
        "feed_url": "The feed address the capture requested.",
        "channel_title": "The channel title, which is also the proof the requested feed answered.",
        "channel_link": "The channel link, checked against the publisher's own host.",
        "channel_description": "The channel description as the publisher wrote it.",
        "channel_language": "The channel language tag.",
        "channel_copyright": "The channel copyright line, which only the Senate feed states.",
        "channel_docs": "The channel docs URL, which only the Senate feed states.",
        "channel_last_build_date": "The channel lastBuildDate, which only the Senate feed states.",
        "channel_ttl": "The channel ttl: the publisher's own polling contract.",
        "channel_skip_days": "The channel skipDays, unit-separator joined; NULL where the channel states none.",
        "channel_skip_hours": "The channel skipHours, unit-separator joined; NULL where the channel states none.",
        "item_index": "Zero-based position of this item in the captured channel.",
        "title": "The item title in full, never truncated to a display length.",
        "link": "The item's full link.",
        "guid": "The item's guid, where it carries one.",
        "guid_is_permalink": "The guid's isPermaLink, defaulting to true when the attribute is absent.",
        "description": "The item's raw HTML description exactly as the publisher wrote it, untruncated.",
        "description_text": "That description read as plain text, not a truncated excerpt.",
        "description_chars": "Character length of description_text.",
        "pub_date": "The item's pubDate exactly as the publisher spelled it, wrong zone abbreviation included.",
        "pub_date_instant": "That pubDate parsed to an instant under RFC 822's fixed abbreviation table.",
        "author": "The item's author, which the Senate feed states as a shared mailbox.",
        "creator": "The item's dc:creator, which the House feed states as a named staffer.",
        "categories_json": "Every category the item lists, as a JSON array.",
        "enclosure_url": "The enclosure URL, where the item carries one.",
        "enclosure_length": "The enclosure length in bytes, where the item states one.",
        "enclosure_type": "The enclosure media type, where the item states one.",
        "observed_at": "When the feed was captured; the merge prefers the larger value.",
        "bill_id": "The bill this release names, where a bill-number pattern matched.",
        "match_rule": "Which release-matching rule fired, including unmatched.",
        "matched_field": "Which field the mention was found in; the Senate feed can only ever match on title.",
        "matched_text": "The exact text that matched, so a false positive is readable from the row.",
    },
)

#: Each publisher's own count name, folded onto the four published columns.
#: The Clerk says ``not-voting-total`` and the Senate says ``absent`` for the
#: same bucket; the published column is ``not_voting``, and ``RollCallVote.tallies``
#: still carries whichever word the publisher used, so nothing is lost by the
#: fold -- it is stated here rather than left to a reader to guess.
TALLY_COLUMNS: Mapping[str, str] = MappingProxyType(
    {
        "yea-total": "yea",
        "yeas": "yea",
        "nay-total": "nay",
        "nays": "nay",
        "present-total": "present",
        "present": "present",
        "not-voting-total": "not_voting",
        "absent": "not_voting",
    }
)

ROLL_CALL_VOTES = table_contract(
    "roll_call_votes",
    grain="One row per roll call: the publisher's own tally, and the bill it refers to.",
    identity=("congress", "chamber", "session", "roll_number"),
    version_column="vote_date",
    columns={
        "vote_id": "Natural key: congress, chamber, session and roll number joined with hyphens.",
        "congress": "The numbered Congress the roll call belongs to.",
        "chamber": "house or senate.",
        "session": "The session number within that Congress.",
        "roll_number": "The roll-call number within that session.",
        "vote_date": "The date of the roll call; the merge prefers the larger value.",
        "source_url": "The publisher's own URL for this roll call.",
        "question": "The question put to the chamber, as the publisher states it.",
        "result": "The stated result of the roll call.",
        "yea": "Yea votes, from the Clerk's yea-total or the Senate's yeas.",
        "nay": "Nay votes, from the Clerk's nay-total or the Senate's nays.",
        "present": "Present votes, as each publisher counts them.",
        "not_voting": "Members not voting: the Clerk's not-voting-total, or the Senate's absent, folded to one column.",
        "tallies_json": (
            "Every count the publisher stated, under the publisher's own names, as a JSON object. "
            "The four columns above fold two vocabularies onto one; this is what was folded."
        ),
        "member_vote_count": "How many member positions the file carried; the member_votes row count for this roll call.",
        "bill_id": "The bill this roll call refers to, from a recorded-vote reference or a vote-list reference.",
        "match_rule": "Which vote-matching rule named that bill, including unmatched.",
        "match_action_index": "Position of the action whose recordedVote named this roll call, where one did.",
        "match_url": "The reference URL the match was read from.",
        "conflict_count": "How many later references disagreed with the one that won; kept, never dropped.",
    },
)

MEMBER_VOTES = table_contract(
    "member_votes",
    grain="One row per member's position on one roll call.",
    identity=("congress", "chamber", "session", "roll_number", "member_key"),
    version_column="vote_date",
    columns={
        "vote_id": "The roll call this position belongs to, as roll_call_votes keys it.",
        "congress": "The numbered Congress the roll call belongs to.",
        "chamber": "house or senate.",
        "session": "The session number within that Congress.",
        "roll_number": "The roll-call number within that session.",
        "member_key": (
            "The file-stated id: `lis:` plus the LIS id on a Senate record, the bare bioguide id on a House "
            "one, and `name:` plus the publisher's name where the file states neither. A Senate bioguide "
            "comes from the crosswalk and does not always resolve, so keying on it would split one member's "
            "votes across two rows; an identity column also cannot be null, which the design's bioguide key "
            "would have been."
        ),
        "bioguide_id": "The voting member's bioguide id, where the publisher or the crosswalk supplies one.",
        "lis_id": "The voting member's Senate LIS id, which only the Senate file carries.",
        "member_name": "The member's name exactly as the roll-call source spells it.",
        "party": "The member's party as the roll-call source states it.",
        "state": "The member's state as the roll-call source states it.",
        "position": "The member's position exactly as the publisher spelled it (Yea, Aye, Not Voting...).",
        "position_normalized": "That position folded onto yea, nay, present or not_voting.",
        "vote_date": "The date of the roll call; the merge prefers the larger value.",
    },
)


def _amendment_id(congress: object, amendment_type: object, number: object) -> str:
    return f"{congress}-{str(amendment_type).lower()}-{number}"


def _amended(record: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = record.get(key)
    return value if isinstance(value, Mapping) else None


def _foreign_key(amended: Mapping[str, Any] | None) -> str | None:
    """The natural key of the measure an amendment amends, or NULL.

    A bill and an amendment spell their keys the same way -- congress, lowercase
    type, number -- so one builder serves both columns.  A partial reference
    answers NULL rather than a key with ``None`` inside it, which would look
    like a row that exists.
    """
    if amended is None:
        return None
    congress, amended_type, number = (amended.get(name) for name in ("congress", "type", "number"))
    if congress is None or amended_type is None or number is None:
        return None
    return _amendment_id(congress, amended_type, number)


def shape_amendment(record: Mapping[str, Any]) -> Row:
    """One ``amendments`` row from the amendment list route's exact publisher dict.

    ``status`` is dropped rather than published: BillTrax hardcoded it to
    ``"Proposed"`` at every write, so the column said nothing about any row.
    """
    latest = record.get("latestAction")
    latest = latest if isinstance(latest, Mapping) else {}
    sponsors = record.get("sponsors")
    sponsor = sponsors[0] if isinstance(sponsors, list) and sponsors and isinstance(sponsors[0], Mapping) else {}
    amended_bill = _amended(record, "amendedBill")
    amended_amendment = _amended(record, "amendedAmendment")
    amendment_type = record.get("type")
    return {
        "amendment_id": _amendment_id(record.get("congress"), amendment_type, record.get("number")),
        "congress": text(record.get("congress")),
        "amendment_type": None if amendment_type is None else str(amendment_type).lower(),
        "amendment_number": text(record.get("number")),
        "purpose": text(record.get("purpose")),
        "description": text(record.get("description")),
        "proposed_date": text(record.get("proposedDate")),
        "submitted_date": text(record.get("submittedDate")),
        "chamber": text(record.get("chamber")),
        "update_date": text(record.get("updateDate")),
        "latest_action_date": text(latest.get("actionDate")),
        "latest_action_text": text(latest.get("text")),
        "sponsor_bioguide_id": text(sponsor.get("bioguideId")),
        "sponsor_full_name": text(sponsor.get("fullName")),
        "sponsor_party": text(sponsor.get("party")),
        "amended_bill_id": _foreign_key(amended_bill),
        "amended_amendment_id": _foreign_key(amended_amendment),
        "url": text(record.get("url")),
    }


def press_release_id(chamber: str, link: str) -> str:
    """The identity C7 replaced a truncated-URL unique key with."""
    identity = digest(joined((chamber, link)))
    assert identity is not None  # digest answers None only for a None input
    return identity


def shape_press_release(
    release: object,
    channel: object,
    *,
    feed: object,
    observed_at: str,
    match: object | None = None,
) -> Row:
    """One ``press_releases`` row: the item, the channel around it, and the bill it names.

    Every channel-level field BillTrax dropped entirely is a column here, and
    neither the title nor the body is shortened.  ``match`` is a
    ``ReleaseMatch`` or ``None`` when no matching pass ran.
    """
    return {
        "release_id": press_release_id(release.chamber, release.link),
        "chamber": text(release.chamber),
        "feed_url": text(feed.url),
        "channel_title": text(channel.title),
        "channel_link": text(channel.link),
        "channel_description": text(channel.description),
        "channel_language": text(channel.language),
        "channel_copyright": text(channel.copyright),
        "channel_docs": text(channel.docs),
        "channel_last_build_date": text(channel.last_build_date),
        "channel_ttl": text(channel.ttl),
        "channel_skip_days": joined(channel.skip_days) or None,
        "channel_skip_hours": joined(str(hour) for hour in channel.skip_hours) or None,
        "item_index": text(release.index),
        "title": text(release.title),
        "link": text(release.link),
        "guid": text(release.guid),
        "guid_is_permalink": flag(release.guid_is_permalink),
        "description": text(release.description),
        "description_text": text(release.description_text),
        "description_chars": text(None if release.description_text is None else len(release.description_text)),
        "pub_date": text(release.pub_date),
        "pub_date_instant": (None if release.pub_date_instant is None else release.pub_date_instant.isoformat()),
        "author": text(release.author),
        "creator": text(release.creator),
        "categories_json": json_column(list(release.categories)),
        "enclosure_url": text(release.enclosure_url),
        "enclosure_length": text(release.enclosure_length),
        "enclosure_type": text(release.enclosure_type),
        "observed_at": text(observed_at),
        "bill_id": None if match is None or match.bill is None else bill_key(match.bill),
        "match_rule": text(None if match is None else match.rule),
        "matched_field": text(None if match is None else match.matched_field),
        "matched_text": text(None if match is None else match.matched_text),
    }


def vote_id(vote: object) -> str:
    """Natural key for one roll call: congress, chamber, session, roll number."""
    return f"{vote.congress}-{vote.chamber}-{vote.session}-{vote.roll_number}"


def folded_tally(tallies: Mapping[str, Any] | None) -> dict[str, Any]:
    """Fold one publisher's own count names onto the four published columns.

    A count name neither publisher uses is ignored rather than guessed at: the
    unfolded mapping stays on the source record, so a new bucket shows up as a
    missing column here and not as a number in the wrong one.
    """
    folded: dict[str, Any] = {}
    for name, value in (tallies or {}).items():
        column = TALLY_COLUMNS.get(name)
        if column is not None:
            folded[column] = value
    return folded


def shape_roll_call_vote(
    vote: object,
    *,
    match: object = None,
    tally: Mapping[str, Any] | None = None,
    member_vote_count: int | None = None,
    source_url: str | None = None,
    question: str | None = None,
    result: str | None = None,
    vote_date: str | None = None,
    action_index: int | None = None,
    conflict_count: int | None = None,
) -> Row:
    """One ``roll_call_votes`` row: the publisher's roll call, and the bill it refers to.

    ``vote`` carries the four identity fields -- a ``VoteKey``, or the
    ``RollCallVote`` itself, in which case its own ``question``, ``result``,
    ``date`` and ``source_url`` are read from it unless the caller overrides
    them.  A ``VoteKey`` states none of those, so a linkage-only row (the
    reference landed before the file did) leaves them NULL.

    ``tally`` is the publisher's own counts mapping, as ``RollCallVote.tallies``
    spells them; it is folded here, not on the source record, so nothing about
    which bucket a publisher meant is lost before this point.  ``action_index``
    and ``conflict_count`` are passed in because ``VoteMatch`` carries neither:
    the index lives on the ``VoteReference`` that won, and the conflict count on
    the ``VoteIndex`` that settled them.
    """
    counts = folded_tally(tally)

    def stated(given: object, own: str, matched: str | None = None) -> object:
        if given is not None:
            return given
        from_vote = getattr(vote, own, None)
        return from_vote if from_vote is not None else getattr(match, matched or own, None)

    return {
        "vote_id": vote_id(vote),
        "congress": text(vote.congress),
        "chamber": text(vote.chamber),
        "session": text(vote.session),
        "roll_number": text(vote.roll_number),
        "vote_date": text(stated(vote_date, "date")),
        "source_url": text(stated(source_url, "source_url", "url")),
        "question": text(stated(question, "question")),
        "result": text(stated(result, "result")),
        "yea": text(counts.get("yea")),
        "nay": text(counts.get("nay")),
        "present": text(counts.get("present")),
        "not_voting": text(counts.get("not_voting")),
        "tallies_json": json_column(dict(tally or {})),
        "member_vote_count": text(member_vote_count),
        "bill_id": None if match is None or match.bill is None else bill_key(match.bill),
        "match_rule": text(None if match is None else match.rule),
        "match_action_index": text(action_index),
        "match_url": text(None if match is None else match.url),
        "conflict_count": text(conflict_count),
    }


def member_key(member: object) -> str:
    """The non-null identity part ``member_votes`` keys on.

    The *file-stated* id wins, not the best id available: ``lis:`` plus the LIS
    id for a Senate record, the bare bioguide id for a House one, and ``name:``
    plus the publisher's own name only where the file states neither.

    That order matters more than it looks.  A Senate record's bioguide id comes
    from the crosswalk, and roughly four of ninety-nine voters on any one roll
    call do not resolve -- a member who has just left the current roster.
    Preferring the bioguide would give such a member ``name:...`` on the run
    where the crosswalk missed and a bioguide on the run where it hit, so one
    vote would become two permanent rows.  The LIS id is on the page either way.
    The bioguide keeps its own column, where changing is a correction rather
    than a new row.
    """
    lis = member.lis_id
    if lis:
        return f"lis:{lis}"
    bioguide = member.bioguide_id
    if bioguide:
        return str(bioguide)
    return f"name:{member.name}"


def shape_member_vote(member: object, *, vote: object, vote_date: str | None = None) -> Row:
    """One ``member_votes`` row: how one member voted on one roll call.

    ``position`` keeps the publisher's own word -- the Clerk spells Aye/No on
    some recorded votes and Yea/Nay on others -- and ``position_normalized``
    carries the fold the reader already computed, so a count and a quotation
    are both answerable from the row.
    """
    return {
        "vote_id": vote_id(vote),
        "congress": text(vote.congress),
        "chamber": text(vote.chamber),
        "session": text(vote.session),
        "roll_number": text(vote.roll_number),
        "member_key": member_key(member),
        "bioguide_id": text(member.bioguide_id),
        "lis_id": text(member.lis_id),
        "member_name": text(member.name),
        "party": text(member.party),
        "state": text(member.state),
        "position": text(member.vote),
        "position_normalized": text(member.vote_normalized),
        "vote_date": text(vote_date if vote_date is not None else getattr(vote, "date", None)),
    }


__all__ = [
    "AMENDMENTS",
    "MEMBER_VOTES",
    "PRESS_RELEASES",
    "ROLL_CALL_VOTES",
    "TALLY_COLUMNS",
    "folded_tally",
    "member_key",
    "press_release_id",
    "shape_amendment",
    "shape_member_vote",
    "shape_press_release",
    "shape_roll_call_vote",
    "vote_id",
]
