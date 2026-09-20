"""One House committee meeting as docs.house.gov states it: the agenda, typed.

The Committee Repository publishes one XML record per House committee meeting,
and that record is the only place the *agenda* is stated as data: a
``<meeting-document type="BR">`` is a measure noticed for the meeting, with its
``<legis-num>``, its ``<description>`` and a ``BILLS-…pdf`` file whose name
restates the number. Everything else in the record -- the subcommittee, the
calendar date, the meeting type -- is what makes the row checkable against the
transcript's own GovInfo MODS before anything joins the two.

**The event id is Congress.gov's, measured rather than assumed.** 9 of 9
sampled ``associatedMeeting.eventId`` values resolved here, and all 9 passed a
*committee-and-date* identity check rather than a status check: the XML's
``<calendar-date>`` equalled the CHRG MODS ``heldDate`` and
``<committee-name id>``'s parent code equalled the MODS ``congCommittee``
authority id under :func:`parent_committee_code`. Neither publisher documents
the equality -- Congress.gov's own endpoint documentation never mentions
docs.house.gov, and its OpenAPI spec spells the field ``eventid`` while the
wire spells it ``eventId`` -- so it is a measured regularity, and the check
belongs on every row rather than in a one-time assumption
([the measurement](../../../../docs/research/hearing-bill-linkage-2026-09-20.md)).

**The rendition is a plain keyless GET, checked by digest and not by status.**
The event page offers the XML only as an ASP.NET ``__doPostBack`` control, with
no ``.xml`` href anywhere on it; the same document is also a static file at
:data:`MEETING_XML`, and the two are byte-identical, **2 of 2 by SHA-256**.
That comparison is the check because this publisher serves its own pages at
HTTP 200, so a status code establishes nothing. Only the GET is addressed here;
the postback is the publisher's own control and needs a page's form state.

**Finding the address for a first fetch is a separate problem and is not
solved here.** :func:`house_meeting_xml_locator` needs the *subcommittee* code
and the calendar date, and a CHRG MODS states neither -- it states the parent
committee (``hsvr00``) and the held date. The two routes that do state the
whole address are the event page (behind the postback) and the per-committee
feed ``docs.house.gov/Committee/RSS.ashx?Code={code}``, whose every item's
``<enclosure>`` is exactly this locator (200, RSS 2.0, 26 items for ``VR00``).
Neither is read here; :func:`locator_from_meeting` rebuilds the address from a
record already in hand, which is what a re-fetch and a resume need.

**A type-less ``<legis-num>`` is refused, not guessed.** Some committees post
``<legis-num>226</legis-num>`` beside ``BILLS-118226ih.pdf`` -- neither states
whether the measure is a House or a Senate one. The long-standing community
scraper defaults that to ``hr``
([`unitedstates/congress`](https://github.com/unitedstates/congress/blob/master/congress/tasks/committee_meetings.py));
here it falls through to the ``<description>``, which usually spells the
designator in full (``H.R.226, Veterans Collaboration Act (Rep. Wittman)``), and
is refused with a stated reason when nothing does. The ``BILLS-118Xih.pdf``
discussion drafts are the case where nothing does: they name a measure with no
number at all, and 10 of 46 retained ``BR`` documents are one of those.

For meeting XML of ``M`` bytes the read is ``O(M)`` time and space through the
shared bounded scanner; every function here is offline and makes no request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from spicy_docs.interpretation.citations import CITATION_RULES_BY_NAME, bill_type_and_number
from spicy_docs.reading.xml_tree import XmlTreeElement, read_xml_tree
from spicy_docs.schemas.tables import natural_key

#: The keyless static address of one meeting's XML, as the publisher's own
#: ``/meetings/`` tree spells it. The committee segment is the subcommittee
#: code's first two characters, which is how the publisher nests ``VR10`` under
#: ``VR`` and ``II10`` under ``II``.
MEETING_XML = (
    "https://docs.house.gov/meetings/{committee}/{subcommittee}/{date}/{event_id}/"
    "{meeting_type}-{congress}-{subcommittee}-{date}.xml"
)

#: The root element of a meeting record.
MEETING_ROOT = "committee-meeting"

DEFAULT_MAX_BYTES = 4 * 1024 * 1024
MAX_MEETING_BYTES = 64 * 1024 * 1024
MAX_ELEMENTS = 100_000

#: ``BR`` is the publisher's own type code for a measure on the agenda. The
#: other codes retained here are ``SD`` (a hearing notice or supporting
#: document), ``HT`` (the hearing transcript) and ``AM`` (an amendment); only
#: ``BR`` names a bill, and nothing else is read as one.
AGENDA_DOCUMENT_TYPE = "BR"

_EVENT_ID = re.compile(r"[0-9]{1,9}")
_COMMITTEE_CODE = re.compile(r"[A-Z]{2}[0-9]{2}")
_MEETING_TYPE = re.compile(r"[A-Z]{2,6}")
_CALENDAR_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
#: The designator inside a ``BILLS-{congress}{TYPE}{number}{stage}.pdf`` file
#: name. The type group is optional because the type-less spelling exists and
#: has to be *recognised* in order to be refused; see the module docstring.
_BILLS_FILE = re.compile(r"BILLS-(?P<congress>[0-9]{3})(?P<type>[A-Za-z]{1,8})?(?P<number>[0-9]{1,5})[a-z]{0,4}\.")
#: The measured ``bill_number`` citation rule itself, taken rather than
#: respelled: a repository ``<description>`` is prose, the same prose a
#: committee print writes, and one designator must reduce to one key whichever
#: document it was read in. Its nine rejects (``HR974``, ``S. Smith``, ...)
#: therefore apply here too.
_BILL_NUMBER = CITATION_RULES_BY_NAME["bill_number"]


class HouseCommitteeRepositoryError(ValueError):
    """The bytes cannot establish one House committee meeting record."""


@dataclass(frozen=True, slots=True)
class HouseMeetingLocator:
    """Every part of a meeting XML address, as the publisher spells each one.

    ``subcommittee`` is the four-character code the record's own
    ``<committee-name id>`` carries (``VR10``); a full committee sets its own
    code with ``00`` in the last two positions (``GO00``), which is how the
    publisher addresses a meeting of the full committee.
    """

    congress: int
    meeting_type: str
    subcommittee: str
    calendar_date: str
    event_id: str

    def __post_init__(self) -> None:
        if isinstance(self.congress, bool) or not isinstance(self.congress, int) or self.congress <= 0:
            raise HouseCommitteeRepositoryError("congress must be a positive integer")
        for value, pattern, label in (
            (self.meeting_type, _MEETING_TYPE, "meeting_type"),
            (self.subcommittee, _COMMITTEE_CODE, "subcommittee"),
            (self.calendar_date, _CALENDAR_DATE, "calendar_date"),
            (self.event_id, _EVENT_ID, "event_id"),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise HouseCommitteeRepositoryError(f"{label} is not the shape docs.house.gov states: {value!r}")

    @property
    def committee(self) -> str:
        """The two-character committee segment the ``/meetings/`` tree nests under."""
        return self.subcommittee[:2]

    @property
    def path_date(self) -> str:
        """The calendar date as the path spells it, ``yyyymmdd``."""
        return self.calendar_date.replace("-", "")


#: The two containers a meeting states its committee under, in the order they
#: are read. A full committee's meeting nests ``<committee-name>`` under
#: ``<committees>`` and states no ``parent-id``; a subcommittee's nests it
#: under ``<subcommittees>`` and states one (measured on all 9 retained
#: events: 7 subcommittee, 2 full committee). Both are kept, and which one
#: stated a body is kept with it, because *subcommittee* hearings are exactly
#: the ones Congress.gov's own action list most often omits.
COMMITTEE_CONTAINERS = ("committees", "subcommittees")


@dataclass(frozen=True, slots=True)
class HouseMeetingCommittee:
    """One ``<committee-name>``: the body that met, and the full committee it sits under.

    ``parent_id`` is the publisher's own ``parent-id`` attribute where it
    states one, and ``None`` on a full-committee meeting, which states no
    parent. :func:`parent_committee_code` is what turns either into the
    ``system_code`` spelling Congress.gov and this repository's ``committees``
    table use, so the two publishers' codes are compared and not assumed equal.
    ``container`` is which of :data:`COMMITTEE_CONTAINERS` stated this body.
    """

    id: str
    parent_id: str | None
    parent_name: str | None
    name: str
    container: str


@dataclass(frozen=True, slots=True)
class HouseMeetingDocument:
    """One ``<meeting-document>`` as the publisher typed it, with any bill it names.

    ``bill_id`` is ``None`` on every document the rule refused, and
    ``refusal`` then says why in the publisher's own terms, so a row that
    produced no link is readable rather than merely absent.
    """

    type: str
    description: str | None
    legis_num: str | None
    file_urls: tuple[str, ...]
    bill_id: str | None
    bill_id_rule: str | None
    evidence_text: str | None
    refusal: str | None


@dataclass(frozen=True, slots=True)
class HouseCommitteeMeeting:
    """One meeting record whole: its identity, the body that met, and its agenda."""

    event_id: str
    congress: int
    session: str | None
    meeting_type: str
    calendar_date: str | None
    start_time: str | None
    title: str | None
    committees: tuple[HouseMeetingCommittee, ...]
    documents: tuple[HouseMeetingDocument, ...]

    @property
    def agenda_documents(self) -> tuple[HouseMeetingDocument, ...]:
        """Every ``type="BR"`` document, in the publisher's own document order."""
        return tuple(document for document in self.documents if document.type == AGENDA_DOCUMENT_TYPE)

    @property
    def parent_committee_codes(self) -> tuple[str, ...]:
        """Every distinct full-committee ``system_code`` this meeting's bodies belong to."""
        codes = {code for committee in self.committees if (code := parent_committee_code(committee.id))}
        return tuple(sorted(codes))


def parent_committee_code(committee_id: str | None) -> str | None:
    """``VR10`` is ``hsvr00``: the ``docs_house_parent_code`` rule, measured 9 of 9.

    docs.house.gov states the *subcommittee* that met; GovInfo MODS and
    Congress.gov state the full committee's ``system_code``. The first two
    characters are the committee and the last two the subcommittee, so the
    parent is ``hs`` plus the committee lower-cased plus ``00`` -- which held
    on every one of the nine sampled events, each checked against that
    hearing's own MODS ``congCommittee`` rather than assumed.
    """
    if not isinstance(committee_id, str) or _COMMITTEE_CODE.fullmatch(committee_id) is None:
        return None
    return f"hs{committee_id[:2].lower()}00"


def house_meeting_xml_locator(locator: HouseMeetingLocator) -> str:
    """The keyless static address of one meeting's XML; this route takes no credential."""
    if not isinstance(locator, HouseMeetingLocator):
        raise TypeError("locator must be a HouseMeetingLocator")
    return MEETING_XML.format(
        committee=locator.committee,
        subcommittee=locator.subcommittee,
        date=locator.path_date,
        event_id=locator.event_id,
        meeting_type=locator.meeting_type,
        congress=locator.congress,
    )


def locator_from_meeting(meeting: HouseCommitteeMeeting) -> HouseMeetingLocator:
    """Rebuild one meeting's own address from the record, for a re-fetch or a resume.

    Refuses rather than guesses when the record states no date or no committee
    code: an address built from a missing part is a guessed URL, and a probe
    built on a guessed URL proves nothing about the publisher.

    A ``<subcommittees>`` entry wins over a ``<committees>`` one, because the
    publisher files a subcommittee meeting's XML under the *subcommittee's*
    path segment (``/VR/VR10/``) and a record stating both would otherwise
    build the parent's address, which is a different document. None of the 10
    retained records states both, so this is a rule chosen from the path
    grammar rather than one measured against a record that exercises it.
    """
    if not isinstance(meeting, HouseCommitteeMeeting):
        raise TypeError("meeting must be a HouseCommitteeMeeting")
    if meeting.calendar_date is None:
        raise HouseCommitteeRepositoryError(f"meeting {meeting.event_id} states no calendar-date to address it by")
    by_container = {committee.container: committee.id for committee in reversed(meeting.committees)}
    code = by_container.get("subcommittees") or by_container.get("committees")
    if code is None:
        raise HouseCommitteeRepositoryError(f"meeting {meeting.event_id} names no committee to address it by")
    return HouseMeetingLocator(
        congress=meeting.congress,
        meeting_type=meeting.meeting_type,
        subcommittee=code,
        calendar_date=meeting.calendar_date,
        event_id=meeting.event_id,
    )


def bill_key_from_bills_file(url: str | None, *, congress: int | str | None = None) -> str | None:
    """``BILLS-118HR188ih.pdf`` is ``118-hr-188``; the type-less spelling is ``None``.

    The file name states its own Congress, so ``congress`` is only a
    cross-check: a name whose Congress disagrees with the caller's is refused
    rather than published under either, because the two statements cannot both
    be right and nothing here can settle which is.
    """
    if not url:
        return None
    match = _BILLS_FILE.search(url.rsplit("/", 1)[-1])
    if match is None or not match.group("type"):
        return None
    parts = bill_type_and_number(f"{match.group('type')}{match.group('number')}")
    if parts is None:
        return None
    stated = int(match.group("congress"))
    if congress is not None and str(congress).isdecimal() and int(congress) != stated:
        return None
    return natural_key(stated, *parts)


def bill_key_from_designator(text: str | None, congress: int | str | None) -> str | None:
    """The first full bill designator in a string, stamped with the caller's Congress.

    The pattern is the citation rules' own ``CONGRESS_CHAMBER``, so
    ``H.R.226`` in a repository description and ``H.R. 226`` in a committee
    print reduce to one key. Without a Congress there is no key: a bare
    designator names a measure only inside one.
    """
    if not text or congress is None or not str(congress).isdecimal():
        return None
    match = _BILL_NUMBER.compiled().search(text)
    if match is None:
        return None
    parts = bill_type_and_number(match.group(0))
    return None if parts is None else natural_key(int(congress), *parts)


def _child_text(element: XmlTreeElement, name: str) -> str | None:
    child = next((item for item in element.children if item.name == name), None)
    return None if child is None else (child.text.strip() or None)


def _read_committee(element: XmlTreeElement, *, container: str) -> HouseMeetingCommittee | None:
    code = element.attribute("id")
    if not code:
        return None
    return HouseMeetingCommittee(
        id=code,
        parent_id=element.attribute("parent-id"),
        parent_name=element.attribute("parent-name"),
        name=element.text.strip(),
        container=container,
    )


def _read_document(element: XmlTreeElement, *, congress: int) -> HouseMeetingDocument:
    """One ``<meeting-document>``, with the bill key its own three statements settle.

    The three are tried strongest first: the ``BILLS-…pdf`` file name, which is
    the publisher's own machine-written form; the ``<legis-num>``, which is
    sometimes the bare number; and the ``<description>``, which is prose but
    usually spells the designator in full. ``bill_id_rule`` records which one
    answered, because they are not equally strong and a consumer wanting only
    the machine-written form has to be able to filter on it.

    The file-name rule is the receipt's own, unwidened: a committee that
    appends a short title (``BILLS-118HR3522ih-FIRESHEDSAct.pdf``) puts the
    extension out of the pattern's reach, so 4 of the 8 resolved documents on
    the fixture record fall through to their ``<legis-num>`` and reach the same
    key by the weaker route. Widening it would make the rule no longer the one
    that was measured, for a key the next candidate already supplies.
    """
    description = _child_text(element, "description")
    legis_num = _child_text(element, "legis-num")
    files = tuple(url for child in element.findall("files", "file") if (url := child.attribute("doc-url")) is not None)
    kind = element.attribute("type") or ""
    if kind != AGENDA_DOCUMENT_TYPE:
        # A hearing notice names the bills in its own description and is not a
        # bill on the agenda; only ``BR`` is, so nothing else is read as one.
        return HouseMeetingDocument(kind, description, legis_num, files, None, None, None, None)
    named = next(
        ((url, key) for url in files if (key := bill_key_from_bills_file(url, congress=congress))),
        None,
    )
    candidates: tuple[tuple[str, str, str | None], ...] = (
        *(() if named is None else (("docs_house_bills_filename", named[1], named[0].rsplit("/", 1)[-1]),)),
        *(
            (name, key, text)
            for name, text in (("docs_house_legis_num", legis_num), ("docs_house_description", description))
            if (key := bill_key_from_designator(text, congress))
        ),
    )
    rule, bill_id, evidence = candidates[0] if candidates else (None, None, None)
    refusal = (
        None
        if bill_id is not None
        else (
            "no file name, legis-num or description states a bill type and number: "
            f"legis-num={legis_num!r} file={(files[0].rsplit('/', 1)[-1] if files else None)!r}"
        )
    )
    return HouseMeetingDocument(kind, description, legis_num, files, bill_id, rule, evidence, refusal)


def parse_house_committee_meeting(body: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> HouseCommitteeMeeting:
    """Read one docs.house.gov meeting record whole, keeping the publisher's own order.

    Nothing is dropped and nothing is corrected: a document the bill rule
    refuses keeps its ``<legis-num>`` and its ``<description>`` with the reason
    beside it. ``meeting-id`` is checked against ``meeting-type`` and the event
    id it concatenates (``HHRG117409``), which is the record's own statement of
    the key it was requested under.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_MEETING_BYTES:
        raise HouseCommitteeRepositoryError("max_bytes must be a positive integer no greater than 64 MiB")
    root = read_xml_tree(
        body,
        expected_root=MEETING_ROOT,
        error_type=HouseCommitteeRepositoryError,
        label="House committee meeting",
        max_bytes=max_bytes,
        max_elements=MAX_ELEMENTS,
    ).element
    congress_raw = root.attribute("congress-num") or ""
    meeting_type = root.attribute("meeting-type") or ""
    meeting_id = root.attribute("meeting-id") or ""
    if not congress_raw.isdecimal():
        raise HouseCommitteeRepositoryError(f"meeting record states no numeric congress-num: {congress_raw!r}")
    if _MEETING_TYPE.fullmatch(meeting_type) is None:
        raise HouseCommitteeRepositoryError(f"meeting record states no meeting-type: {meeting_type!r}")
    event_id = meeting_id.removeprefix(meeting_type)
    if not meeting_id.startswith(meeting_type) or _EVENT_ID.fullmatch(event_id) is None:
        raise HouseCommitteeRepositoryError(
            f"meeting-id {meeting_id!r} is not its own meeting-type {meeting_type!r} plus an event id"
        )
    congress = int(congress_raw)
    details = root.findall("meeting-details")
    committees = tuple(
        committee
        for name in COMMITTEE_CONTAINERS
        for element in details
        for container in element.findall(name)
        for child in container.findall("committee-name")
        if (committee := _read_committee(child, container=name)) is not None
    )
    calendar_date = next(
        (
            value
            for element in details
            for date_element in element.findall("meeting-date")
            if (value := _child_text(date_element, "calendar-date")) and _CALENDAR_DATE.fullmatch(value)
        ),
        None,
    )
    start_time = next(
        (
            value
            for element in details
            for child in element.findall("meeting-date")
            if (value := _child_text(child, "start-time"))
        ),
        None,
    )
    title = next((value for element in details if (value := _child_text(element, "meeting-title"))), None)
    documents = tuple(
        _read_document(child, congress=congress)
        for container in root.findall("meeting-documents")
        for child in container.findall("meeting-document")
    )
    return HouseCommitteeMeeting(
        event_id=event_id,
        congress=congress,
        session=root.attribute("session-num"),
        meeting_type=meeting_type,
        calendar_date=calendar_date,
        start_time=start_time,
        title=title,
        committees=committees,
        documents=documents,
    )


__all__ = [
    "AGENDA_DOCUMENT_TYPE",
    "COMMITTEE_CONTAINERS",
    "MEETING_ROOT",
    "MEETING_XML",
    "HouseCommitteeMeeting",
    "HouseCommitteeRepositoryError",
    "HouseMeetingCommittee",
    "HouseMeetingDocument",
    "HouseMeetingLocator",
    "bill_key_from_bills_file",
    "bill_key_from_designator",
    "house_meeting_xml_locator",
    "locator_from_meeting",
    "parent_committee_code",
    "parse_house_committee_meeting",
]
