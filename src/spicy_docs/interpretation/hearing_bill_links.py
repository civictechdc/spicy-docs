"""Which bills a hearing was held on, per source, with the rule that said so.

A hearing has no ``PRIMARY`` bill because a hearing is not filed against one
bill. A legislative hearing is convened on a *list* -- twelve of them on
``CHRG-118hhrg56198`` -- and four publishers state that list. The measurement
this module carries into product code
([hearing-to-bill linkage](../../../docs/research/hearing-bill-linkage-2026-09-20.md),
198 requests, receipt ``hearing-bill-linkage-2026-09-20/``) asked which source
states it and what precision each one earns.

**Two rules are implemented, in the order the measurement ranked them.**

``mods_cover`` reads the package MODS's own ``<bill context="COVER">`` list --
the bills printed on the hearing's cover. It costs **no request at all**:
``GovInfoBodyAcquirer`` already fetches that MODS for every body it reads. Six
set-comparisons against a statement made by a *different* process (the
Congress.gov hearing title three times, the Daily Digest committee entry,
``relatedItems.bills``, the CHRG front page) were **6 of 6 set-equal over 55
bills**, and the bill's own action list confirms a *Hearings Held* action by
that committee on that date for **19 of 20** pairs.

``docs_house_br`` reads the House Committee Repository's per-event agenda, one
keyless GET per event ([the reader](../sources/congress/house_committee_repository.py)).
**It states intent, not outcome**, so its rows are ``noticed`` and never
``held_on``: where the agenda and the cover agree the bill side confirms 18 of
18, but where the agenda alone states a bill it confirms 1 of 18, contradicts 1
(``118-hr-2997``, noticed for 2023-05-23 and heard 2023-06-22) and is silent on
16. A consumer that wants what happened reads ``relation = 'held_on'``; a
consumer that wants what was scheduled reads both.

**A ``BODY`` mention is never a link.** ``BODY`` and ``OTHER`` are what the
transcript happens to cite, and **0 of 23** ``BODY``-only mentions carry a
confirming action. They are counted, not linked, and nothing here makes a row
from one.

**The identity check is per row, not per build.** ``docs.house.gov``'s
``EventID`` equalling Congress.gov's ``eventId`` is a measured regularity over
ten events that neither publisher documents, so :func:`agenda_links` refuses
unless *this* meeting's ``<calendar-date>`` equals *this* hearing's MODS
``heldDate`` and one of its committees' parent codes equals one of the MODS's
``congCommittee`` authority ids. A refusal is the only thing that would notice
the equality silently ceasing to hold.

**Three further sources are measured and not implemented**, named here so the
sealed vocabulary can take them without a rename: ``daily_digest_entry`` (the
only route reaching both chambers back to 1994, and the one that could close
the Senate gap), ``congress_related_items`` (the only Senate source measured,
and promotable only with the reverse jacket edge) and
``front_matter_designator`` (the transcript's own title page). Their measured
figures are in the note; nothing here produces a row under any of them.

For a MODS naming ``B`` bills and a meeting naming ``D`` documents, both rules
are ``O(B)`` and ``O(D)``: one pass, no re-parsing and no request.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from spicy_docs.schemas.committee_report_tables import CHAMBER_BY_DOCUMENT_TYPE
from spicy_docs.schemas.document_citation_tables import bill_key
from spicy_docs.sources.congress.house_committee_repository import HouseCommitteeMeeting

#: The MODS ``context`` marker a link is made from. Exactly one: ``PRIMARY``
#: never appears on a hearing (0 of 52 and 0 of 20, measured twice), and
#: ``BODY``/``OTHER`` are mentions the bill side confirms 0 of 23 times.
COVER_CONTEXT = "COVER"

#: What a row asserts about the pairing, sealed and additions-only. ``held_on``
#: is a statement about what happened, ``noticed`` about what was scheduled;
#: the distinction is the measured one between 19-of-20 and 1-of-18 bill-side
#: confirmation, so collapsing them would publish an agenda as an event.
RELATIONS: tuple[str, ...] = ("held_on", "noticed")


class HearingBillLinkError(ValueError):
    """Two records cannot be held to name the same hearing."""


@dataclass(frozen=True, slots=True)
class HearingBillLinkRule:
    """One source's rule: what it reads, what it asserts, and what it measured.

    ``name`` is the published ``link_source`` value and is part of every row's
    identity, so it is additions-only: renaming one rewrites rows that are
    already out. ``version`` moves when what the rule reads changes, and is a
    zero-padded decimal because the published column is compared as a string.
    ``measured`` is the sentence a consumer needs before trusting a row, kept
    beside the rule rather than only in the contract prose so the two cannot
    drift.
    """

    name: str
    version: str
    publisher: str
    relation: str
    reads: str
    measured: str
    implemented: bool = True

    def __post_init__(self) -> None:
        if self.relation not in RELATIONS:
            raise HearingBillLinkError(f"{self.name}: relation {self.relation!r} is not one of {RELATIONS}")


#: Every link source, measured or named. The first two are implemented; the
#: last three are the measurement's own build order beyond this branch and are
#: listed so the sealed vocabulary is complete from the start.
HEARING_BILL_LINK_RULES: tuple[HearingBillLinkRule, ...] = (
    HearingBillLinkRule(
        name="mods_cover",
        version="001",
        publisher="govinfo_mods",
        relation="held_on",
        reads='the package MODS root extension\'s <bill context="COVER"> list',
        measured=(
            "19 of 20 COVER pairs carry a Hearings Held action by that committee on that date, the one "
            "exception being a bill with three actions in total, so the bill side is silent rather than "
            "contradicting; 6 of 6 set-comparisons against an independently produced list are set-equal over "
            "55 bills. Recall is unmeasured: 2 of 20 sampled House hearings of the 118th carry a COVER bill "
            "at all, hearing type was never classified, and 0 of 3 sampled Senate hearings carry one."
        ),
    ),
    HearingBillLinkRule(
        name="docs_house_br",
        version="001",
        publisher="docs_house_gov",
        relation="noticed",
        reads='each <meeting-document type="BR">\'s file name, <legis-num> and <description>',
        measured=(
            "36 of 46 retained BR documents resolve to a bill key; the 10 that do not are the "
            "BILLS-118Xih.pdf discussion drafts, which name a measure with no number. Where the agenda and "
            "the cover agree the bill side confirms 18 of 18; where the agenda alone states a bill it "
            "confirms 1 of 18, contradicts 1 and is silent on 16, which is why these rows are noticed. "
            "Reach: only 9 of 20 sampled hearings state an eventId at all, and how far back the Repository "
            "goes is unmeasured."
        ),
    ),
    HearingBillLinkRule(
        name="daily_digest_entry",
        version="001",
        publisher="govinfo_crec",
        relation="held_on",
        reads="the committee entry in a Daily Digest House or Senate Committee Meetings granule",
        measured=(
            "12 of 12 on the one entry cross-checked, set-equal to that transcript's COVER list; 4 of 16 "
            "entries on that date carry a bill. One date, one committee: the parse's error rate is "
            "unmeasured. Not implemented."
        ),
        implemented=False,
    ),
    HearingBillLinkRule(
        name="congress_related_items",
        version="001",
        publisher="congress_gov",
        relation="held_on",
        reads="a committee-meeting detail's relatedItems.bills",
        measured=(
            "10 of 60 sampled meetings state a bill and it is the only Senate source measured, but the "
            "meeting-to-jacket edge is many-valued: 1 of 5 pointed at a transcript that names no meeting, so "
            "a row needs the hearing's own reverse eventId edge first. Not implemented."
        ),
        implemented=False,
    ),
    HearingBillLinkRule(
        name="front_matter_designator",
        version="001",
        publisher="govinfo_chrg",
        relation="held_on",
        reads="the bill designators printed on the transcript's first page",
        measured=(
            "12 of 12 on one front page, equal to COVER and to the Congress.gov title. A hearing titled only "
            "LEGISLATIVE HEARING states nothing and the rule cannot tell held-on from mentioned-in-the-title, "
            "so it ranks below COVER. Not implemented."
        ),
        implemented=False,
    ),
)

HEARING_BILL_LINK_RULES_BY_NAME = {rule.name: rule for rule in HEARING_BILL_LINK_RULES}

#: The sealed, additions-only ``link_source`` vocabulary, in rank order.
LINK_SOURCES: tuple[str, ...] = tuple(rule.name for rule in HEARING_BILL_LINK_RULES)


def _rule_set_version(rules: Sequence[HearingBillLinkRule]) -> str:
    """A digest over every rule's name, version, publisher, relation and reader.

    Derived rather than written, the way ``citations.py``'s
    ``CITATION_RULE_SET_VERSION`` is: changing what a rule reads or what it
    asserts moves this even when someone forgets to move that rule's own
    ``version``, and the pinned assertion in the tests then names both. What it
    cannot see is a change *inside* :func:`cover_links` or :func:`agenda_links`
    that leaves the rule record untouched; that is what the per-rule ``version``
    is for. Twelve hex characters is 48 bits over a five-row input.
    """
    joined = "\n".join(
        f"{rule.name}|{rule.version}|{rule.publisher}|{rule.relation}|{rule.reads}|{int(rule.implemented)}"
        for rule in rules
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


#: The identity of the whole rule set, published on every row.
HEARING_BILL_LINK_RULE_VERSION = _rule_set_version(HEARING_BILL_LINK_RULES)


@dataclass(frozen=True, slots=True)
class HearingBillLink:
    """One (hearing, bill, source) statement, with the join key it was checked on.

    Everything but ``bill_id``, ``evidence_text`` and ``evidence_rule``
    describes the *hearing* and is the same on every row of one package under
    one source, which is what makes ``(package_id, bill_id, link_source)`` the
    identity: two sources naming the same pair is the strongest evidence this
    measurement found, and collapsing them to one row would delete it.
    """

    package_id: str
    congress: int | None
    chamber: str | None
    committee_system_code: str | None
    held_date: str | None
    event_id: str | None
    bill_id: str
    link_source: str
    relation: str
    evidence_rule: str
    evidence_text: str | None
    rule_version: str


def _committee_system_code(mods: object) -> str | None:
    """The ``authorityId`` of the first ``congCommittee`` the MODS names."""
    return next((committee.authority_id for committee in getattr(mods, "committees", ())), None)


def _committee_system_codes(mods: object) -> frozenset[str]:
    return frozenset(str(committee.authority_id).lower() for committee in getattr(mods, "committees", ()))


def _hearing_facts(mods: object) -> dict[str, object]:
    """The columns every link row of one hearing repeats, read off the MODS once."""
    identity = mods.identity
    return {
        "package_id": identity.package_id,
        "congress": identity.congress,
        "chamber": CHAMBER_BY_DOCUMENT_TYPE.get(identity.document_type or ""),
        "committee_system_code": _committee_system_code(mods),
        "held_date": getattr(mods, "held_date", None),
    }


def _links(
    mods: object,
    *,
    rule: HearingBillLinkRule,
    event_id: str | None,
    found: Iterable[tuple[str, str, str | None]],
) -> tuple[HearingBillLink, ...]:
    """One row per distinct bill, in the publisher's own order, first statement kept."""
    facts = _hearing_facts(mods)
    rows: dict[str, HearingBillLink] = {}
    for key, evidence_rule, evidence_text in found:
        rows.setdefault(
            key,
            HearingBillLink(
                **facts,  # type: ignore[arg-type]
                event_id=event_id,
                bill_id=key,
                link_source=rule.name,
                relation=rule.relation,
                evidence_rule=evidence_rule,
                evidence_text=evidence_text,
                rule_version=HEARING_BILL_LINK_RULE_VERSION,
            ),
        )
    return tuple(rows.values())


def cover_links(mods: object, *, event_id: str | None = None) -> tuple[HearingBillLink, ...]:
    """Every ``mods_cover`` link one package MODS states, in document order.

    ``mods`` is read structurally -- the shape
    ``sources.govinfo.bodies.PackageModsIdentity`` has -- so a caller holding
    a record this repository already fetched for the body needs no second
    request and no second parse. A MODS stating no ``COVER`` bill yields no
    rows, which is the correct answer for an oversight hearing and an unmarked
    gap on the Senate: **3 of 3 sampled Senate CHRG MODS state no bill in any
    context**, and nothing in a row says which of the two silences it is.
    ``event_id`` is the Congress.gov ``associatedMeeting.eventId`` the caller
    read, carried so an agenda row and a cover row for one hearing join; the
    MODS itself never states one.
    """
    rule = HEARING_BILL_LINK_RULES_BY_NAME["mods_cover"]
    found = (
        (bill_key(bill), "mods_bill_context", bill.context)
        for bill in getattr(mods, "bills", ())
        if bill.context == COVER_CONTEXT
    )
    return _links(mods, rule=rule, event_id=event_id, found=found)


def check_meeting_identity(mods: object, meeting: HouseCommitteeMeeting) -> None:
    """Prove the docs.house.gov record and the CHRG MODS name one hearing, or refuse.

    Two conditions, both the publishers' own statements about the event and
    neither of them the request URL: the meeting's ``<calendar-date>`` must
    equal the MODS ``heldDate``, and one of the meeting's committees' parent
    codes must be one of the MODS's ``congCommittee`` authority ids. Held 9 of
    9 on the sampled events. Checked per row rather than assumed once, because
    the id equality this reaches through is documented by neither publisher.
    """
    if not isinstance(meeting, HouseCommitteeMeeting):
        raise TypeError("meeting must be a HouseCommitteeMeeting")
    held = getattr(mods, "held_date", None)
    package_id = mods.identity.package_id
    if not held or meeting.calendar_date != held:
        raise HearingBillLinkError(
            f"meeting {meeting.event_id} states calendar-date {meeting.calendar_date!r} and {package_id} "
            f"states heldDate {held!r}; they are not the same event"
        )
    codes = _committee_system_codes(mods)
    parents = frozenset(meeting.parent_committee_codes)
    if not codes or not parents or not (codes & parents):
        raise HearingBillLinkError(
            f"meeting {meeting.event_id} names committees {sorted(parents)} and {package_id} names "
            f"{sorted(codes)}; they are not the same committee"
        )


def agenda_links(mods: object, meeting: HouseCommitteeMeeting) -> tuple[HearingBillLink, ...]:
    """Every ``docs_house_br`` link one meeting's agenda states, after the identity check.

    Rows are ``noticed``: this is the agenda, and a bill noticed and dropped
    stays on it. A ``BR`` document the bill rule refused produces no row and
    keeps its reason on
    ``sources.congress.house_committee_repository.HouseMeetingDocument.refusal``,
    so nothing is dropped silently.
    """
    check_meeting_identity(mods, meeting)
    rule = HEARING_BILL_LINK_RULES_BY_NAME["docs_house_br"]
    found = (
        (document.bill_id, document.bill_id_rule or rule.name, document.evidence_text)
        for document in meeting.agenda_documents
        if document.bill_id is not None
    )
    return _links(mods, rule=rule, event_id=meeting.event_id, found=found)


__all__ = [
    "COVER_CONTEXT",
    "HEARING_BILL_LINK_RULES",
    "HEARING_BILL_LINK_RULES_BY_NAME",
    "HEARING_BILL_LINK_RULE_VERSION",
    "LINK_SOURCES",
    "RELATIONS",
    "HearingBillLink",
    "HearingBillLinkError",
    "HearingBillLinkRule",
    "agenda_links",
    "check_meeting_identity",
    "cover_links",
]
