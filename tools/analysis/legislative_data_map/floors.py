"""Floors, edge samples and drift: descents past recorded floors and per-edge sampling."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from spicy_docs.reading.paged_json import PagedJsonReader, PagedJsonSourceError
from spicy_docs.transport.credentials import scrub_credential
from tools.analysis.legislative_data_map.capture import (
    COMPARE_VOLUME,
    ERROR_TOLERANCE,
    SAMPLE_MAX_BYTES,
    _bulk_listing,
    _congress_url,
    _count,
    _keyed_json,
    _texts,
    _walk,
    _xml,
)
from tools.analysis.legislative_data_map.flow import (
    COMMITTEE_CHAMBER,
    _bill_ref,
    _cg,
    _gi,
    _package_id,
    _stated_congress_path,
)
from tools.analysis.legislative_data_map.rows import CONGRESS_ROUTES, CURRENT_CONGRESS, SAMPLES
from tools.analysis.shared import (
    CONGRESS_API,
    JSON_TYPES,
    KeylessProbe,
    ProbeError,
    local_name,
)

# committee's own walk found no stop at all within --max-descent's default 60 steps (still
# populated at the 57th); 65 more steps from any recorded floor at or below the 66th reaches the
# 1st Congress. committee-print's real floor sat six empty Congresses past its false two-empty
# stop (94th, past a run from the 100th to the 95th) and treaty's sat four past its (81st, past
# the 85th to the 82nd); eight tolerates both without costing every other route more than a few
# confirming requests (measured 2026-09-19).
FLOOR_DESCENT_STEPS = 65
FLOOR_EMPTY_TOLERANCE = 8

# --- floors, edge samples, drift ---------------------------------------------------------------


def measure_floors(reader: PagedJsonReader, measures: dict[str, Any], api_key: str) -> None:
    """Continue each route's descent below its recorded floor until a real run of empties, not just two.

    ``measure_congress`` stops on two consecutive empty Congresses, which measured routes have hit while
    older rows sat a wider gap below; so this walks ``FLOOR_DESCENT_STEPS`` further Congresses regardless,
    resets its empty run on every non-zero count and only stops after ``FLOOR_EMPTY_TOLERANCE`` in a row.
    A floor that was already real costs a few confirming requests, all landing empty.
    """
    for route in CONGRESS_ROUTES:
        facts = measures.get("congress", {}).get(route.route, {})
        earliest = facts.get("earliest")
        if not route.descent or earliest is None:
            continue
        below: dict[int, int | None] = {}
        new_earliest, empty_run, stop = earliest, 0, "cap"
        for step in range(FLOOR_DESCENT_STEPS):
            key = earliest - 1 - step
            if key < 1:
                stop = "floor"
                break
            try:
                count = _count(reader, _congress_url(route.descent.format(c=key)), route.records_key)
            except (PagedJsonSourceError, httpx.HTTPError):
                below[key] = None
                if sum(1 for v in below.values() if v is None) >= ERROR_TOLERANCE:
                    stop = "error"
                    break
                continue
            below[key] = count
            if count > 0:
                new_earliest, empty_run = key, 0
            else:
                empty_run += 1
                if empty_run >= FLOOR_EMPTY_TOLERANCE:
                    stop = "empty-run"
                    break
        facts["belowFloor"] = below
        # No separate "found data below the adopted floor" field: `new_earliest` is set to every
        # key visited with a non-zero count, in strictly decreasing order, so it is always the
        # deepest one already probed -- a stale `floorGap` field used to carry this warning under
        # the old fixed five-key probe, which could find data the walk had not adopted; this walk
        # adopts everything it finds, so that field would always serialize empty and was removed.
        # Drop it from a sidecar written by an older run of this tool, so nothing stale lingers.
        facts.pop("floorGap", None)
        if new_earliest != earliest:
            facts["earliest"], facts["descentStop"] = new_earliest, stop
        print(
            f"floor {route.route}: earliest {facts.get('earliest')} (was {earliest}), stop {stop}, below {below}",
            file=sys.stderr,
        )


# A6: `house-requirement/8070/matching-communications` reaches back to the 105th Congress (the
# map's histogram) but only carries detail records from some later floor; probed through the 119th.
REQUIREMENT_CONGRESSES = tuple(range(105, CURRENT_CONGRESS + 1))


def measure_requirements(reader: PagedJsonReader, api_key: str) -> dict[str, Any]:
    """Walk requirement 8070's full matching-communications list once, then probe the detail floor.

    The route is a count, not an index (A6), so the walk is not bounded to an era; it histograms every
    row by the ``congress`` field it states, then probes one detail record per Congress from the 105th
    through the 119th and records the first that resolves. The share at or above that floor is the
    number the A6 keep/drop decision (`docs/research/closing-the-gaps-2026-09-19.md`) turns on.
    """
    url = f"{CONGRESS_API}/house-requirement/8070/matching-communications?{urlencode({'format': 'json', 'limit': 250})}"
    rows = _walk(reader, url, "matchingCommunications", max_pages=380)
    histogram: Counter[int] = Counter()
    sample_by_congress: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        congress_num = row.get("congress")
        if congress_num is None:
            continue
        congress_num = int(congress_num)
        histogram[congress_num] += 1
        sample_by_congress.setdefault(congress_num, row)

    detail: dict[str, Any] = {}
    floor: int | None = None
    for congress_num in REQUIREMENT_CONGRESSES:
        sample = sample_by_congress.get(congress_num)
        if sample is None:
            detail[str(congress_num)] = {"sampled": False}
            continue
        code = str(sample.get("communicationType", {}).get("code", ""))
        number = sample.get("number")
        label = f"{congress_num}th {code.upper()} {number}"
        stated = _stated_congress_path(sample.get("url"))
        path = stated or f"house-communication/{congress_num}/{code.lower()}/{number}"
        locator = "publisher" if stated else "constructed"
        try:
            record = _cg(reader, path).get("houseCommunication", {})
        except (PagedJsonSourceError, ProbeError, httpx.HTTPError) as error:
            # A 404 here is expected, not exceptional: it is exactly how a Congress outside the
            # detail era answers (`ProbeUnavailableError`, a `ProbeError`), so it is recorded as
            # an unresolved sample, not raised.
            detail[str(congress_num)] = {
                "sampled": True,
                "resolved": False,
                "label": label,
                "locator": locator,
                "error": scrub_credential(str(error), api_key)[:80],
            }
            continue
        resolved = str(record.get("number")) == str(number)
        detail[str(congress_num)] = {"sampled": True, "resolved": resolved, "label": label, "locator": locator}
        if resolved and floor is None:
            floor = congress_num

    total = len(rows)
    covered = sum(n for c, n in histogram.items() if floor is not None and c >= floor)
    share = covered / total if total else 0.0
    print(
        f"requirements: {total} rows walked, detail floor {floor}, {covered}/{total} ({share:.1%}) at or above it",
        file=sys.stderr,
    )
    return {
        "total": total,
        "histogram": {str(c): n for c, n in sorted(histogram.items())},
        "detail": detail,
        "detailFloor": floor,
        "coveredByFloor": covered,
        "share": share,
    }


type Outcome = tuple[bool, str]
SENATE_DOCUMENT_TYPES = {
    "S.": "s", "H.R.": "hr", "S.J.Res.": "sjres", "H.J.Res.": "hjres", "S.Res.": "sres", "H.Res.": "hres",
    "S.Con.Res.": "sconres", "H.Con.Res.": "hconres",
}  # fmt: skip


def measure_edge_samples(
    congress: PagedJsonReader, govinfo: PagedJsonReader, probe: KeylessProbe, api_key: str, n: int
) -> dict[str, Any]:
    """Follow each edge from N items instead of one; the flow table then shows resolved-of-tried per edge."""
    out: dict[str, Any] = {}

    def tally(key: str, outcomes: list[Outcome], **extra: Any) -> None:
        out[key] = {
            "tried": len(outcomes),
            "resolved": sum(1 for ok, _ in outcomes if ok),
            "failures": [note for ok, note in outcomes if not ok][:3],
            **extra,
        }
        print(f"sample {key}: {out[key]['resolved']}/{out[key]['tried']}", file=sys.stderr)

    def attempt(fn: Callable[[], Outcome], label: str) -> Outcome:
        try:
            return fn()
        except (
            PagedJsonSourceError,
            ProbeError,
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as error:
            return False, f"{label}: {type(error).__name__} {scrub_credential(str(error), api_key)[:60]}"

    def summary_ok(package: str | None) -> bool:
        return bool(package) and _gi(govinfo, f"packages/{package}/summary").get("packageId") == package

    def rows_of(path: str, key: str) -> list[Mapping[str, Any]]:
        return list(_cg(congress, f"{path}?limit={n}").get(key, []))

    # Bills outward
    members: list[Outcome] = []
    committees: list[Outcome] = []
    laws: list[Outcome] = []
    reports: list[Outcome] = []
    votes: list[Outcome] = []
    clerks: list[Outcome] = []
    packages: list[Outcome] = []
    for row in rows_of(f"bill/{CURRENT_CONGRESS}", "bills"):
        ref = _bill_ref(row)
        bill = _cg(congress, ref).get("bill", {})
        number = str(bill.get("number"))
        bid = (bill.get("sponsors") or [{}])[0].get("bioguideId")
        if bid:
            members.append(
                attempt(
                    lambda ref=ref, bid=bid: (
                        _cg(congress, f"member/{bid}").get("member", {}).get("bioguideId") == bid,
                        f"{ref} sponsor {bid}",
                    ),
                    ref,
                )
            )
        crow = (_cg(congress, f"{ref}/committees").get("committees") or [{}])[0]
        code = crow.get("systemCode")
        if code:
            chamber = COMMITTEE_CHAMBER.get(str(crow.get("chamber", "")), "house")
            committees.append(
                attempt(
                    lambda ref=ref, code=code, chamber=chamber: (
                        _cg(congress, f"committee/{chamber}/{code}").get("committee", {}).get("systemCode") == code,
                        f"{ref} {code}",
                    ),
                    ref,
                )
            )
        law = str((bill.get("laws") or [{}])[0].get("number") or "")
        if "-" in law:
            lc, ln = law.split("-")
            laws.append(
                attempt(
                    lambda ref=ref, bill=bill, number=number, law=law, lc=lc, ln=ln: (
                        str(_cg(congress, f"law/{lc}/pub/{ln}").get("bill", {}).get("number")) == number,
                        f"{ref} law {law}",
                    ),
                    ref,
                )
            )
        citation = str((bill.get("committeeReports") or [{}])[0].get("citation") or "")
        cm = re.fullmatch(r"([HS])\. Rept\. (\d+)-(\d+)", citation)
        if cm:
            kind = "hrpt" if cm[1] == "H" else "srpt"
            reports.append(
                attempt(
                    lambda ref=ref, citation=citation, cm=cm, kind=kind: (
                        (_cg(congress, f"committee-report/{cm[2]}/{kind}/{cm[3]}").get("committeeReports") or [{}])[
                            0
                        ].get("citation")
                        == citation,
                        f"{ref} {citation}",
                    ),
                    ref,
                )
            )
        actions = _cg(congress, f"{ref}/actions?limit=250").get("actions", [])
        rv = next((v for a in actions for v in a.get("recordedVotes", []) if v.get("chamber") == "House"), None)
        if rv:
            votes.append(
                attempt(
                    lambda ref=ref, number=number, rv=rv: (
                        str(
                            _cg(congress, f"house-vote/{rv['congress']}/{rv['sessionNumber']}/{rv['rollNumber']}")
                            .get("houseRollCallVote", {})
                            .get("legislationNumber")
                        )
                        == number,
                        f"{ref} roll {rv['rollNumber']}",
                    ),
                    ref,
                )
            )
            expected = f"{str(bill.get('type', '')).lower()}{number}"
            clerks.append(
                attempt(
                    lambda ref=ref, rv=rv, expected=expected: (
                        (_texts(_xml(probe, rv["url"], "clerk"), {"legis-num"}) or [""])[0]
                        .replace(" ", "")
                        .replace(".", "")
                        .lower()
                        == expected,
                        f"{ref} {rv['url']}",
                    ),
                    ref,
                )
            )
        version = (_cg(congress, f"{ref}/text").get("textVersions") or [{}])[0]
        package = _package_id(str((version.get("formats") or [{}])[0].get("url") or ""))
        if package:
            packages.append(attempt(lambda ref=ref, package=package: (summary_ok(package), f"{ref} {package}"), ref))
    tally("bill→member", members)
    tally("bill→committee", committees)
    tally("bill→law", laws)
    tally("bill→report", reports)
    tally("bill→house-vote", votes)
    tally("bill→clerk-xml", clerks)
    tally("bill→text-package", packages)

    # Hearings, meetings
    h_packages: list[Outcome] = []
    h_meetings: list[Outcome] = []
    for row in rows_of(f"hearing/{CURRENT_CONGRESS}", "hearings"):
        path = f"hearing/{row.get('congress')}/{str(row.get('chamber', '')).lower()}/{row.get('jacketNumber')}"
        detail = _cg(congress, path).get("hearing", {})
        package = _package_id(str((detail.get("formats") or [{}])[0].get("url") or ""))
        h_packages.append(attempt(lambda package=package, path=path: (summary_ok(package), f"{path} {package}"), path))
        event = (detail.get("associatedMeeting") or {}).get("eventId")
        if event:
            chamber = str(detail.get("chamber", "house")).lower()
            h_meetings.append(
                attempt(
                    lambda chamber=chamber, path=path, event=event: (
                        str(
                            _cg(congress, f"committee-meeting/{CURRENT_CONGRESS}/{chamber}/{event}")
                            .get("committeeMeeting", {})
                            .get("eventId")
                        )
                        == str(event),
                        f"{path} event {event}",
                    ),
                    path,
                )
            )
    tally("hearing→package", h_packages)
    tally("hearing→meeting", h_meetings)
    m_bills: list[Outcome] = []
    for row in rows_of(f"committee-meeting/{CURRENT_CONGRESS}", "committeeMeetings"):
        path = f"committee-meeting/{row.get('congress')}/{str(row.get('chamber', '')).lower()}/{row.get('eventId')}"
        detail = _cg(congress, path).get("committeeMeeting", {})
        item = ((detail.get("relatedItems") or {}).get("bills") or [{}])[0]
        if item.get("number"):
            m_bills.append(
                attempt(
                    lambda bill=bill, number=number, path=path, item=item: (
                        str(_cg(congress, _bill_ref(item)).get("bill", {}).get("number")) == str(item.get("number")),
                        f"{path} {_bill_ref(item)}",
                    ),
                    path,
                )
            )
    tally("meeting→bill", m_bills)

    # Nominations
    n_committees: list[Outcome] = []
    n_hearings: list[Outcome] = []
    for row in rows_of(f"nomination/{CURRENT_CONGRESS}", "nominations"):
        number = row.get("number")
        crow = (_cg(congress, f"nomination/{CURRENT_CONGRESS}/{number}/committees").get("committees") or [{}])[0]
        code = crow.get("systemCode")
        if code:
            n_committees.append(
                attempt(
                    lambda number=number, code=code: (
                        _cg(congress, f"committee/senate/{code}").get("committee", {}).get("systemCode") == code,
                        f"PN{number} {code}",
                    ),
                    f"PN{number}",
                )
            )
        hrow = (_cg(congress, f"nomination/{CURRENT_CONGRESS}/{number}/hearings").get("hearings") or [{}])[0]
        if hrow.get("jacketNumber"):
            n_hearings.append(
                attempt(
                    lambda number=number, hrow=hrow: (
                        str(
                            _cg(congress, f"hearing/{CURRENT_CONGRESS}/senate/{hrow['jacketNumber']}")
                            .get("hearing", {})
                            .get("jacketNumber")
                        )
                        == str(hrow["jacketNumber"]),
                        f"PN{number} jacket {hrow['jacketNumber']}",
                    ),
                    f"PN{number}",
                )
            )
    tally("nomination→committee", n_committees)
    tally("nomination→hearing", n_hearings)

    # Reports, treaties, the Record, CRS
    r_bills: list[Outcome] = []
    r_packages: list[Outcome] = []
    for row in rows_of(f"committee-report/{CURRENT_CONGRESS}", "reports"):
        path = f"committee-report/{row.get('congress')}/{str(row.get('type', '')).lower()}/{row.get('number')}"
        detail = (_cg(congress, path).get("committeeReports") or [{}])[0]
        assoc = (detail.get("associatedBill") or [{}])[0]
        if assoc.get("number"):
            r_bills.append(
                attempt(
                    lambda bill=bill, number=number, path=path, assoc=assoc: (
                        str(_cg(congress, _bill_ref(assoc)).get("bill", {}).get("number")) == str(assoc.get("number")),
                        f"{path} {_bill_ref(assoc)}",
                    ),
                    path,
                )
            )
        text = (_cg(congress, f"{path}/text").get("text") or [{}])[0]
        package = _package_id(str((text.get("formats") or [{}])[0].get("url") or ""))
        r_packages.append(attempt(lambda package=package, path=path: (summary_ok(package), f"{path} {package}"), path))
    tally("report→bill", r_bills)
    tally("report→package", r_packages)
    treaties: list[Outcome] = []
    for row in rows_of(f"treaty/{CURRENT_CONGRESS}", "treaties"):
        package = f"CDOC-{row.get('congressReceived', CURRENT_CONGRESS)}tdoc{row.get('number')}"
        treaties.append(
            attempt(
                lambda number=number, package=package, row=row: (
                    summary_ok(package),
                    f"treaty {row.get('number')} {package}",
                ),
                package,
            )
        )
    tally("treaty→cdoc", treaties)
    issues: list[Outcome] = []
    for row in rows_of(f"daily-congressional-record/{COMPARE_VOLUME}", "dailyCongressionalRecord"):
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
        issues.append(
            attempt(
                lambda package=package, row=row: (summary_ok(package), f"issue {row.get('issueNumber')} {package}"),
                str(row.get("issueNumber")),
            )
        )
    tally("record→package", issues)
    crs: list[Outcome] = []
    for row in rows_of("crsreport", "CRSReports"):
        detail = _cg(congress, f"crsreport/{row.get('id')}").get("CRSReport", {})
        item = next((r for r in detail.get("relatedMaterials", []) if r.get("URL")), None)
        if item:
            url = str(item["URL"]).split("?")[0]
            crs.append(
                attempt(
                    lambda row=row, path=path, url=url: (
                        any(k not in ("request", "pagination") for k in _keyed_json(congress, f"{url}?format=json")),
                        f"{row.get('id')} {urlsplit(url).path}",
                    ),
                    str(row.get("id")),
                )
            )
    tally("crs→law-or-bill", crs)

    # House votes: the current session, bill and source file
    hv_bills: list[Outcome] = []
    hv_sources: list[Outcome] = []
    for row in rows_of(f"house-vote/{CURRENT_CONGRESS}/2", "houseRollCallVotes"):
        roll = row.get("rollCallNumber")
        detail = _cg(congress, f"house-vote/{CURRENT_CONGRESS}/2/{roll}").get("houseRollCallVote", {})
        kind, number = str(detail.get("legislationType", "")).lower(), str(detail.get("legislationNumber") or "")
        if kind and number:
            hv_bills.append(
                attempt(
                    lambda bill=bill, number=number, kind=kind, roll=roll: (
                        str(_cg(congress, f"bill/{CURRENT_CONGRESS}/{kind}/{number}").get("bill", {}).get("number"))
                        == number,
                        f"roll {roll} {kind} {number}",
                    ),
                    f"roll {roll}",
                )
            )
        source = str(detail.get("sourceDataURL") or "")
        if source:
            hv_sources.append(
                attempt(
                    lambda roll=roll, source=source: (
                        (_texts(_xml(probe, source, "clerk"), {"rollcall-num"}) or [""])[0].lstrip("0") == str(roll),
                        f"roll {roll} {source}",
                    ),
                    f"roll {roll}",
                )
            )
    tally("house-vote→bill", hv_bills)
    tally("house-vote→source-xml", hv_sources)

    # Senate votes spread across the session: the roster gap over time
    cvc_root = _xml(probe, SAMPLES["senate-cvc"][0], "cvc")
    crosswalk = {el.get("lis_member_id") for el in cvc_root.iter() if local_name(el.tag) == "senator"}
    legislators = json.loads(
        probe.get(SAMPLES["legislators-historical-json"][0], media_types=JSON_TYPES, max_bytes=SAMPLE_MAX_BYTES).body
    )
    by_lis = {str((r.get("id") or {}).get("lis")) for r in legislators if (r.get("id") or {}).get("lis")}
    by_vote: list[dict[str, Any]] = []
    documents: list[Outcome] = []
    voters = in_cvc = via_json = misses = 0
    for vote_number in range(1, 700, 35):
        url = f"https://www.senate.gov/legislative/LIS/roll_call_votes/vote{CURRENT_CONGRESS}1/vote_{CURRENT_CONGRESS}_1_{vote_number:05d}.xml"
        try:
            root = _xml(probe, url, "senate-vote")
        except ProbeError:
            misses += 1
            if misses >= 3:
                break
            continue
        lis_ids = _texts(root, {"lis_member_id"})
        absent = [x for x in lis_ids if x not in crosswalk]
        voters += len(lis_ids)
        in_cvc += len(lis_ids) - len(absent)
        via_json += sum(1 for x in absent if x in by_lis)
        stated = (_texts(root, {"vote_date"}) or [""])[0]
        date = (re.match(r"[A-Za-z]+ \d+, \d{4}", stated) or re.match(r".{0,20}", stated))[0]
        by_vote.append({"vote": vote_number, "date": date, "voters": len(lis_ids), "absentFromCvc": len(absent)})
        kind = (_texts(root, {"document_type"}) or [""])[0]
        number = (_texts(root, {"document_number"}) or [""])[0]
        amendment = re.sub(r"\D", "", (_texts(root, {"amendment_number"}) or [""])[0])
        code = SENATE_DOCUMENT_TYPES.get(kind)
        if kind.startswith("PN"):
            first = number.split("-")[0]
            label = f"vote {vote_number} PN {number}" + (" (en bloc range, first resolved)" if "-" in number else "")
            documents.append(
                attempt(
                    lambda first=first, label=label: (
                        str(_cg(congress, f"nomination/{CURRENT_CONGRESS}/{first}").get("nomination", {}).get("number"))
                        == first,
                        label,
                    ),
                    label,
                )
            )
        elif kind == "S.Amdt." and amendment:
            documents.append(
                attempt(
                    lambda amendment=amendment, vote_number=vote_number: (
                        str(
                            _cg(congress, f"amendment/{CURRENT_CONGRESS}/samdt/{amendment}")
                            .get("amendment", {})
                            .get("number")
                        )
                        == amendment,
                        f"vote {vote_number} S.Amdt. {amendment}",
                    ),
                    f"vote {vote_number}",
                )
            )
        elif code and number:
            documents.append(
                attempt(
                    lambda code=code, number=number, vote_number=vote_number, kind=kind: (
                        str(_cg(congress, f"bill/{CURRENT_CONGRESS}/{code}/{number}").get("bill", {}).get("number"))
                        == number,
                        f"vote {vote_number} {kind} {number}",
                    ),
                    f"vote {vote_number}",
                )
            )
        else:
            documents.append(
                (False, f"vote {vote_number}: document {kind!r} {number!r} is not a bill, amendment or nomination")
            )
    tally("senate-vote→document", documents)
    out["senate-vote→member"] = {
        "tried": voters, "resolved": in_cvc, "failures": [], "resolvedViaLegislatorsJson": via_json, "byVote": by_vote,
    }  # fmt: skip
    print(f"sample senate-vote→member: {in_cvc}/{voters} via cvc, {via_json} more via the JSON", file=sys.stderr)

    # Laws against the bulk folder
    law_rows = _cg(congress, f"law/{CURRENT_CONGRESS}?limit=250").get("bills", [])
    names = {str(f.get("name")) for f in _bulk_listing(probe, f"PLAW/{CURRENT_CONGRESS}/public")}
    plaw: list[Outcome] = []
    for row in law_rows:
        for law in row.get("laws", []):
            if "Public" in str(law.get("type")) and "-" in str(law.get("number")):
                lc, ln = str(law["number"]).split("-")
                plaw.append((f"PLAW-{lc}publ{int(ln)}.xml" in names, f"{law['number']} not in bulk yet"))
    tally("law→plaw-bulk", plaw)

    # Communications to committees
    c_committees: list[Outcome] = []
    seen_codes: dict[str, bool] = {}
    for row in rows_of(f"house-communication/{CURRENT_CONGRESS}", "houseCommunications"):
        detail = _keyed_json(congress, f"{str(row.get('url', '')).split('?')[0]}?format=json").get(
            "houseCommunication", {}
        )
        code = (detail.get("committees") or [{}])[0].get("systemCode")
        if not code:
            continue
        if code not in seen_codes:
            seen_codes[code] = _cg(congress, f"committee/house/{code}").get("committee", {}).get("systemCode") == code
        c_committees.append((seen_codes[code], f"EC {detail.get('number')} {code}"))
    tally("communication→committee", c_committees)
    return out
