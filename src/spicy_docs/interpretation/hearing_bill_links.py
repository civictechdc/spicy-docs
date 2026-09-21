"""Which bills a hearing was held on, per source, with the rule that said so.

A hearing has no ``PRIMARY`` bill because it is not filed against one, so four
publishers' statements of the list were measured and two rules implemented in
rank order: ``mods_cover`` reads the package MODS's own ``<bill
context="COVER">`` list at no request cost (6 of 6 set-equal against
independently produced lists, the bill side confirming 19 of 20 pairs), and
``docs_house_br`` reads the House Committee Repository's per-event agenda, one
keyless GET per event, whose rows are ``noticed`` and never ``held_on``
because the agenda states intent, not outcome (18 of 18 where it agrees with
the cover, 1 of 18 where it stands alone). A ``BODY`` mention is never a link
(0 of 23 carry a confirming action), and ``agenda_links`` refuses unless this
meeting's calendar date and committee codes match this hearing's MODS, because
the ``EventID``/``eventId`` equality it reaches through is documented by
neither publisher.
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

#: Every value ``hearing_bill_links.evidence_rule`` can carry: which statement
#: inside a source settled the key. The MODS states a key one way; the House
#: agenda states it three, in descending strength.
EVIDENCE_RULES: tuple[str, ...] = (
    "mods_bill_context",
    "docs_house_bills_filename",
    "docs_house_legis_num",
    "docs_house_description",
)


class HearingBillLinkError(ValueError):
    """Two records cannot be held to name the same hearing."""


@dataclass(frozen=True, slots=True)
class HearingBillLinkRule:
    """One source's rule: what it reads, what it asserts, and what it measured.

    ``name`` is the published ``link_source`` value and part of every row's
    identity, so it is additions-only: renaming one rewrites rows that are
    already out. ``version`` moves when what the rule reads changes, and is a
    zero-padded decimal because the published column is compared as a string.
    ``measured`` is the sentence a consumer needs before trusting a row, kept
    beside the rule so it cannot drift from the contract prose.
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

    Derived rather than written, so changing what a rule reads or asserts moves
    this even when someone forgets to move that rule's own ``version``; what it
    cannot see is a change *inside* :func:`cover_links` or :func:`agenda_links`
    that leaves the rule record untouched, which is what the per-rule
    ``version`` is for.
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


@dataclass(frozen=True, slots=True)
class _HearingFacts:
    """The five columns every link row of one hearing repeats, read off the MODS once."""

    package_id: str
    congress: int | None
    chamber: str | None
    committee_system_code: str | None
    held_date: str | None


def _hearing_facts(mods: object) -> _HearingFacts:
    identity = mods.identity
    return _HearingFacts(
        package_id=identity.package_id,
        congress=identity.congress,
        chamber=CHAMBER_BY_DOCUMENT_TYPE.get(identity.document_type or ""),
        committee_system_code=_committee_system_code(mods),
        held_date=getattr(mods, "held_date", None),
    )


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
                package_id=facts.package_id,
                congress=facts.congress,
                chamber=facts.chamber,
                committee_system_code=facts.committee_system_code,
                held_date=facts.held_date,
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
    ``sources.govinfo.bodies.PackageModsIdentity`` has -- so a caller holding a
    record this repository already fetched for the body needs no second request
    and no second parse. A MODS stating no ``COVER`` bill yields no rows, which
    is the correct answer for an oversight hearing and an unmarked gap on the
    Senate (3 of 3 sampled Senate CHRG MODS state no bill in any context), and
    nothing in a row says which silence it is; ``event_id`` is the Congress.gov
    ``associatedMeeting.eventId`` the caller read, carried so an agenda row and
    a cover row for one hearing join.
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
    codes must be one of the MODS's ``congCommittee`` authority ids (held 9 of
    9 on the sampled events). Checked per row rather than assumed once, because
    the id equality this reaches through is documented by neither publisher.
    Raises ``HearingBillLinkError`` on either mismatch and ``TypeError`` for a
    non-``HouseCommitteeMeeting``.
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


def _evidence_rule(document: object) -> str:
    """The reader that settled this document's key, held to the published vocabulary.

    The reader sets ``bill_id`` and ``bill_id_rule`` together, so a document
    with a key always names the statement that produced it. Stating a name
    outside ``EVIDENCE_RULES`` as a refusal rather than a fallback is
    deliberate: a fallback would publish the source name into ``evidence_rule``,
    which is not one of the values the column documents.
    """
    name = document.bill_id_rule
    if name not in EVIDENCE_RULES:
        raise HearingBillLinkError(
            f"a resolved agenda document names evidence rule {name!r}, which is not one of {EVIDENCE_RULES}"
        )
    return name


def agenda_links(mods: object, meeting: HouseCommitteeMeeting) -> tuple[HearingBillLink, ...]:
    """Every ``docs_house_br`` link one meeting's agenda states, after the identity check.

    Rows are ``noticed``: this is the agenda, and a bill noticed and dropped
    stays on it. A ``BR`` document the bill rule refused produces no row and
    keeps its reason on
    ``sources.congress.house_committee_repository.HouseMeetingDocument.refusal``,
    so nothing is dropped silently. Raises ``HearingBillLinkError`` or
    ``TypeError`` through :func:`check_meeting_identity`.
    """
    check_meeting_identity(mods, meeting)
    rule = HEARING_BILL_LINK_RULES_BY_NAME["docs_house_br"]
    found = tuple(
        (document.bill_id, _evidence_rule(document), document.evidence_text)
        for document in meeting.agenda_documents
        if document.bill_id is not None
    )
    return _links(mods, rule=rule, event_id=meeting.event_id, found=found)


__all__ = [
    "COVER_CONTEXT",
    "EVIDENCE_RULES",
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
