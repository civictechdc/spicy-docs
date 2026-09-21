"""Data flow: which identifier references which source, probed on one real item per edge."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from spicy_docs.reading.paged_json import PagedJsonReader, PagedJsonSourceError
from spicy_docs.reading.xml import parse_xml
from spicy_docs.transport.credentials import CredentialRefusedError, scrub_credential
from tools.analysis.legislative_data_map._render import _cell, _ordinal
from tools.analysis.legislative_data_map.capture import (
    COMPARE_VOLUME,
    GOVINFO_API,
    SAMPLE_MAX_BYTES,
    _bioguides,
    _bulk_listing,
    _keyed_json,
    _texts,
    _xml,
)
from tools.analysis.legislative_data_map.rows import CURRENT_CONGRESS, SAMPLES, XML_TYPES
from tools.analysis.shared import (
    CONGRESS_API,
    JSON_TYPES,
    KeylessProbe,
    ProbeError,
    ProbeUnavailableError,
    local_name,
)

# --- data flow: which identifiers reference which sources, one real item per edge --------------


@dataclass(frozen=True)
class Edge:
    """One reference from a source to a target: the field that carries it and how it is followed."""

    key: str
    source: str
    target: str
    via: str
    kind: str  # id: an identifier the target keys on; url: a stated URL; derived: an id built by a rule; text: free text only


FLOW_BILL = (CURRENT_CONGRESS, "hr", "1")
FLOW_LAW = (CURRENT_CONGRESS, 1)
FLOW_OLD_LAW = "117-58"
FLOW_SENATE_VOTE = f"https://www.senate.gov/legislative/LIS/roll_call_votes/vote{CURRENT_CONGRESS}1/vote_{CURRENT_CONGRESS}_1_00001.xml"
CBO_FEED = f"https://www.cbo.gov/rss/{CURRENT_CONGRESS}congress-cost-estimates.xml"
OLRC_TABLES = "https://uscode.house.gov/classification/tables.shtml"
HTML_TYPES = ("text/html", "application/xhtml+xml")
COMMITTEE_CHAMBER = {"House": "house", "Senate": "senate", "Joint": "joint"}


def _stated_congress_path(url: object) -> str | None:
    """A list row's own ``url`` as a path under ``CONGRESS_API``, or None when the row states none.

    A probe built from a path this tool spells can only test its own spelling: the requirement
    probe once asked ``house-communication/112/ec/2`` while the publisher's list row states
    ``.../112/EC/2``, so a route answering only the upper-case form would have read as a missing
    detail record. The 2026-09-20 executive-communications re-derivation asked the stated locator
    and the floor held, but the construction is kept only as the fallback for a row stating none.
    """
    if not isinstance(url, str) or not url.startswith(f"{CONGRESS_API}/"):
        return None
    return url[len(CONGRESS_API) + 1 :].split("?", 1)[0]


def _cg(reader: PagedJsonReader, path: str) -> Mapping[str, Any]:
    return _keyed_json(reader, f"{CONGRESS_API}/{path}{'&' if '?' in path else '?'}format=json")


def _gi(reader: PagedJsonReader, path: str) -> Mapping[str, Any]:
    return _keyed_json(reader, f"{GOVINFO_API}/{path}")


def _package_id(url: str) -> str | None:
    match = re.search(r"/(?:pkg/)?([A-Z]{3,6}-[0-9A-Za-z._-]+?)(?:/|\.xml|\.htm|\.pdf|\.txt)", url)
    return match[1] if match else None


def _system_code(chamber: str, code: str) -> str:
    """Clerk and Senate committee codes to Congress.gov systemCodes: `JU00` → `hsju00`, `SSAS` → `ssas00`."""
    code = code.strip().lower()
    if chamber == "house":
        return code if code.startswith("hs") else f"hs{code}"
    return code if code.endswith("00") else f"{code}00"


def _committee_name(committee: Mapping[str, Any]) -> str:
    history = committee.get("history") or [{}]
    return str(history[0].get("officialName") or committee.get("name") or committee.get("systemCode"))


def _bill_ref(item: Mapping[str, Any]) -> str:
    return f"bill/{item.get('congress')}/{str(item.get('type', '')).lower()}/{item.get('number')}"


def measure_flow(
    congress: PagedJsonReader, govinfo: PagedJsonReader, probe: KeylessProbe, api_key: str
) -> dict[str, Any]:
    c, t, n = FLOW_BILL
    bill_path = f"bill/{c}/{t}/{n}"
    results: dict[str, Any] = {}
    cache: dict[str, Any] = {}

    def bill_detail() -> Mapping[str, Any]:
        if "bill" not in cache:
            cache["bill"] = _cg(congress, bill_path).get("bill", {})
        return cache["bill"]

    def keyless_exists(url: str, media_types: tuple[str, ...]) -> tuple[bool, str]:
        try:
            capture = probe.get(url, media_types=media_types, max_bytes=4 * 1024 * 1024)
            return True, f"{capture.status_code} {capture.content_type} {capture.byte_size:,} B"
        except CredentialRefusedError as error:
            return False, f"refused keyless: {str(error)[:60]} (bot wall)"
        except ProbeError as error:
            message = str(error)
            if "exceeds" in message:
                return True, "exists, larger than 4 MiB"
            status = getattr(getattr(error, "capture", None), "status_code", None)
            return False, f"HTTP {status}" if status else message[:80]

    def run(edge: Edge, fn: Callable[[], tuple[bool, str]]) -> None:
        try:
            ok, evidence = fn()
        except (
            PagedJsonSourceError,
            ProbeError,
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as error:
            ok, evidence = False, f"{type(error).__name__}: {scrub_credential(str(error), api_key)[:120]}"
        results[edge.key] = {**asdict(edge), "ok": ok, "evidence": evidence}
        print(f"flow {edge.key}: {'ok' if ok else 'NO'} {evidence[:110]}", file=sys.stderr)

    # Congress.gov bill outward
    def bill_member() -> tuple[bool, str]:
        bid = bill_detail().get("sponsors", [{}])[0].get("bioguideId")
        member = _cg(congress, f"member/{bid}").get("member", {})
        return member.get("bioguideId") == bid, f"sponsor {bid} → {member.get('directOrderName') or member.get('name')}"

    def bill_committee() -> tuple[bool, str]:
        row = _cg(congress, f"{bill_path}/committees").get("committees", [{}])[0]
        code, chamber = row.get("systemCode"), COMMITTEE_CHAMBER.get(row.get("chamber", ""), "house")
        committee = _cg(congress, f"committee/{chamber}/{code}").get("committee", {})
        return committee.get("systemCode") == code, f"{code} → {_committee_name(committee)}"

    def report_rows() -> Mapping[str, Any]:
        """The first listed report of the Congress; H.R. 1 itself carried none (reconciliation)."""
        if "report" not in cache:
            row = _cg(congress, f"committee-report/{CURRENT_CONGRESS}?limit=1").get("reports", [{}])[0]
            cache["report_path"] = (
                f"committee-report/{row.get('congress')}/{str(row.get('type', '')).lower()}/{row.get('number')}"
            )
            cache["report"] = _cg(congress, cache["report_path"]).get("committeeReports", [{}])[0]
        return cache["report"]

    def bill_report() -> tuple[bool, str]:
        assoc = report_rows().get("associatedBill", [{}])[0]
        if not assoc:
            return False, f"{cache['report_path']} names no associated bill"
        detail = _cg(congress, _bill_ref(assoc)).get("bill", {})
        citations = [r.get("citation") for r in detail.get("committeeReports", [])]
        return report_rows().get(
            "citation"
        ) in citations, f"{_bill_ref(assoc)} committeeReports {citations} ↔ {report_rows().get('citation')}"

    def bill_law() -> tuple[bool, str]:
        law = bill_detail().get("laws", [{}])[0]
        number = str(law.get("number", ""))
        cong, num = number.split("-")
        bill = _cg(congress, f"law/{cong}/pub/{num}").get("bill", {})
        return str(
            bill.get("number")
        ) == n, f"{law.get('type')} {number} → law/{cong}/pub/{num} → {bill.get('type')} {bill.get('number')}"

    def recorded_votes() -> list[Mapping[str, Any]]:
        if "votes" not in cache:
            actions = _cg(congress, f"{bill_path}/actions?limit=250").get("actions", [])
            cache["votes"] = [v for a in actions for v in a.get("recordedVotes", [])]
        return cache["votes"]

    def bill_house_vote() -> tuple[bool, str]:
        vote = next((v for v in recorded_votes() if v.get("chamber") == "House"), None)
        if not vote:
            return False, "no House recorded vote on the sample"
        detail = _cg(congress, f"house-vote/{vote['congress']}/{vote['sessionNumber']}/{vote['rollNumber']}").get(
            "houseRollCallVote", {}
        )
        return (
            str(detail.get("legislationNumber")) == n,
            f"roll {vote['rollNumber']} → house-vote → {detail.get('legislationType')} {detail.get('legislationNumber')}",
        )

    def bill_clerk_xml() -> tuple[bool, str]:
        vote = next((v for v in recorded_votes() if v.get("chamber") == "House"), None)
        if not vote:
            return False, "no House recorded vote on the sample"
        root = _xml(probe, vote["url"], "clerk")
        legis = (_texts(root, {"legis-num"}) or [""])[0]
        return legis.replace(" ", "").lower() == f"{t}{n}", f"{vote['url']} legis-num {legis!r}"

    def bill_senate_xml() -> tuple[bool, str]:
        vote = next((v for v in recorded_votes() if v.get("chamber") == "Senate"), None)
        if not vote:
            return False, "no Senate recorded vote on the sample"
        root = _xml(probe, vote["url"], "senate")
        number = (_texts(root, {"document_number"}) or [""])[0]
        return number == n, f"{vote['url']} document_number {number!r}"

    def bill_amendment() -> tuple[bool, str]:
        row = _cg(congress, f"{bill_path}/amendments").get("amendments", [{}])[0]
        path = f"amendment/{row.get('congress')}/{str(row.get('type', '')).lower()}/{row.get('number')}"
        amended = _cg(congress, path).get("amendment", {}).get("amendedBill", {})
        return str(
            amended.get("number")
        ) == n, f"{row.get('type')} {row.get('number')} → amendedBill {amended.get('type')} {amended.get('number')}"

    def bill_related() -> tuple[bool, str]:
        row = _cg(congress, f"{bill_path}/relatedbills").get("relatedBills", [{}])[0]
        bill = _cg(congress, _bill_ref(row)).get("bill", {})
        return str(bill.get("number")) == str(row.get("number")), f"{_bill_ref(row)} → {bill.get('title', '')[:40]!r}"

    def bill_text_package() -> tuple[bool, str]:
        version = _cg(congress, f"{bill_path}/text").get("textVersions", [{}])[0]
        url = version.get("formats", [{}])[0].get("url", "")
        package = _package_id(url)
        summary = _gi(govinfo, f"packages/{package}/summary") if package else {}
        return bool(package) and summary.get(
            "packageId"
        ) == package, f"{urlsplit(url).netloc}{urlsplit(url).path} → GovInfo {package}"

    def bill_cbo() -> tuple[bool, str]:
        url = bill_detail().get("cboCostEstimates", [{}])[0].get("url", "")
        if not url:
            return False, "no CBO estimate on the sample"
        ok, evidence = keyless_exists(url, HTML_TYPES)
        return ok, f"{url} → {evidence}"

    run(
        Edge("bill→member", "Congress.gov bill", "Congress.gov member", "sponsors[].bioguideId → member/{id}", "id"),
        bill_member,
    )
    run(
        Edge(
            "bill→committee",
            "Congress.gov bill",
            "Congress.gov committee",
            "committees[].systemCode → committee/{chamber}/{code}",
            "id",
        ),
        bill_committee,
    )
    run(
        Edge(
            "bill→report",
            "Congress.gov bill",
            "Congress.gov committee-report",
            "committeeReports[].citation → committee-report/{c}/{type}/{n}",
            "derived",
        ),
        bill_report,
    )
    run(Edge("bill→law", "Congress.gov bill", "Congress.gov law", "laws[].number → law/{c}/pub/{n}", "id"), bill_law)
    run(
        Edge(
            "bill→house-vote",
            "Congress.gov bill",
            "Congress.gov house-vote",
            "actions[].recordedVotes → house-vote/{c}/{session}/{roll}",
            "id",
        ),
        bill_house_vote,
    )
    run(
        Edge(
            "bill→clerk-xml", "Congress.gov bill", "Clerk vote XML", "recordedVotes[].url (clerk.house.gov/evs)", "url"
        ),
        bill_clerk_xml,
    )
    run(
        Edge(
            "bill→senate-xml",
            "Congress.gov bill",
            "Senate vote XML",
            "recordedVotes[].url (senate.gov roll_call_votes)",
            "url",
        ),
        bill_senate_xml,
    )
    run(
        Edge(
            "bill→amendment",
            "Congress.gov bill",
            "Congress.gov amendment",
            "amendments[] → amendment/{c}/{type}/{n}; amendedBill back",
            "id",
        ),
        bill_amendment,
    )
    run(
        Edge(
            "bill→related-bill", "Congress.gov bill", "Congress.gov bill", "relatedBills[] → bill/{c}/{type}/{n}", "id"
        ),
        bill_related,
    )
    run(
        Edge(
            "bill→text-package",
            "Congress.gov bill",
            "GovInfo BILLS package",
            "textVersions[].formats[].url → package id BILLS-{c}{type}{n}{version}",
            "derived",
        ),
        bill_text_package,
    )
    run(Edge("bill→cbo", "Congress.gov bill", "CBO estimate page", "cboCostEstimates[].url", "url"), bill_cbo)

    # Congress.gov reports, hearings, meetings
    def report_bill() -> tuple[bool, str]:
        assoc = report_rows().get("associatedBill", [{}])[0]
        bill = _cg(congress, _bill_ref(assoc)).get("bill", {})
        return str(bill.get("number")) == str(assoc.get("number")), f"associatedBill → {_bill_ref(assoc)}"

    def report_package() -> tuple[bool, str]:
        text = _cg(congress, f"{cache['report_path']}/text").get("text", [{}])[0]
        url = text.get("formats", [{}])[0].get("url", "")
        package = _package_id(url)
        summary = _gi(govinfo, f"packages/{package}/summary") if package else {}
        return bool(package) and summary.get("packageId") == package, f"{urlsplit(url).path} → GovInfo {package}"

    def hearing_detail() -> Mapping[str, Any]:
        """The first of the eight newest hearings that names a meeting, else the first."""
        if "hearing" not in cache:
            rows = _cg(congress, f"hearing/{CURRENT_CONGRESS}?limit=8").get("hearings", [{}])
            first: Mapping[str, Any] = {}
            for row in rows:
                path = f"hearing/{row.get('congress')}/{str(row.get('chamber', '')).lower()}/{row.get('jacketNumber')}"
                detail = _cg(congress, path).get("hearing", {})
                first = first or detail
                if (detail.get("associatedMeeting") or {}).get("eventId"):
                    cache["hearing"] = detail
                    break
            cache.setdefault("hearing", first)
        return cache["hearing"]

    def hearing_package() -> tuple[bool, str]:
        url = hearing_detail().get("formats", [{}])[0].get("url", "")
        package = _package_id(url)
        summary = _gi(govinfo, f"packages/{package}/summary") if package else {}
        return bool(package) and summary.get(
            "packageId"
        ) == package, f"jacket {hearing_detail().get('jacketNumber')} → {package}"

    def hearing_meeting() -> tuple[bool, str]:
        meeting = hearing_detail().get("associatedMeeting", {})
        event = meeting.get("eventId")
        if not event:
            return False, f"no associatedMeeting on jacket {hearing_detail().get('jacketNumber')}"
        chamber = str(hearing_detail().get("chamber", "house")).lower()
        detail = _cg(congress, f"committee-meeting/{CURRENT_CONGRESS}/{chamber}/{event}").get("committeeMeeting", {})
        return str(detail.get("eventId")) == str(event), f"eventId {event} → committee-meeting ({detail.get('type')})"

    def meeting_with(field: str) -> Mapping[str, Any]:
        if "meetings" not in cache:
            rows = _cg(congress, f"committee-meeting/{CURRENT_CONGRESS}?limit=8").get("committeeMeetings", [])
            cache["meetings"] = [
                _cg(congress, f"committee-meeting/{r['congress']}/{str(r['chamber']).lower()}/{r['eventId']}").get(
                    "committeeMeeting", {}
                )
                for r in rows
            ]
        for detail in cache["meetings"]:
            value = detail.get(field) or (detail.get("relatedItems", {}) or {}).get(field)
            if value:
                return detail
        return {}

    def meeting_bill() -> tuple[bool, str]:
        detail = meeting_with("bills")
        item = (detail.get("relatedItems", {}) or {}).get("bills", [{}])[0]
        if not item:
            return False, "no meeting among the first 8 lists a bill"
        bill = _cg(congress, _bill_ref(item)).get("bill", {})
        return str(bill.get("number")) == str(
            item.get("number")
        ), f"eventId {detail.get('eventId')} relatedItems.bills → {_bill_ref(item)}"

    def meeting_documents() -> tuple[bool, str]:
        detail = meeting_with("witnessDocuments") or meeting_with("meetingDocuments")
        docs = detail.get("witnessDocuments") or detail.get("meetingDocuments") or [{}]
        url = docs[0].get("url", "")
        if not url:
            return False, "no meeting among the first 8 carries a document URL"
        ok, evidence = keyless_exists(url, ("application/pdf", *XML_TYPES, *HTML_TYPES))
        return ok, f"{urlsplit(url).netloc} → {evidence}"

    def meeting_hearing() -> tuple[bool, str]:
        """The reverse of hearing→meeting: the meeting a hearing names must name the hearing's jacket back."""
        event = (hearing_detail().get("associatedMeeting") or {}).get("eventId")
        if not event:
            return False, "no hearing among the eight newest names a meeting"
        chamber = str(hearing_detail().get("chamber", "house")).lower()
        detail = _cg(congress, f"committee-meeting/{CURRENT_CONGRESS}/{chamber}/{event}").get("committeeMeeting", {})
        jackets = [str(x.get("jacketNumber")) for x in detail.get("hearingTranscript") or []]
        mine = str(hearing_detail().get("jacketNumber"))
        return mine in jackets, f"eventId {event} hearingTranscript {jackets} ↔ jacket {mine}"

    run(
        Edge(
            "report→bill",
            "Congress.gov committee-report",
            "Congress.gov bill",
            "associatedBill[] → bill/{c}/{type}/{n}",
            "id",
        ),
        report_bill,
    )
    run(
        Edge(
            "report→package",
            "Congress.gov committee-report",
            "GovInfo CRPT package",
            "text[].formats[].url → package id CRPT-{c}{type}{n}",
            "derived",
        ),
        report_package,
    )
    run(
        Edge(
            "hearing→package",
            "Congress.gov hearing",
            "GovInfo CHRG package",
            "formats[].url → package id CHRG-{c}{chamber}hrg{jacket}",
            "derived",
        ),
        hearing_package,
    )
    run(
        Edge(
            "hearing→meeting",
            "Congress.gov hearing",
            "Congress.gov committee-meeting",
            "associatedMeeting.eventId → committee-meeting/{c}/{chamber}/{eventId}",
            "id",
        ),
        hearing_meeting,
    )
    run(
        Edge(
            "meeting→bill", "Congress.gov committee-meeting", "Congress.gov bill", "relatedItems.bills[] → bill", "id"
        ),
        meeting_bill,
    )
    run(
        Edge(
            "meeting→documents",
            "Congress.gov committee-meeting",
            "docs.house.gov / congress.gov documents",
            "witnessDocuments[].url, meetingDocuments[].url",
            "url",
        ),
        meeting_documents,
    )
    run(
        Edge(
            "meeting→hearing",
            "Congress.gov committee-meeting",
            "Congress.gov hearing",
            "hearingTranscript[].jacketNumber → hearing/{c}/{chamber}/{jacket}",
            "id",
        ),
        meeting_hearing,
    )

    # Nominations, votes, members
    def nomination_with(field: str) -> Mapping[str, Any]:
        """The first of the twelve newest nominations whose detail counts the named sub-resource."""
        if "nominations" not in cache:
            rows = _cg(congress, f"nomination/{CURRENT_CONGRESS}?limit=12").get("nominations", [])
            cache["nominations"] = [
                _cg(congress, f"nomination/{CURRENT_CONGRESS}/{r.get('number')}").get("nomination", {}) for r in rows
            ]
        found = next((d for d in cache["nominations"] if (d.get(field) or {}).get("count")), {})
        if found:
            return found
        # The newest nominations have not reached a hearing; confirmed ones have. Take five from that feed.
        if "confirmed" not in cache:
            root = _xml(
                probe, "https://www.senate.gov/legislative/LIS/nominations/NomCivilianConfirmed.xml", "confirmed"
            )
            numbers = [m for el in root.iter() if el.text for m in re.findall(r"PN(\d+)", el.text)][:5]
            cache["confirmed"] = [
                _cg(congress, f"nomination/{CURRENT_CONGRESS}/{n}").get("nomination", {})
                for n in dict.fromkeys(numbers)
            ]
        return next((d for d in cache["confirmed"] if (d.get(field) or {}).get("count")), {})

    def nomination_committee() -> tuple[bool, str]:
        detail = nomination_with("committees")
        number = detail.get("number")
        if number is None:
            return False, "none of the twelve newest nominations counts a committee"
        rows = _cg(congress, f"nomination/{CURRENT_CONGRESS}/{number}/committees").get("committees", [{}])
        code = rows[0].get("systemCode")
        committee = _cg(congress, f"committee/senate/{code}").get("committee", {})
        return committee.get("systemCode") == code, f"PN{number} → {code} → {_committee_name(committee)}"

    def nomination_hearing() -> tuple[bool, str]:
        detail = nomination_with("hearings")
        number = detail.get("number")
        if number is None:
            return False, "none of the twelve newest nor five confirmed nominations counts a hearing"
        rows = _cg(congress, f"nomination/{CURRENT_CONGRESS}/{number}/hearings").get("hearings", [{}])
        jacket = rows[0].get("jacketNumber")
        hearing = _cg(congress, f"hearing/{CURRENT_CONGRESS}/senate/{jacket}").get("hearing", {})
        return str(hearing.get("jacketNumber")) == str(jacket), f"PN{number} → hearing jacket {jacket}"

    def feed_nomination() -> tuple[bool, str]:
        root = _xml(probe, "https://www.senate.gov/legislative/LIS/nominations/NomWithdrawn.xml", "feed")
        pn = next((m for el in root.iter() if el.text for m in re.findall(r"PN(\d+)", el.text)), None)
        detail = _cg(congress, f"nomination/{CURRENT_CONGRESS}/{pn}").get("nomination", {})
        return str(detail.get("number")) == pn, f"feed PN{pn} → nomination/{CURRENT_CONGRESS}/{pn}"

    def feed_committee() -> tuple[bool, str]:
        root = _xml(probe, "https://www.senate.gov/legislative/LIS/nominations/NomCivilianPendingCommittee.xml", "feed")
        committee_el = next((el for el in root.iter() if local_name(el.tag) == "Committee"), None)
        if committee_el is None:
            return False, "no Committee element in the feed"
        fields = {local_name(ch.tag): (ch.text or "").strip() for ch in committee_el}
        code = next(
            (v for k, v in fields.items() if "code" in k.lower() and re.fullmatch(r"[A-Za-z]{4}(00)?", v)), None
        )
        if code:
            system = _system_code("senate", code[:4])
            committee = _cg(congress, f"committee/senate/{system}").get("committee", {})
            return committee.get("systemCode") == system, f"feed code {code} → {system} → {_committee_name(committee)}"
        name = next((v for k, v in fields.items() if "name" in k.lower() and v), "")
        rows = _cg(congress, "committee/senate?limit=250").get("committees", [])
        match = next((r for r in rows if name and name.lower() in str(r.get("name", "")).lower()), None)
        return (
            bool(match),
            f"feed names {name!r} (fields {sorted(fields)}) → systemCode {match.get('systemCode') if match else None} by name match",
        )

    def house_vote_bill() -> tuple[bool, str]:
        detail = _cg(congress, f"house-vote/{CURRENT_CONGRESS}/1/240").get("houseRollCallVote", {})
        ref = f"bill/{CURRENT_CONGRESS}/{str(detail.get('legislationType', '')).lower()}/{detail.get('legislationNumber')}"
        bill = _cg(congress, ref).get("bill", {})
        return str(bill.get("number")) == str(detail.get("legislationNumber")), f"roll 240 → {ref}"

    def house_vote_member() -> tuple[bool, str]:
        value = _cg(congress, f"house-vote/{CURRENT_CONGRESS}/1/240/members?limit=1")
        bid = value.get("houseRollCallVoteMemberVotes", {}).get("results", [{}])[0].get("bioguideID")
        member = _cg(congress, f"member/{bid}").get("member", {})
        return member.get("bioguideId") == bid, f"voter {bid} → member"

    def member_bill() -> tuple[bool, str]:
        bid = bill_detail().get("sponsors", [{}])[0].get("bioguideId")
        row = _cg(congress, f"member/{bid}/sponsored-legislation?limit=1").get("sponsoredLegislation", [{}])[0]
        bill = _cg(congress, _bill_ref(row)).get("bill", {})
        return str(bill.get("number")) == str(row.get("number")), f"{bid} sponsored → {_bill_ref(row)}"

    def member_house_file() -> tuple[bool, str]:
        bid = bill_detail().get("sponsors", [{}])[0].get("bioguideId")
        ids = _bioguides(_xml(probe, SAMPLES["house-members-xml"][0], "house"))
        return bid in ids, f"{bid} {'in' if bid in ids else 'not in'} members.xml ({len(ids)} ids)"

    def clerk_committee() -> tuple[bool, str]:
        root = _xml(probe, SAMPLES["house-memberdata"][0], "memberdata")
        code = next((v for el in root.iter() for k, v in el.attrib.items() if "comcode" in k.lower() and v), None)
        if not code:
            return False, "no comcode attribute in MemberData"
        system = _system_code("house", code)
        committee = _cg(congress, f"committee/house/{system}").get("committee", {})
        return committee.get("systemCode") == system, f"comcode {code} → {system} → {_committee_name(committee)}"

    def cvc_root() -> Any:
        if "cvc_root" not in cache:
            cache["cvc_root"] = _xml(probe, SAMPLES["senate-cvc"][0], "cvc")
        return cache["cvc_root"]

    def cvc_senators() -> list[dict[str, str]]:
        """Each senator's leaf children plus attributes; the LIS id is the `lis_member_id` attribute of <senator>."""
        return [
            {**{local_name(ch.tag): (ch.text or "").strip() for ch in el if len(ch) == 0}, **dict(el.attrib)}
            for el in cvc_root().iter()
            if local_name(el.tag) == "senator"
        ]

    def bioguide_of(fields: Mapping[str, str]) -> str:
        return fields.get("bioguideId") or fields.get("bioguide_id") or ""

    def cvc_member() -> tuple[bool, str]:
        first = (cvc_senators() or [{}])[0]
        bid, lis = bioguide_of(first), first.get("lis_member_id")
        member = _cg(congress, f"member/{bid}").get("member", {})
        return member.get("bioguideId") == bid, f"cvc bioguideId {bid} + @lis_member_id {lis} → member"

    def cvc_committee() -> tuple[bool, str]:
        root = cvc_root()
        code = next(
            (
                v
                for el in root.iter()
                if local_name(el.tag) == "committee"
                for k, v in el.attrib.items()
                if "code" in k.lower()
            ),
            None,
        )
        code = code or next(
            (
                el.text.strip()
                for el in root.iter()
                if "committee" in local_name(el.tag).lower() and el.text and re.fullmatch(r"[A-Z]{4}", el.text.strip())
            ),
            None,
        )
        if not code:
            return False, "no committee code in cvc"
        system = _system_code("senate", code)
        committee = _cg(congress, f"committee/senate/{system}").get("committee", {})
        return committee.get("systemCode") == system, f"cvc {code} → {system} → {_committee_name(committee)}"

    def senate_vote_root() -> Any:
        if "senate_vote_root" not in cache:
            cache["senate_vote_root"] = _xml(probe, FLOW_SENATE_VOTE, "senate-vote")
        return cache["senate_vote_root"]

    def senate_vote_member() -> tuple[bool, str]:
        """LIS ids on a vote resolve through today's crosswalk only for senators still serving; count the rest."""
        voters = _texts(senate_vote_root(), {"lis_member_id"})
        crosswalk = {f.get("lis_member_id"): bioguide_of(f) for f in cvc_senators()}
        absent = [lis for lis in voters if lis not in crosswalk]
        present = next((lis for lis in voters if lis in crosswalk), None)
        if present is None:
            return False, f"none of {len(voters)} voters' LIS ids in today's cvc"
        member = _cg(congress, f"member/{crosswalk[present]}").get("member", {})
        return member.get("bioguideId") == crosswalk[present], (
            f"LIS {present} → cvc → {crosswalk[present]} → member; {len(absent)} of {len(voters)} voters' LIS ids "
            f"are absent from today's cvc {absent[:4]}"
        )

    def senate_vote_document() -> tuple[bool, str]:
        root = senate_vote_root()
        kind = (_texts(root, {"document_type"}) or [""])[0]
        number = (_texts(root, {"document_number"}) or [""])[0]
        if kind.startswith("PN"):
            detail = _cg(congress, f"nomination/{CURRENT_CONGRESS}/{number}").get("nomination", {})
            return str(detail.get("number")) == number, f"{kind} {number} → nomination"
        code = {
            "S.": "s",
            "H.R.": "hr",
            "S.J.Res.": "sjres",
            "H.J.Res.": "hjres",
            "S.Res.": "sres",
            "H.Res.": "hres",
        }.get(kind, kind.replace(".", "").lower())
        bill = _cg(congress, f"bill/{CURRENT_CONGRESS}/{code}/{number}").get("bill", {})
        return str(bill.get("number")) == number, f"{kind} {number} → bill/{CURRENT_CONGRESS}/{code}/{number}"

    def senate_hearings_committee() -> tuple[bool, str]:
        root = _xml(probe, SAMPLES["senate-hearings"][0], "hearings")
        code = (_texts(root, {"cmte_code"}) or [""])[0]
        system = _system_code("senate", code[:4]) if code else ""
        committee = _cg(congress, f"committee/senate/{system}").get("committee", {}) if system else {}
        return committee.get("systemCode") == system, f"cmte_code {code} → {system} → {_committee_name(committee)}"

    run(
        Edge(
            "nomination→committee",
            "Congress.gov nomination",
            "Congress.gov committee",
            "nomination/{c}/{n}/committees[].systemCode",
            "id",
        ),
        nomination_committee,
    )
    run(
        Edge(
            "nomination→hearing",
            "Congress.gov nomination",
            "Congress.gov hearing",
            "nomination/{c}/{n}/hearings[].jacketNumber",
            "id",
        ),
        nomination_hearing,
    )
    run(
        Edge(
            "feed→nomination",
            "Senate nomination feed",
            "Congress.gov nomination",
            "PN number → nomination/{c}/{n}",
            "id",
        ),
        feed_nomination,
    )
    run(
        Edge(
            "feed→committee",
            "Senate nomination feed",
            "Congress.gov committee",
            "Senate committee code → systemCode `{code}00`",
            "derived",
        ),
        feed_committee,
    )
    run(
        Edge(
            "house-vote→bill",
            "Congress.gov house-vote",
            "Congress.gov bill",
            "legislationType + legislationNumber → bill",
            "id",
        ),
        house_vote_bill,
    )
    run(
        Edge(
            "house-vote→member",
            "Congress.gov house-vote",
            "Congress.gov member",
            "members[].bioguideID → member/{id}",
            "id",
        ),
        house_vote_member,
    )
    run(
        Edge("member→bill", "Congress.gov member", "Congress.gov bill", "sponsored-legislation[] → bill", "id"),
        member_bill,
    )
    run(
        Edge("member→house-file", "Congress.gov member", "House members.xml", "bioguideId ↔ Member@bioguide_id", "id"),
        member_house_file,
    )
    run(
        Edge(
            "memberdata→committee",
            "House MemberData.xml",
            "Congress.gov committee",
            "committee-assignment@comcode → systemCode `hs{code}`",
            "derived",
        ),
        clerk_committee,
    )
    run(
        Edge(
            "cvc→member",
            "Senate cvc XML",
            "Congress.gov member",
            "senator.bioguide_id → member/{id}; carries lis_member_id",
            "id",
        ),
        cvc_member,
    )
    run(
        Edge(
            "cvc→committee",
            "Senate cvc XML",
            "Congress.gov committee",
            "committee code → systemCode `{code}00`",
            "derived",
        ),
        cvc_committee,
    )
    run(
        Edge(
            "senate-vote→member",
            "Senate vote XML",
            "Congress.gov member",
            "member.lis_member_id → cvc bioguide_id → member/{id}",
            "derived",
        ),
        senate_vote_member,
    )
    run(
        Edge(
            "senate-vote→document",
            "Senate vote XML",
            "Congress.gov bill or nomination",
            "document_type + document_number → bill or nomination",
            "derived",
        ),
        senate_vote_document,
    )
    run(
        Edge(
            "senate-hearings→committee",
            "Senate hearings.xml",
            "Congress.gov committee",
            "meeting.cmte_code → systemCode",
            "derived",
        ),
        senate_hearings_committee,
    )

    # Treaties, the Record, CRS
    def treaty_cdoc() -> tuple[bool, str]:
        row = _cg(congress, f"treaty/{CURRENT_CONGRESS}?limit=1").get("treaties", [{}])[0]
        number = row.get("number")
        package = f"CDOC-{row.get('congressReceived', CURRENT_CONGRESS)}tdoc{number}"
        summary = _gi(govinfo, f"packages/{package}/summary")
        return summary.get("packageId") == package, f"treaty {number} → {package} ({summary.get('title', '')[:40]})"

    def record_package() -> tuple[bool, str]:
        row = _cg(congress, f"daily-congressional-record/{COMPARE_VOLUME}?limit=1").get(
            "dailyCongressionalRecord", [{}]
        )[0]
        detail = _cg(congress, f"daily-congressional-record/{COMPARE_VOLUME}/{row.get('issueNumber')}").get("issue", {})
        url = next(
            (
                x.get("url", "")
                for x in (detail.get("fullIssue") or {}).get("entireIssue", [])
                if "CREC-" in x.get("url", "")
            ),
            "",
        )
        package = _package_id(url)
        summary = _gi(govinfo, f"packages/{package}/summary") if package else {}
        return (
            bool(package) and summary.get("packageId") == package,
            f"vol {COMPARE_VOLUME} issue {row.get('issueNumber')} entireIssue {urlsplit(url).netloc} → GovInfo {package}",
        )

    def crs_detail() -> Mapping[str, Any]:
        if "crs" not in cache:
            row = _cg(congress, "crsreport?limit=1").get("CRSReports", [{}])[0]
            cache["crs"] = _cg(congress, f"crsreport/{row.get('id')}").get("CRSReport", {})
        return cache["crs"]

    def crs_bill() -> tuple[bool, str]:
        related = crs_detail().get("relatedMaterials", [])
        item = next((r for r in related if r.get("URL")), None)
        if not item:
            return False, f"{crs_detail().get('id')} lists no related material with a URL"
        url = str(item["URL"]).split("?")[0]
        value = _keyed_json(congress, f"{url}?format=json")
        target = next((k for k in value if k not in ("request", "pagination")), "")
        return (
            bool(target),
            f"{crs_detail().get('id')} relatedMaterials type {item.get('type')} {item.get('number')} → {urlsplit(url).path} → {target}",
        )

    def crs_pdf() -> tuple[bool, str]:
        fmt = next((f for f in crs_detail().get("formats", []) if str(f.get("format", "")).upper() == "PDF"), {})
        url = fmt.get("url", "")
        ok, evidence = keyless_exists(url, ("application/pdf",))
        return ok, f"{crs_detail().get('id')} → {urlsplit(url).path} → {evidence}"

    run(
        Edge(
            "treaty→cdoc",
            "Congress.gov treaty",
            "GovInfo CDOC package",
            "treaty number → package id CDOC-{c}tdoc{n}",
            "derived",
        ),
        treaty_cdoc,
    )
    run(
        Edge(
            "record→package",
            "Congress.gov daily-congressional-record",
            "GovInfo CREC package",
            "issue links → package id CREC-{date}",
            "derived",
        ),
        record_package,
    )
    run(
        Edge(
            "crs→law-or-bill",
            "Congress.gov crsreport",
            "Congress.gov law",
            "relatedMaterials[].URL (laws and bills) → law/{c}/pub/{n}",
            "url",
        ),
        crs_bill,
    )
    run(Edge("crs→pdf", "Congress.gov crsreport", "congress.gov CRS PDF", "formats[].url (keyless)", "url"), crs_pdf)

    # Laws: PLAW, Statutes, the Code
    lc, ln = FLOW_LAW

    def plaw_meta() -> dict[str, Any]:
        if "plaw" not in cache:
            url = f"https://www.govinfo.gov/bulkdata/PLAW/{lc}/public/PLAW-{lc}publ{ln}.xml"
            root = _xml(probe, url, "plaw")
            citable = _texts(root, {"citableAs"})
            usc = sum(1 for el in root.iter() if str(el.get("href", "")).startswith("/us/usc/"))
            cache["plaw"] = {"citableAs": citable, "uscRefs": usc}
        return cache["plaw"]

    def plaw_usc() -> tuple[bool, str]:
        meta = plaw_meta()
        return meta[
            "uscRefs"
        ] > 0, f"PLAW-{lc}publ{ln}: {meta['uscRefs']} refs to /us/usc/…; citableAs {meta['citableAs'][:3]}"

    def plaw_statute() -> tuple[bool, str]:
        stat = next((s for s in plaw_meta()["citableAs"] if "Stat." in s), "")
        volume = stat.split()[0] if stat else ""
        try:
            names = [str(f.get("name")) for f in _bulk_listing(probe, f"STATUTE/{volume}")]
            return any(x.endswith(".xml") for x in names), f"{stat} → STATUTE/{volume} {names[:2]}"
        except ProbeError:
            files = [str(f.get("name")) for f in _bulk_listing(probe, "STATUTE/135")]
            return any(x.endswith(".xml") for x in files), (
                f"rule proved on {FLOW_OLD_LAW} → STATUTE/135 {files[:1]}; {stat} → STATUTE/{volume} not in bulk yet (newest volume 137)"
            )

    def plaw_related() -> tuple[bool, str]:
        value = _gi(govinfo, f"related/PLAW-{lc}publ{ln}")
        collections = [r.get("collection") for r in value.get("relationships", [])]
        bills = [r for r in value.get("relationships", []) if r.get("collection") == "BILLS"]
        packages: list[str] = []
        if bills:
            follow = _keyed_json(govinfo, bills[0]["relationshipLink"])
            packages = [str(p.get("packageId")) for p in follow.get("results", [])][:3]
        return bool(collections), f"related collections {collections}; BILLS → {packages}"

    def bills_related() -> tuple[bool, str]:
        value = _gi(govinfo, f"related/BILLS-{c}{t}{n}enr")
        collections = [r.get("collection") for r in value.get("relationships", [])]
        return bool(collections), f"BILLS-{c}{t}{n}enr related collections {collections}"

    def law_table3() -> tuple[bool, str]:
        from spicy_docs.sources.uscode import parse_table3_page, table3_act_locator

        url = table3_act_locator(FLOW_OLD_LAW)
        capture = probe.get(url, media_types=HTML_TYPES, max_bytes=4 * 1024 * 1024)
        try:
            page = parse_table3_page(capture.body, key=FLOW_OLD_LAW, max_bytes=capture.byte_size)
        except ValueError as error:
            return False, f"{url} → {capture.byte_size:,} B; parse_table3_page refused: {str(error)[:60]}"
        return True, (
            f"{url} → {capture.byte_size:,} B; page states act {page.stated_key}, Congress {page.congress}, "
            f"{page.statutes_at_large_volume} Stat."
        )

    def law_classification() -> tuple[bool, str]:
        index = probe.get(OLRC_TABLES, media_types=HTML_TYPES, max_bytes=4 * 1024 * 1024).body.decode(
            "utf-8", "replace"
        )
        hrefs = re.findall(r'href="([^"]+)"', index)
        target = next((h for h in hrefs if str(lc) in h and h.endswith((".htm", ".html", ".shtml"))), None)
        if not target:
            return False, f"no {lc}th table linked from {OLRC_TABLES}"
        url = (
            target
            if target.startswith("http")
            else f"https://uscode.house.gov/classification/{target.lstrip('/').removeprefix('classification/')}"
        )
        body = probe.get(url, media_types=HTML_TYPES, max_bytes=8 * 1024 * 1024).body.decode("utf-8", "replace")
        key = f"{lc}-{ln}"
        return key in body, f"{url} states {key}: {key in body}"

    run(
        Edge("plaw→usc", "GovInfo PLAW USLM", "US Code sections", '<ref href="/us/usc/t…/s…"> in the law text', "id"),
        plaw_usc,
    )
    run(
        Edge(
            "plaw→statute",
            "GovInfo PLAW USLM",
            "GovInfo STATUTE volume",
            "meta citableAs `NNN Stat. NNN` → bulkdata/STATUTE/{volume}",
            "derived",
        ),
        plaw_statute,
    )
    run(
        Edge(
            "plaw→related",
            "GovInfo PLAW",
            "GovInfo related service",
            "related/{packageId} → BILLS, CREC, … package ids",
            "id",
        ),
        plaw_related,
    )
    run(
        Edge("bills→related", "GovInfo BILLS", "GovInfo related service", "related/BILLS-{c}{type}{n}{version}", "id"),
        bills_related,
    )
    run(
        Edge(
            "law→table3",
            "Public law number",
            "OLRC Table III",
            f"`table3_act_locator` ({FLOW_OLD_LAW}) → act page stating the number",
            "derived",
        ),
        law_table3,
    )
    run(
        Edge(
            "law→classification",
            "Public law number",
            "OLRC classification tables",
            "tables.shtml → per-Congress table → law number",
            "derived",
        ),
        law_classification,
    )

    # Floor, CBO, LDA
    def floor_bill() -> tuple[bool, str]:
        from datetime import timedelta

        today = datetime.now(UTC).date()
        monday = today - timedelta(days=today.weekday())
        for weeks in range(6):
            stamp = (monday - timedelta(weeks=weeks)).strftime("%Y%m%d")
            url = f"https://docs.house.gov/floor/Download.aspx?file=/billsthisweek/{stamp}/{stamp}.xml"
            try:
                capture = probe.get(
                    url,
                    media_types=(*XML_TYPES, "application/x-octet-stream", "application/octet-stream"),
                    max_bytes=SAMPLE_MAX_BYTES,
                )
                root = parse_xml(
                    capture.body,
                    max_bytes=len(capture.body),
                    error_type=ProbeError,
                    label="floor",
                    allow_external_doctype=True,
                    max_depth=64,
                )
            except ProbeError:
                continue
            legis = next((x for x in _texts(root, {"legis-num"}) if re.match(r"H\.?\s?R\.?\s?\d+|S\.\s?\d+", x)), "")
            match = re.match(r"(H\.?\s?R\.?|S\.)\s?(\d+)", legis)
            if not match:
                return False, f"{stamp}: floor items carry no bill number"
            code = "hr" if match[1].upper().startswith("H") else "s"
            bill = _cg(congress, f"bill/{CURRENT_CONGRESS}/{code}/{match[2]}").get("bill", {})
            return str(bill.get("number")) == match[
                2
            ], f"{stamp} legis-num {legis!r} → bill/{CURRENT_CONGRESS}/{code}/{match[2]}"
        return False, "no weekly floor XML answered for the last six Mondays"

    def cbo_bill() -> tuple[bool, str]:
        root = _xml(probe, CBO_FEED, "cbo")
        numbers = _texts(root, {"Bill_Number"})
        match = next(
            (
                re.match(r"(H\.R\.|S\.|H\.J\.Res\.|S\.J\.Res\.)\s?(\d+)", x)
                for x in numbers
                if re.match(r"(H\.R\.|S\.)", x)
            ),
            None,
        )
        if not match:
            return False, f"no Bill_Number element parsed; {len(numbers)} present"
        code = {"H.R.": "hr", "S.": "s", "H.J.Res.": "hjres", "S.J.Res.": "sjres"}[match[1]]
        bill = _cg(congress, f"bill/{CURRENT_CONGRESS}/{code}/{match[2]}").get("bill", {})
        return str(bill.get("number")) == match[
            2
        ], f"item Bill_Number {match[0]!r} → bill/{CURRENT_CONGRESS}/{code}/{match[2]}"

    def lda_first() -> Mapping[str, Any]:
        if "lda" not in cache:
            capture = probe.get(
                "https://lda.gov/api/v1/filings/?page_size=1&filing_year=2026",
                media_types=JSON_TYPES,
                max_bytes=4 * 1024 * 1024,
            )
            cache["lda"] = json.loads(capture.body).get("results", [{}])[0]
        return cache["lda"]

    def lda_registrant() -> tuple[bool, str]:
        rid = (lda_first().get("registrant") or {}).get("id")
        capture = probe.get(
            f"https://lda.gov/api/v1/registrants/{rid}/", media_types=JSON_TYPES, max_bytes=4 * 1024 * 1024
        )
        value = json.loads(capture.body)
        return (
            value.get("id") == rid,
            f"filing {str(lda_first().get('filing_uuid', ''))[:8]} → registrant {rid} {str(value.get('name', ''))[:30]!r}",
        )

    def lda_bill_text() -> tuple[bool, str]:
        capture = probe.get(
            "https://lda.gov/api/v1/filings/?page_size=25&filing_year=2026",
            media_types=JSON_TYPES,
            max_bytes=8 * 1024 * 1024,
        )
        filings = json.loads(capture.body).get("results", [])
        mentioning = 0
        sample: list[str] = []
        for filing in filings:
            refs = [
                m
                for a in filing.get("lobbying_activities", [])
                for m in re.findall(r"\b(?:H\.R\.|S\.)\s?\d+", a.get("description") or "")
            ]
            mentioning += bool(refs)
            sample = sample or refs[:2]
        return (
            mentioning > 0,
            f"{mentioning} of {len(filings)} filings name a bill in free text {sample}; no structured bill field exists",
        )

    run(
        Edge(
            "floor→bill",
            "docs.house.gov weekly floor XML",
            "Congress.gov bill",
            "floor-item.legis-num → bill/{c}/{type}/{n}",
            "derived",
        ),
        floor_bill,
    )
    run(
        Edge("cbo→bill", "CBO cost-estimate feed", "Congress.gov bill", "item Bill_Number → bill/{c}/{type}/{n}", "id"),
        cbo_bill,
    )
    run(
        Edge("lda→registrant", "LDA filings", "LDA registrants", "registrant.id → registrants/{id}", "id"),
        lda_registrant,
    )
    run(
        Edge("lda→bill", "LDA filings", "Congress.gov bill", "lobbying_activities[].description free text", "text"),
        lda_bill_text,
    )

    # Communications, requirements, the regulatory bridge, the identifier hub, legislative days
    def communication_details() -> list[Mapping[str, Any]]:
        """The 25 newest House communications, in detail."""
        if "communication_details" not in cache:
            rows = _cg(congress, f"house-communication/{CURRENT_CONGRESS}?limit=25").get("houseCommunications", [])
            cache["communication_details"] = [
                _keyed_json(congress, f"{str(row.get('url', '')).split('?')[0]}?format=json").get(
                    "houseCommunication", {}
                )
                for row in rows
            ]
        return cache["communication_details"]

    def house_communication() -> Mapping[str, Any]:
        """The first sampled communication that is a rulemaking with a RIN, else the first."""
        details = communication_details()
        return next(
            (d for d in details if re.search(r"RIN:?\s*\d{4}-[A-Z]{2}\d{2}", str(d.get("reportNature", "")))),
            details[0] if details else {},
        )

    def communication_typing() -> tuple[bool, str]:
        details = communication_details()
        rulemaking = sum(1 for d in details if str(d.get("isRulemaking")) == "True")
        with_rin = sum(1 for d in details if re.search(r"RIN:?\s*\d{4}-[A-Z]{2}\d{2}", str(d.get("reportNature", ""))))
        referred = sum(1 for d in details if d.get("committees"))
        required = sum(1 for d in details if d.get("matchingRequirements"))
        dated = sum(1 for d in details if d.get("congressionalRecordDate"))
        return bool(details), (
            f"of the {len(details)} newest: {rulemaking} rulemakings, {with_rin} with a RIN, {referred} with a committee referral, "
            f"{required} naming a requirement, {dated} with a Record date"
        )

    def communication_committee() -> tuple[bool, str]:
        detail = house_communication()
        code = (detail.get("committees") or [{}])[0].get("systemCode")
        committee = _cg(congress, f"committee/house/{code}").get("committee", {}) if code else {}
        return (
            committee.get("systemCode") == code,
            f"EC {detail.get('number')} referred {code} on {(detail.get('committees') or [{}])[0].get('referralDate')} → {_committee_name(committee)}",
        )

    def communication_requirement() -> tuple[bool, str]:
        detail = house_communication()
        req = (detail.get("matchingRequirements") or [{}])[0]
        number = req.get("number")
        if number is None:
            return False, f"EC {detail.get('number')} names no matching requirement"
        requirement = _cg(congress, f"house-requirement/{number}").get("houseRequirement", {})
        return str(requirement.get("number")) == str(
            number
        ), f"EC {detail.get('number')} → requirement {number}: {str(requirement.get('nature', ''))[:50]!r}"

    def communication_federal_register() -> tuple[bool, str]:
        detail = house_communication()
        match = re.search(r"RIN:?\s*(\d{4}-[A-Z]{2}\d{2})", str(detail.get("reportNature", "")))
        if not match:
            return False, f"EC {detail.get('number')} states no RIN"
        rin = match[1]
        query = urlencode({"conditions[regulation_id_number]": rin, "per_page": 5, "fields[]": "regulation_id_numbers"})
        capture = probe.get(
            f"https://www.federalregister.gov/api/v1/documents.json?{query}",
            media_types=JSON_TYPES,
            max_bytes=4 * 1024 * 1024,
        )
        value = json.loads(capture.body)
        results = value.get("results", [])
        hits = [(r.get("document_number"), r.get("regulation_id_numbers")) for r in results]
        keyed = bool(results) and all(rin in (r.get("regulation_id_numbers") or []) for r in results)
        return keyed, (
            f"EC {detail.get('number')} RIN {rin} → Federal Register API regulation_id_number filter: {value.get('count')} documents, "
            f"each carrying the RIN as a structured field {hits[:3]}"
        )

    def requirement_communications() -> tuple[bool, str]:
        """The list resolves; whether the communications it names have a detail route is checked at both ends."""
        value = _cg(congress, "house-requirement/8070/matching-communications?limit=1")
        count = int(value.get("pagination", {}).get("count") or 0)
        last = _cg(congress, f"house-requirement/8070/matching-communications?limit=1&offset={max(count - 1, 0)}")
        outcomes = []
        resolved = False
        for row in (value.get("matchingCommunications") or [{}])[:1] + (last.get("matchingCommunications") or [{}])[:1]:
            code = str(row.get("communicationType", {}).get("code", "")).lower()
            label = f"{row.get('congress')}th {code.upper()} {row.get('number')}"
            try:
                detail = _cg(congress, f"house-communication/{row.get('congress')}/{code}/{row.get('number')}").get(
                    "houseCommunication", {}
                )
                ok = str(detail.get("number")) == str(row.get("number"))
                resolved = resolved or ok
                outcomes.append(f"{label} detail {'resolves' if ok else 'differs'}")
            except ProbeUnavailableError:
                outcomes.append(f"{label} detail 404")
        return (
            resolved,
            f"requirement 8070 (CRA) lists {count:,} communications, unordered by Congress; {'; '.join(outcomes)}",
        )

    def senate_communication_committee() -> tuple[bool, str]:
        row = _cg(congress, f"senate-communication/{CURRENT_CONGRESS}?limit=1").get("senateCommunications", [{}])[0]
        url = str(row.get("url", "")).split("?")[0]
        detail = _keyed_json(congress, f"{url}?format=json").get("senateCommunication", {})
        code = (detail.get("committees") or [{}])[0].get("systemCode")
        committee = _cg(congress, f"committee/senate/{code}").get("committee", {}) if code else {}
        return (
            committee.get("systemCode") == code,
            f"EC {detail.get('number')} → {code} → {_committee_name(committee)}; typed fields {sorted(detail)[:8]}",
        )

    def legislators() -> list[Mapping[str, Any]]:
        if "legislators" not in cache:
            capture = probe.get(
                SAMPLES["legislators-historical-json"][0], media_types=JSON_TYPES, max_bytes=SAMPLE_MAX_BYTES
            )
            cache["legislators"] = json.loads(capture.body)
        return cache["legislators"]

    def legislators_former_senator() -> tuple[bool, str]:
        voters = _texts(senate_vote_root(), {"lis_member_id"})
        crosswalk = {f.get("lis_member_id") for f in cvc_senators()}
        absent = [lis for lis in voters if lis not in crosswalk]
        by_lis = {str((r.get("id") or {}).get("lis")): r for r in legislators() if (r.get("id") or {}).get("lis")}
        found = [(lis, by_lis[lis]["id"].get("bioguide")) for lis in absent if lis in by_lis]
        if not found:
            return False, f"none of the {len(absent)} LIS ids absent from cvc appear in the historical JSON"
        lis, bioguide = found[0]
        member = _cg(congress, f"member/{bioguide}").get("member", {})
        return member.get(
            "bioguideId"
        ) == bioguide, f"{len(found)} of {len(absent)} absent LIS ids resolve via the JSON; {lis} → {bioguide} → member"

    def legislators_fec() -> tuple[bool, str]:
        record = next((r for r in legislators() if (r.get("id") or {}).get("fec")), None)
        if not record:
            return False, "no historical record carries an FEC id"
        fec_id = record["id"]["fec"][0]
        value = _keyed_json(congress, f"https://api.open.fec.gov/v1/candidate/{fec_id}/?{urlencode({'per_page': 1})}")
        result = (value.get("results") or [{}])[0]
        return (
            result.get("candidate_id") == fec_id,
            f"{record['id'].get('bioguide')} id.fec {fec_id} → FEC API candidate {result.get('name', '')[:30]!r}",
        )

    def record_legislative_day() -> tuple[bool, str]:
        rows = _cg(congress, f"daily-congressional-record/{COMPARE_VOLUME}?limit=5").get("dailyCongressionalRecord", [])
        seen = []
        for row in rows:
            detail = _cg(congress, f"daily-congressional-record/{COMPARE_VOLUME}/{row.get('issueNumber')}").get(
                "issue", {}
            )
            names = [x.get("name") for x in (detail.get("fullIssue") or {}).get("sections", [])]
            chambers = "+".join(
                "H" if n == "House Section" else "S" for n in names if n in ("House Section", "Senate Section")
            )
            seen.append(f"{str(detail.get('issueDate', ''))[:10]} {chambers or 'none'}")
        return bool(seen) and all(
            not x.endswith("none") for x in seen
        ), f"chamber sections per issue: {', '.join(seen)}"

    run(
        Edge(
            "communication-typing",
            "Congress.gov house-communication",
            "Congress.gov house-communication",
            "detail fields on the 25 newest: isRulemaking, RIN, committees, matchingRequirements, congressionalRecordDate",
            "id",
        ),
        communication_typing,
    )
    run(
        Edge(
            "communication→committee",
            "Congress.gov house-communication",
            "Congress.gov committee",
            "committees[].systemCode + referralDate → committee/house/{code}",
            "id",
        ),
        communication_committee,
    )
    run(
        Edge(
            "communication→requirement",
            "Congress.gov house-communication",
            "Congress.gov house-requirement",
            "matchingRequirements[].number → house-requirement/{n}",
            "id",
        ),
        communication_requirement,
    )
    run(
        Edge(
            "communication→federal-register",
            "Congress.gov house-communication",
            "Federal Register document",
            "reportNature `RIN: nnnn-XXnn` → federalregister.gov/api/v1/documents?conditions[regulation_id_number]=RIN",
            "id",
        ),
        communication_federal_register,
    )
    run(
        Edge(
            "requirement→communications",
            "Congress.gov house-requirement",
            "Congress.gov house-communication",
            "house-requirement/{n}/matching-communications[] → house-communication/{c}/{type}/{n}",
            "id",
        ),
        requirement_communications,
    )
    run(
        Edge(
            "senate-communication→committee",
            "Congress.gov senate-communication",
            "Congress.gov committee",
            "committees[].systemCode → committee/senate/{code}",
            "id",
        ),
        senate_communication_committee,
    )
    run(
        Edge(
            "legislators→former-senator",
            "Legislators JSON",
            "Congress.gov member",
            "id.lis (absent from cvc) → id.bioguide → member/{id}",
            "id",
        ),
        legislators_former_senator,
    )
    run(
        Edge(
            "legislators→fec",
            "Legislators JSON",
            "FEC candidate",
            "id.fec[] → api.open.fec.gov/v1/candidate/{id}",
            "id",
        ),
        legislators_fec,
    )
    run(
        Edge(
            "record→legislative-day",
            "Congress.gov daily-congressional-record",
            "Legislative day per chamber",
            "issue fullIssue.sections names (House Section, Senate Section)",
            "derived",
        ),
        record_legislative_day,
    )
    return results


FLOW_NODES = {
    "Congress.gov bill": "CGbill", "Congress.gov member": "CGmember", "Congress.gov committee": "CGcommittee",
    "Congress.gov committee-report": "CGreport", "Congress.gov law": "CGlaw", "Congress.gov house-vote": "CGvote",
    "Congress.gov amendment": "CGamendment", "Congress.gov hearing": "CGhearing", "Congress.gov committee-meeting": "CGmeeting",
    "Congress.gov nomination": "CGnomination", "Congress.gov treaty": "CGtreaty", "Congress.gov daily-congressional-record": "CGrecord",
    "Congress.gov crsreport": "CGcrs", "Congress.gov bill or nomination": "CGbill",
    "GovInfo BILLS package": "GIbills", "GovInfo CRPT package": "GIcrpt", "GovInfo CHRG package": "GIchrg", "GovInfo CDOC package": "GIcdoc",
    "GovInfo CREC package": "GIcrec", "GovInfo PLAW USLM": "GIplaw", "GovInfo PLAW": "GIplaw", "GovInfo BILLS": "GIbills",
    "GovInfo STATUTE volume": "GIstatute", "GovInfo related service": "GIrelated", "US Code sections": "USC",
    "Public law number": "PL", "OLRC Table III": "OLRCt3", "OLRC classification tables": "OLRCclass",
    "Clerk vote XML": "ClerkVote", "Senate vote XML": "SenVote", "House members.xml": "HouseMembers", "House MemberData.xml": "MemberData",
    "Senate cvc XML": "CVC", "Senate hearings.xml": "SenHearings", "Senate nomination feed": "NomFeed",
    "docs.house.gov / congress.gov documents": "Docs", "docs.house.gov weekly floor XML": "Floor", "CBO estimate page": "CBOpage",
    "CBO cost-estimate feed": "CBOfeed", "congress.gov CRS PDF": "CRSpdf", "LDA filings": "LDAfilings", "LDA registrants": "LDAregistrants",
    "Congress.gov house-communication": "CGhcomm", "Congress.gov senate-communication": "CGscomm",
    "Congress.gov house-requirement": "CGreq", "Federal Register document": "FR", "Legislators JSON": "LegJSON",
    "FEC candidate": "FEC", "Legislative day per chamber": "LegDay",
}  # fmt: skip
FLOW_LABELS = {"PL": "Public law number", "USC": "US Code section"}
# Sources the tables hold that no probed edge reaches yet, with the join each would carry. Drawn apart, never as arrows.
UNJOINED = (
    ("BILLSTATUS, BILLS, BILLSUM bulk zips", "file name BILLSTATUS-119hr1.xml is the bill key (derived); unprobed"),
    ("Statutes at Large volume", "each volume states the public laws it holds; reached only as a target"),
    ("Statute compilations (COMPS)", "currency statement names the last public law folded in; unprobed"),
    ("Bill PDFs, committee prints, bound Record", "package ids by the same stem rule; unprobed"),
    ("Congressional Directory, Government Manual, House Manual", "names of members, committees and agencies; no key"),
    ("House Rules Committee, House floor summary", "bill numbers in page text; unprobed"),
    ("House LDA filings", "Senate API registrant.house_registrant_id names the House record; unprobed"),
    ("LDA contributions, clients, lobbyists", "registrant and client ids on the same API; unprobed"),
    ("Statement of Disbursements, Secretary of the Senate report", "member office names, no bioguide"),
    ("PLUM report", "agency and position codes; no legislative key"),
    ("GAO products and legal decisions", "public laws and bills cited in text; unprobed"),
    ("JCT estimates", "bill numbers in titles; unprobed"),
    ("CISA .gov registry", "agency names; no legislative key"),
    ("EveryCRSReport", "CRS report ids in its index; unprobed"),
    ("Press releases", "bill mentions in text; interpretation stays BillTrax-side"),
)  # fmt: skip


def _node(label: str) -> str:
    return FLOW_NODES.get(label, re.sub(r"\W", "", label))


def render_flow(measures: Mapping[str, Any]) -> list[str]:
    flow = measures.get("flow")
    if not flow:
        return []
    samples = measures.get("flowSamples") or {}
    ok = sum(1 for e in flow.values() if e.get("ok"))
    sampled = (
        f" Each sampled edge shows resolved-of-tried over {measures.get('flowSampleSize')} items." if samples else ""
    )
    lines = [
        "### Data flow: what references what, validated on one real item per edge",
        "",
        (
            f"Measured {str(measures.get('flowAt', ''))[:10]} in {sum(measures.get('flowRequests', {}).values())} requests: "
            f"{ok} of {len(flow)} edges resolved. Solid arrows resolved; dotted did not, and the table says why. "
            "`id` is an identifier the target keys on, `derived` an id built by a stated rule, `url` a URL the source "
            f"states, `text` a mention in free text with no structured field.{sampled}"
        ),
        "",
        "```mermaid",
        "graph LR",
    ]
    seen: set[str] = set()
    for e in flow.values():
        for label in (e["source"], e["target"]):
            node = _node(label)
            if node not in seen:
                seen.add(node)
                lines.append(f'    {node}["{FLOW_LABELS.get(node, label)}"]')
    for e in flow.values():
        arrow = "-->" if e.get("ok") else "-.->"
        lines.append(f"    {_node(e['source'])} {arrow}|{e['key'].split('→')[-1]}| {_node(e['target'])}")
    lines.append('    subgraph unjoined ["In the tables, no probed edge yet"]')
    for index, (name, join) in enumerate(UNJOINED):
        lines.append(f'        U{index}["{name}: {join}"]')
    lines.append("    end")
    lines += ["```", "", "| Edge | From | To | How | Kind | Resolved | Evidence |", "|---|---|---|---|---|---|---|"]

    def resolved_cell(key: str, ok: bool) -> tuple[str, str]:
        sample = samples.get(key)
        if not sample or not sample.get("tried"):
            return ("yes" if ok else "no"), ""
        extra = f"; sampled failures: {'; '.join(sample.get('failures', [])[:2])}" if sample.get("failures") else ""
        return f"{'yes' if ok else 'no'} · {sample['resolved']}/{sample['tried']}", extra

    for e in flow.values():
        cell, extra = resolved_cell(e["key"], bool(e.get("ok")))
        cells = (
            e["key"],
            e["source"],
            e["target"],
            e["via"],
            e["kind"],
            cell,
            (e.get("evidence", "")[:160] + extra)[:300],
        )
        lines.append("| " + " | ".join(_cell(v) for v in cells) + " |")
    for key, (source, target, via, kind) in SAMPLE_ONLY.items():
        sample = samples.get(key)
        if not sample:
            continue
        cell = f"{sample['resolved']}/{sample['tried']}"
        extra = "; ".join(sample.get("failures", [])[:2])
        lines.append("| " + " | ".join(_cell(v) for v in (key, source, target, via, kind, cell, extra)) + " |")
    senate = samples.get("senate-vote→member")
    if senate and senate.get("byVote"):
        lines.append("")
        lines.append(
            f"Senate roster gap across the session: {senate['resolved']:,} of {senate['tried']:,} voter ids on "
            f"{len(senate['byVote'])} sampled votes resolve through today's cvc, and {senate.get('resolvedViaLegislatorsJson', 0):,} "
            "more through the legislators JSON. Absent from cvc per vote: "
            + ", ".join(f"vote {v['vote']} ({v['date']}) {v['absentFromCvc']}" for v in senate["byVote"])
            + "."
        )
    lines.append("")
    return lines


# A6's proposal row names the rule ("host only if the detail era covers a useful share") but no
# number: no `docs/decisions.md` record and no other gap row states one. A majority is the plain
# reading of "useful" absent a more specific rule -- a hosted table whose newer, more active half
# has no rows at all would mislead a consumer more than the missing table does -- so this measurement
# adopts one-half as its own stated default, not a prior decision; revisit if `decisions.md` records
# a different bound.
REQUIREMENTS_USEFUL_SHARE = 0.5


def render_requirements(measures: Mapping[str, Any]) -> list[str]:
    """A6: requirement 8070's histogram and detail floor, read against the proposal's useful-share rule."""
    data = measures.get("requirements")
    if not data:
        return []
    histogram = data.get("histogram", {})
    total = data.get("total", 0)
    floor = data.get("detailFloor")
    covered = data.get("coveredByFloor", 0)
    share = data.get("share", 0.0)
    lines = ["### House reporting requirements: the 8070 histogram (A6)", ""]
    if histogram:
        span = (
            f"the {_ordinal(int(min(histogram, key=int)))} through {_ordinal(int(max(histogram, key=int)))} Congresses"
        )
    else:
        span = "no Congress"
    lines.append(
        f"Requirement 8070's `matching-communications` list walked in full, keyed, once: {total:,} rows "
        f"across {span}. Probing one communication's detail record per Congress from the 105th "
        f"through the {_ordinal(CURRENT_CONGRESS)} finds the detail route answering from "
        + (f"the {_ordinal(floor)} Congress on" if floor is not None else "no Congress in that range")
        + f", so {covered:,} of the {total:,} walked rows ({share:.1%}) fall in the detail era."
    )
    if floor is not None:
        useful = (
            "a useful share, so `house_requirements` is worth hosting"
            if share >= REQUIREMENTS_USEFUL_SHARE
            else ("not a useful share, so `house_requirements` stays a candidate rather than a hosted table")
        )
        lines.append(
            f"By the proposal's rule -- host only if the detail era covers a useful share -- {share:.1%} is {useful} "
            f"(this measurement's own stated threshold: {REQUIREMENTS_USEFUL_SHARE:.0%}, a majority; no decisions.md "
            f"record sets one)."
        )
    lines.append("")
    return lines


SAMPLE_ONLY = {
    "law→plaw-bulk": ("Congress.gov law", "GovInfo PLAW bulkdata", "law number → PLAW-{c}publ{n}.xml present in the bulk folder", "derived"),
    "house-vote→source-xml": ("Congress.gov house-vote", "Clerk vote XML", "sourceDataURL answers and names the same roll", "url"),
}  # fmt: skip
