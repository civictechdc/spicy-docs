"""The Congress.gov index tables: communications, meetings, Record issues, treaties, nominations.

Five tables, each one row per record of one Congress.gov list or detail route
(``sources/congress/listing.py``), the way ``amendments`` is one row per
amendment-list record.  Four of them are read from two records at once: the
list row, the only place the publisher states ``url``, and the detail record,
which carries everything else and repeats the list row's identifying fields.
A shaper takes both and reads the detail's fields over the list row's, so a
list-only row still shapes with the detail's columns NULL, and a detail-only
record still shapes with ``url`` NULL.  A list-valued
column comes from the detail alone: NULL when no detail was read, ``[]`` when
the detail was read and states none -- the publisher omits ``matchingRequirements``
rather than sending an empty array, and the two cases must not look alike.

Decisions, each with its reason:

* ``house_communications`` is keyed ``(congress, communication_type, number)``,
  the publisher's own address ``house-communication/{congress}/{type}/{number}``,
  with the type lowercased the way the address spells it and ``amendments``
  spells its type.  The type is read off the record, never checked against a
  vocabulary here; the route module owns that vocabulary.
* ``is_rulemaking`` folds the publisher's ``"True"`` / ``"False"`` strings
  (those two spellings and no other on 18 of 18 sampled 2026-09-19) onto the
  one published truth spelling; any other spelling refuses rather than
  publishing a NULL that would read as "not stated".
* The RIN is an interpretation, so it arrives as an
  ``interpretation.communication_rin.RinFinding`` and lands as three columns
  (value, rule, matched text).  ``None`` means the rule was not run and all
  three are NULL, the way ``press_releases`` treats an absent match.
* ``committee_meetings`` is keyed ``(congress, chamber, event_id)``, the
  publisher's own address.  Event ids look unique on their own, but nothing
  has measured that across chambers, and an identity must not rest on a
  guess.  ``hearing_jacket`` is the first jacket the meeting lists and
  ``hearing_jackets_json`` every one: the map's ``meeting→hearing`` evidence
  is a meeting naming two jackets (63019 and 64431), so one column cannot be
  the whole fact.
* ``record_issues`` is keyed ``(volume, issue)``, the API's own identity for a
  Record issue (the map's comparison verdict: never key the Record on a
  date).  ``chambers`` is the legislative-day calendar, derived from the
  detail's section names by the rule the map's ``record→legislative-day``
  edge measured (:data:`SECTION_CHAMBERS`), and NULL rather than empty when
  no detail was read.
* ``treaties`` is keyed ``(congress_received, number, suffix)``, the
  publisher's address with its optional part suffix, spelled ``""`` when the
  record spells it so.  ``package_id`` is the GovInfo CDOC id the map's
  ``treaty→cdoc`` edge derived (``CDOC-{c}tdoc{n}``, 2 of 2), applied only to
  a treaty with no suffix because the suffixed form was never measured.
* ``nominations`` is keyed ``(congress, citation)``: the citation
  (``PN730-20``) is the publisher's own display key and already carries the
  part number; PN numbers restart each Congress.

Senate communications have no table here.  The detail record carries the
abstract, the committee referral and the Record date only -- no rulemaking
flag, legal authority, report nature, submitting agency or official, and no
matching requirement (measured on the captured EC 4712 and by the map's
``senate-communication→committee`` edge) -- so a ``senate_communications``
table could fill none of the columns that make ``house_communications`` the
regulatory bridge without inventing them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from spicy_docs.schemas.tables import (
    Row,
    TableContractError,
    flag,
    joined,
    json_column,
    natural_key,
    table_contract,
    text,
)

HOUSE_COMMUNICATIONS = table_contract(
    "house_communications",
    grain="One row per House executive communication, as the Congress.gov house-communication routes state it.",
    identity=("congress", "communication_type", "number"),
    version_column="update_date",
    columns={
        "communication_id": "Natural key: congress, lowercase communication type and number joined with hyphens.",
        "congress": "The numbered Congress the communication was received in.",
        "communication_type": (
            "The publisher's communication type code, lowercased the way its own address spells it (ec, ml, ...)."
        ),
        "communication_type_name": "The publisher's name for that type (Executive Communication, Memorial, ...).",
        "number": "The communication's number within its Congress and type.",
        "chamber": "The chamber, as the publisher spells it.",
        "session": "The session of Congress the communication was received in.",
        "abstract": "The publisher's abstract: the Record's own description of the communication.",
        "report_nature": "The nature of the report transmitted, where the detail states one; where the RIN is read from.",
        "legal_authority": (
            "The statutory authority the communication cites, where the detail states one; a Congressional "
            "Review Act rule submission cites 5 U.S.C. 801(a)(1)(A)."
        ),
        "submitting_agency": "The agency that submitted the communication, where the detail states one.",
        "submitting_official": "The official who submitted it, where the detail states one.",
        "congressional_record_date": "The date the communication appeared in the Congressional Record.",
        "is_rulemaking": (
            "Whether the publisher flags the communication as a rulemaking: the publisher's `True`/`False` strings "
            "folded onto the one published truth spelling; any other spelling refuses."
        ),
        "referral_system_code": "System code of the first committee the communication was referred to.",
        "referral_committee_name": "That committee's name as the publisher spells it.",
        "referral_date": "The date of that referral.",
        "referral_count": "How many committees the detail lists; every one is in committees_json.",
        "committees_json": "Every committee referral the detail lists, as a JSON array of the publisher's objects.",
        "matching_requirement_number": "Number of the first House reporting requirement the communication matches.",
        "matching_requirement_count": "How many requirements the detail lists; every one is in matching_requirements_json.",
        "matching_requirements_json": "Every matching requirement the detail lists, as a JSON array of numbers.",
        "rin": "The Regulation Identifier Number read from report_nature, where the rule found one.",
        "rin_rule": "Which RIN rule fired (`report_nature_rin_label`), or `unmatched`; NULL where the rule was not run.",
        "rin_matched_text": "The exact text the RIN rule matched, so a false positive is readable from the row.",
        "update_date": "The publisher's updateDate; the merge prefers the larger value.",
        "url": "The publisher's own URL for this communication, which only the list row states.",
    },
)

COMMITTEE_MEETINGS = table_contract(
    "committee_meetings",
    grain="One row per scheduled committee meeting, as the Congress.gov committee-meeting routes state it.",
    identity=("congress", "chamber", "event_id"),
    version_column="update_date",
    columns={
        "congress": "The numbered Congress the meeting belongs to.",
        "chamber": "The chamber, lowercased the way the publisher's own address spells it (house, senate, joint).",
        "event_id": "The publisher's event id, the key hearing_transcripts.event_id joins on.",
        "title": "The meeting title as the detail states it.",
        "meeting_type": "The publisher's meeting type (Hearing, Markup, ...).",
        "meeting_status": "The publisher's meeting status (Scheduled, Rescheduled, ...).",
        "meeting_date": "The meeting's date-time instant as the detail states it.",
        "location_building": "The building the detail names.",
        "location_room": "The room the detail names.",
        "committee_system_code": "System code of the first committee the detail lists.",
        "committee_count": "How many committees the detail lists; every one is in committees_json.",
        "committees_json": "Every committee the detail lists, as a JSON array of the publisher's objects.",
        "hearing_jacket": "The first hearing transcript jacket number the detail lists, where it lists any.",
        "hearing_jacket_count": "How many transcript jackets the detail lists; every one is in hearing_jackets_json.",
        "hearing_jackets_json": "Every transcript jacket number the detail lists, as a JSON array of strings.",
        "bill_count": "How many bills the detail relates to the meeting; every one is in bill_ids_json.",
        "bill_ids_json": "Natural keys of every bill in relatedItems.bills, as a JSON array, in publisher order.",
        "witness_count": "How many witnesses the detail lists.",
        "witnesses_json": "Every witness the detail lists, as a JSON array of the publisher's objects.",
        "witness_document_count": "How many witness documents the detail lists.",
        "witness_documents_json": "Every witness document the detail lists, as a JSON array of the publisher's objects.",
        "meeting_document_count": "How many meeting documents the detail lists.",
        "meeting_documents_json": "Every meeting document the detail lists, as a JSON array of the publisher's objects.",
        "document_urls_json": (
            "The URL of every document the meeting lists, witness documents first then meeting documents, "
            "in publisher order: what the map's meeting-to-documents edge resolves."
        ),
        "videos_json": "Every video link the detail lists, as a JSON array of the publisher's objects.",
        "update_date": "The publisher's updateDate; the merge prefers the larger value.",
        "url": "The publisher's own URL for this meeting, which only the list row states.",
    },
)

#: The rule the map's ``record→legislative-day`` edge measured: an issue's
#: ``fullIssue.sections[].name`` says which chamber met.  The Daily Digest
#: and Extensions of Remarks are sections too, and name no chamber sitting.
SECTION_CHAMBERS: Mapping[str, str] = MappingProxyType({"House Section": "house", "Senate Section": "senate"})
CHAMBERS_RULE = "section_name"
#: The map's ``record→package`` rule: the issue's own link names the GovInfo
#: package by its file stem (``CREC-2026-09-18.pdf`` is ``CREC-2026-09-18``).
PACKAGE_ID_RULE_RECORD = "entire_issue_url_stem"
#: The map's ``treaty→cdoc`` rule, resolved 2 of 2 on the 119th's treaties.
PACKAGE_ID_RULE_TREATY = "cdoc_tdoc_number"

RECORD_ISSUES = table_contract(
    "record_issues",
    grain="One row per daily Congressional Record issue, which is also one legislative day per chamber named.",
    identity=("volume", "issue"),
    version_column="update_date",
    columns={
        "volume": "The Record volume number.",
        "issue": "The issue number within that volume, as the publisher spells it.",
        "congress": "The numbered Congress the issue belongs to.",
        "session": "The session of Congress the issue belongs to.",
        "issue_date": "The issue date instant as the publisher states it.",
        "chambers": (
            "Which chambers this issue records a sitting of, unit-separator joined and sorted (`house`, `senate`); "
            "NULL where no detail was read, empty where the detail names no chamber section."
        ),
        "chambers_rule": "How chambers was derived: `section_name`, from the detail's section names.",
        "section_count": "How many sections the detail lists.",
        "section_names": "Every section name the detail lists, unit-separator joined, in publisher order.",
        "sections_json": "Every section the detail lists, as a JSON array of the publisher's objects.",
        "entire_issue_json": "Every whole-issue rendition the detail lists, as a JSON array of the publisher's objects.",
        "package_id": "The GovInfo CREC package id read from the first whole-issue link's file stem.",
        "package_id_rule": "How package_id was derived: `entire_issue_url_stem`.",
        "article_count": "How many articles the detail says the issue has.",
        "articles_url": "The publisher's URL for the issue's article list.",
        "update_date": "The publisher's updateDate; the merge prefers the larger value.",
        "url": "The publisher's own URL for this issue.",
    },
)

TREATIES = table_contract(
    "treaties",
    grain="One row per treaty document, as the Congress.gov treaty routes state it.",
    identity=("congress_received", "number", "suffix"),
    version_column="update_date",
    columns={
        "treaty_id": "Natural key: the Congress received, the number and, where one exists, the suffix, hyphen-joined.",
        "congress_received": "The Congress the treaty was received in.",
        "congress_considered": "The Congress the treaty was considered in, where the publisher states one.",
        "number": "The treaty document number.",
        "suffix": "The part suffix, as the publisher spells it (empty on an unpartitioned treaty).",
        "old_number": "The publisher's old number, where one exists.",
        "old_number_display_name": "The publisher's display name for that old number, where one exists.",
        "topic": "The publisher's topic.",
        "transmitted_date": "The instant the treaty was transmitted to the Senate.",
        "in_force_date": "The instant the treaty entered into force, where the publisher states one.",
        "resolution_text": "The resolution of ratification text, where the detail states one.",
        "formal_title": "The detail's `Treaty - Formal Title` entry.",
        "short_title": "The detail's `Treaty - Short Title` entry.",
        "titles_json": "Every title the detail lists, as a JSON array of the publisher's objects.",
        "countries_json": "Every country party the detail names, as a JSON array of names.",
        "index_terms_json": "Every index term the detail names, as a JSON array of names.",
        "related_docs_json": "Every related document the detail lists, as a JSON array of the publisher's objects.",
        "parts_json": "The publisher's parts object, as JSON.",
        "action_count": "How many actions the detail says the treaty has.",
        "actions_url": "The publisher's URL for the treaty's action list.",
        "package_id": "The GovInfo CDOC package id derived from the treaty number, on a treaty with no suffix.",
        "package_id_rule": "How package_id was derived: `cdoc_tdoc_number`.",
        "update_date": "The publisher's updateDate; the merge prefers the larger value.",
        "url": "The publisher's own URL for this treaty, which only the list row states.",
    },
)

NOMINATIONS = table_contract(
    "nominations",
    grain="One row per nomination or part, as the Congress.gov nomination list route states it.",
    identity=("congress", "citation"),
    version_column="update_date",
    columns={
        "citation": "The publisher's citation, its own display key, with the part where one exists (PN730-20).",
        "congress": "The numbered Congress the nomination was received in.",
        "number": "The PN number.",
        "part_number": "The part number, as the publisher spells it.",
        "description": "The publisher's description of the nomination.",
        "organization": "The organization the nominee would serve in.",
        "received_date": "The date the Senate received the nomination.",
        "is_civilian": "Whether the publisher's nominationType says the nomination is civilian.",
        "nomination_type_json": "The publisher's nominationType object, as JSON.",
        "latest_action_date": "Date of the publisher's latestAction entry.",
        "latest_action_text": "Text of the publisher's latestAction entry.",
        "update_date": "The publisher's updateDate; the merge prefers the larger value.",
        "url": "The publisher's own URL for this nomination.",
    },
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else ()


def _listed(detail: Mapping[str, Any] | None, key: str) -> tuple[Any, ...] | None:
    """A detail's list: NULL when no detail was read, empty when the detail states none."""
    if detail is None:
        return None
    return tuple(_sequence(detail.get(key)))


def _json_or_null(value: object) -> str | None:
    return None if value is None else json_column(value)


def _count(value: Sequence[Any] | None) -> str | None:
    return None if value is None else str(len(value))


def _first(value: Sequence[Any] | None) -> Mapping[str, Any]:
    return _mapping(value[0]) if value else {}


_RULEMAKING: Mapping[str, bool] = MappingProxyType({"True": True, "False": False})


def _rulemaking(value: object) -> str | None:
    """Fold the publisher's ``"True"``/``"False"`` strings; refuse any other spelling."""
    if value is None:
        return None
    if isinstance(value, bool):
        return flag(value)
    if isinstance(value, str) and value in _RULEMAKING:
        return flag(_RULEMAKING[value])
    raise TableContractError(f"house_communications: isRulemaking is spelled {value!r}, which no rule folds")


def shape_house_communication(
    listed: Mapping[str, Any],
    detail: Mapping[str, Any] | None,
    *,
    rin: object | None = None,
) -> Row:
    """One ``house_communications`` row from a list row and its detail record.

    ``listed`` is the list route's row for this communication, or the detail
    record itself when no list row was retained.  ``rin`` is a
    ``RinFinding`` from ``rin_from_report_nature`` over the detail's
    ``reportNature``, or ``None`` when that rule was not run.
    """
    read = _chain(listed, detail)
    kind = _mapping(read.get("communicationType"))
    code = kind.get("code")
    committees = _listed(detail, "committees")
    requirements = _listed(detail, "matchingRequirements")
    referral = _first(committees)
    requirement = _first(requirements)
    return {
        "communication_id": natural_key(read.get("congress"), code, read.get("number")),
        "congress": text(read.get("congress")),
        "communication_type": None if code is None else str(code).lower(),
        "communication_type_name": text(kind.get("name")),
        "number": text(read.get("number")),
        "chamber": text(read.get("chamber")),
        "session": text(read.get("sessionNumber")),
        "abstract": text(read.get("abstract")),
        "report_nature": text(read.get("reportNature")),
        "legal_authority": text(read.get("legalAuthority")),
        "submitting_agency": text(read.get("submittingAgency")),
        "submitting_official": text(read.get("submittingOfficial")),
        "congressional_record_date": text(read.get("congressionalRecordDate")),
        "is_rulemaking": _rulemaking(read.get("isRulemaking")),
        "referral_system_code": text(referral.get("systemCode")),
        "referral_committee_name": text(referral.get("name")),
        "referral_date": text(referral.get("referralDate")),
        "referral_count": _count(committees),
        "committees_json": _json_or_null(committees),
        "matching_requirement_number": text(requirement.get("number")),
        "matching_requirement_count": _count(requirements),
        "matching_requirements_json": (
            None if requirements is None else json_column([_mapping(entry).get("number") for entry in requirements])
        ),
        "rin": None if rin is None else text(rin.rin),
        "rin_rule": None if rin is None else text(rin.rule),
        "rin_matched_text": None if rin is None else text(rin.matched_text),
        "update_date": text(read.get("updateDate")),
        "url": text(listed.get("url")),
    }


def _chain(listed: Mapping[str, Any], detail: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """The detail's fields over the list row's, the detail winning where both state one."""
    if not isinstance(listed, Mapping):
        raise TableContractError("a list row must be a mapping")
    if detail is None:
        return listed
    if not isinstance(detail, Mapping):
        raise TableContractError("a detail record must be a mapping or None")
    return {**listed, **detail}


def _urls(entries: Sequence[Any]) -> list[str]:
    return [str(url) for entry in entries if (url := _mapping(entry).get("url"))]


def shape_committee_meeting(listed: Mapping[str, Any], detail: Mapping[str, Any] | None) -> Row:
    """One ``committee_meetings`` row from a list row and its detail record.

    ``listed`` is the list route's row for this meeting, or the detail record
    itself when no list row was retained.
    """
    read = _chain(listed, detail)
    location = _mapping(read.get("location"))
    committees = _listed(detail, "committees")
    jackets = _listed(detail, "hearingTranscript")
    bills = None if detail is None else tuple(_sequence(_mapping(detail.get("relatedItems")).get("bills")))
    witnesses = _listed(detail, "witnesses")
    witness_documents = _listed(detail, "witnessDocuments")
    meeting_documents = _listed(detail, "meetingDocuments")
    videos = _listed(detail, "videos")
    chamber = read.get("chamber")
    jacket_numbers = None if jackets is None else [str(_mapping(entry).get("jacketNumber")) for entry in jackets]
    return {
        "congress": text(read.get("congress")),
        "chamber": None if chamber is None else str(chamber).lower(),
        "event_id": text(read.get("eventId")),
        "title": text(read.get("title")),
        "meeting_type": text(read.get("type")),
        "meeting_status": text(read.get("meetingStatus")),
        "meeting_date": text(read.get("date")),
        "location_building": text(location.get("building")),
        "location_room": text(location.get("room")),
        "committee_system_code": text(_first(committees).get("systemCode")),
        "committee_count": _count(committees),
        "committees_json": _json_or_null(committees),
        "hearing_jacket": None if not jacket_numbers else jacket_numbers[0],
        "hearing_jacket_count": _count(jackets),
        "hearing_jackets_json": _json_or_null(jacket_numbers),
        "bill_count": _count(bills),
        "bill_ids_json": (
            None
            if bills is None
            else json_column(
                [
                    natural_key(entry.get("congress"), entry.get("type"), entry.get("number"))
                    for entry in map(_mapping, bills)
                ]
            )
        ),
        "witness_count": _count(witnesses),
        "witnesses_json": _json_or_null(witnesses),
        "witness_document_count": _count(witness_documents),
        "witness_documents_json": _json_or_null(witness_documents),
        "meeting_document_count": _count(meeting_documents),
        "meeting_documents_json": _json_or_null(meeting_documents),
        "document_urls_json": (
            None if detail is None else json_column(_urls(witness_documents or ()) + _urls(meeting_documents or ()))
        ),
        "videos_json": _json_or_null(videos),
        "update_date": text(read.get("updateDate")),
        "url": text(listed.get("url")),
    }


def _package_stem(url: object) -> str | None:
    """``.../CREC-2026-09-18.pdf`` names package ``CREC-2026-09-18``; anything else is NULL."""
    if not isinstance(url, str) or not url:
        return None
    stem = url.rsplit("/", 1)[-1]
    stem = stem.split(".", 1)[0]
    return stem or None


def shape_record_issue(listed: Mapping[str, Any], detail: Mapping[str, Any] | None) -> Row:
    """One ``record_issues`` row from a list row and its detail record (the ``issue`` object)."""
    read = _chain(listed, detail)
    full = None if detail is None else _mapping(detail.get("fullIssue"))
    sections = None if full is None else tuple(_sequence(full.get("sections")))
    entire = None if full is None else tuple(_sequence(full.get("entireIssue")))
    articles = {} if full is None else _mapping(full.get("articles"))
    names = None if sections is None else [str(_mapping(section).get("name")) for section in sections]
    chambers = None if names is None else sorted({SECTION_CHAMBERS[name] for name in names if name in SECTION_CHAMBERS})
    package_id = None if not entire else _package_stem(_first(entire).get("url"))
    return {
        "volume": text(read.get("volumeNumber")),
        "issue": text(read.get("issueNumber")),
        "congress": text(read.get("congress")),
        "session": text(read.get("sessionNumber")),
        "issue_date": text(read.get("issueDate")),
        "chambers": None if chambers is None else joined(chambers),
        "chambers_rule": None if chambers is None else CHAMBERS_RULE,
        "section_count": _count(sections),
        "section_names": None if names is None else joined(names),
        "sections_json": _json_or_null(sections),
        "entire_issue_json": _json_or_null(entire),
        "package_id": package_id,
        "package_id_rule": None if package_id is None else PACKAGE_ID_RULE_RECORD,
        "article_count": text(articles.get("count")),
        "articles_url": text(articles.get("url")),
        "update_date": text(read.get("updateDate")),
        "url": text(read.get("url")),
    }


def treaty_id(congress: object, number: object, suffix: object) -> str:
    """``{congress}-{number}``, plus ``-{suffix}`` on a partitioned treaty."""
    return f"{congress}-{number}" + (f"-{suffix}" if suffix else "")


def treaty_package_id(congress: object, number: object, suffix: object) -> str | None:
    """The map's ``treaty→cdoc`` rule, on an unpartitioned treaty only."""
    if congress is None or number is None or suffix:
        return None
    return f"CDOC-{congress}tdoc{number}"


def shape_treaty(listed: Mapping[str, Any], detail: Mapping[str, Any] | None) -> Row:
    """One ``treaties`` row from a list row and its detail record."""
    read = _chain(listed, detail)
    congress, number, suffix = read.get("congressReceived"), read.get("number"), read.get("suffix")
    titles = _listed(detail, "titles")
    by_type = (
        {} if titles is None else {_mapping(entry).get("titleType"): _mapping(entry).get("title") for entry in titles}
    )
    countries = _listed(detail, "countriesParties")
    terms = _listed(detail, "indexTerms")
    related = _listed(detail, "relatedDocs")
    actions = {} if detail is None else _mapping(detail.get("actions"))
    parts = read.get("parts")
    package_id = treaty_package_id(congress, number, suffix)
    return {
        "treaty_id": treaty_id(congress, number, suffix),
        "congress_received": text(congress),
        "congress_considered": text(read.get("congressConsidered")),
        "number": text(number),
        "suffix": text(suffix),
        "old_number": text(read.get("oldNumber")),
        "old_number_display_name": text(read.get("oldNumberDisplayName")),
        "topic": text(read.get("topic")),
        "transmitted_date": text(read.get("transmittedDate")),
        "in_force_date": text(read.get("inForceDate")),
        "resolution_text": text(read.get("resolutionText")),
        "formal_title": text(by_type.get("Treaty - Formal Title")),
        "short_title": text(by_type.get("Treaty - Short Title")),
        "titles_json": _json_or_null(titles),
        "countries_json": None
        if countries is None
        else json_column([_mapping(entry).get("name") for entry in countries]),
        "index_terms_json": None if terms is None else json_column([_mapping(entry).get("name") for entry in terms]),
        "related_docs_json": _json_or_null(related),
        "parts_json": None if not isinstance(parts, Mapping) else json_column(dict(parts)),
        "action_count": text(actions.get("count")),
        "actions_url": text(actions.get("url")),
        "package_id": package_id,
        "package_id_rule": None if package_id is None else PACKAGE_ID_RULE_TREATY,
        "update_date": text(read.get("updateDate")),
        "url": text(listed.get("url")),
    }


def shape_nomination(record: Mapping[str, Any]) -> Row:
    """One ``nominations`` row from the nomination list route's exact publisher dict."""
    if not isinstance(record, Mapping):
        raise TableContractError("a nomination record must be a mapping")
    latest = _mapping(record.get("latestAction"))
    kind = record.get("nominationType")
    civilian = _mapping(kind).get("isCivilian")
    return {
        "citation": text(record.get("citation")),
        "congress": text(record.get("congress")),
        "number": text(record.get("number")),
        "part_number": text(record.get("partNumber")),
        "description": text(record.get("description")),
        "organization": text(record.get("organization")),
        "received_date": text(record.get("receivedDate")),
        "is_civilian": flag(civilian) if isinstance(civilian, bool) or civilian is None else text(civilian),
        "nomination_type_json": None if not isinstance(kind, Mapping) else json_column(dict(kind)),
        "latest_action_date": text(latest.get("actionDate")),
        "latest_action_text": text(latest.get("text")),
        "update_date": text(record.get("updateDate")),
        "url": text(record.get("url")),
    }


__all__ = [
    "CHAMBERS_RULE",
    "COMMITTEE_MEETINGS",
    "HOUSE_COMMUNICATIONS",
    "NOMINATIONS",
    "PACKAGE_ID_RULE_RECORD",
    "PACKAGE_ID_RULE_TREATY",
    "RECORD_ISSUES",
    "SECTION_CHAMBERS",
    "TREATIES",
    "shape_committee_meeting",
    "shape_house_communication",
    "shape_nomination",
    "shape_record_issue",
    "shape_treaty",
    "treaty_id",
    "treaty_package_id",
]
