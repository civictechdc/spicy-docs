"""Overlapping routes on one bounded scope: where the two publishers' inventories disagree.

Each pair compares identifier sets on a fixed Congress, volume or year, and the verdict strings
at the bottom state which side the repo takes and why.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

import httpx

from spicy_docs.reading.paged_json import PagedJsonReader, PagedJsonSourceError
from tools.analysis.legislative_data_map._render import _cell
from tools.analysis.legislative_data_map.capture import (
    COMPARE_CONGRESS,
    COMPARE_VOLUME,
    COMPARE_YEAR,
    NOMINATION_FEEDS,
    SAMPLE_MAX_BYTES,
    _bioguides,
    _congress_list,
    _error,
    _govinfo_published,
    _keyed_json,
    _result,
    _texts,
    _walk,
    _xml,
)
from tools.analysis.legislative_data_map.rows import CURRENT_CONGRESS, SAMPLES
from tools.analysis.shared import (
    CONGRESS_API,
    GOVINFO_BULK,
    JSON_TYPES,
    KeylessProbe,
    ProbeError,
    local_name,
)


def compare_house_vote(congress: PagedJsonReader, probe: KeylessProbe) -> dict[str, Any]:
    """One House roll call (session 1, roll 240) as the API's member votes against the Clerk XML, by position."""
    url = f"{CONGRESS_API}/house-vote/{CURRENT_CONGRESS}/1/240/members?{urlencode({'format': 'json', 'limit': 250})}"
    api: dict[str, str] = {}
    for _ in range(4):
        value = _keyed_json(congress, url)
        for member in value.get("houseRollCallVoteMemberVotes", {}).get("results", []):
            api[str(member.get("bioguideID"))] = str(member.get("voteCast"))
        url = value.get("pagination", {}).get("next") or ""
        if not url:
            break
    root = _xml(probe, SAMPLES["clerk-vote"][0], "clerk-vote")
    clerk: dict[str, str] = {}
    for recorded in root.iter():
        if local_name(recorded.tag) != "recorded-vote":
            continue
        legislator = next((c for c in recorded if local_name(c.tag) == "legislator"), None)
        vote = next((c for c in recorded if local_name(c.tag) == "vote"), None)
        if legislator is not None and vote is not None:
            clerk[str(legislator.get("name-id"))] = (vote.text or "").strip()
    clerk_totals = {
        local_name(e.tag): e.text
        for e in root.iter()
        if local_name(e.tag).endswith("-total") and "party" not in local_name(e.tag)
    }
    disagreements = sorted((k, api[k], clerk[k]) for k in api.keys() & clerk.keys() if api[k] != clerk[k])
    detail = f"vote disagreements {len(disagreements)}; API totals {dict(Counter(api.values()))}; Clerk totals {clerk_totals}"
    return _result(
        "Congress.gov house-vote members", "Clerk roll XML", f"roll 240, session 1, {CURRENT_CONGRESS}th",
        set(api), set(clerk), detail, disagreements=disagreements[:20],
    )  # fmt: skip


def compare_members(congress: PagedJsonReader, probe: KeylessProbe) -> dict[str, Any]:
    """Current members on the API against House members.xml/MemberData and the Senate cvc, by bioguide id."""
    rows = _congress_list(congress, f"member/congress/{CURRENT_CONGRESS}", "members", max_pages=4)
    api = {str(r.get("bioguideId")): r for r in rows}
    house_file = _bioguides(_xml(probe, SAMPLES["house-members-xml"][0], "house-members"))
    memberdata = _bioguides(_xml(probe, SAMPLES["house-memberdata"][0], "house-memberdata"))
    senate = _bioguides(_xml(probe, SAMPLES["senate-cvc"][0], "senate-cvc"))
    publisher = house_file | memberdata | senate
    former = []
    for bioguide in sorted(api.keys() - publisher):
        terms = api[bioguide].get("terms", {}).get("item", [])
        ended = any(t.get("endYear") for t in terms)
        former.append(
            {
                "bioguideId": bioguide,
                "name": api[bioguide].get("name"),
                "state": api[bioguide].get("state"),
                "ended": ended,
            }
        )
    detail = (
        f"House members.xml {len(house_file)}, House MemberData {len(memberdata)} (symmetric difference {len(house_file ^ memberdata)}), "
        f"Senate cvc {len(senate)}; of the API-only members {sum(1 for f in former if f['ended'])} of {len(former)} have an ended term"
    )
    return _result(
        "Congress.gov member/congress",
        "House members.xml + MemberData + Senate cvc XML",
        f"{CURRENT_CONGRESS}th Congress",
        set(api),
        publisher,
        detail,
        apiOnlyMembers=former[:40],
    )


def compare_daily_record(congress: PagedJsonReader, govinfo: PagedJsonReader) -> dict[str, Any]:
    """One Record volume's issue dates on the API against GovInfo CREC packages, excluding the prior volume's."""
    rows = _congress_list(
        congress, f"daily-congressional-record/{COMPARE_VOLUME}", "dailyCongressionalRecord", max_pages=2
    )
    api_all = {str(r.get("issueDate", ""))[:10] for r in rows}
    api = {d for d in api_all if d.startswith(str(COMPARE_YEAR))}
    packages = _govinfo_published(govinfo, "CREC", f"{COMPARE_YEAR}-01-01", f"{COMPARE_YEAR}-12-31", max_pages=2)
    prior_volume = [
        str(p.get("packageId")) for p in packages if str(p.get("packageId")).endswith(f"-v{COMPARE_VOLUME - 1}")
    ]
    gi = {str(p.get("dateIssued", ""))[:10] for p in packages if str(p.get("packageId")) not in prior_volume}
    odd = sorted(
        str(p.get("packageId"))
        for p in packages
        if not re.fullmatch(r"CREC-\d{4}-\d{2}-\d{2}", str(p.get("packageId")))
    )
    detail = (
        f"API issues {len(rows)} for volume {COMPARE_VOLUME}, {len(api_all - api)} dated outside {COMPARE_YEAR}; "
        f"GovInfo packages {len(packages)} issued in {COMPARE_YEAR}, {len(prior_volume)} belonging to volume {COMPARE_VOLUME - 1}; "
        f"package ids that are not one plain date {odd[:6]}"
    )
    return _result(
        "Congress.gov daily-congressional-record",
        "GovInfo CREC",
        f"volume {COMPARE_VOLUME} within {COMPARE_YEAR}",
        api,
        gi,
        detail,
    )


def compare_committee_reports(congress: PagedJsonReader, govinfo: PagedJsonReader) -> dict[str, Any]:
    """One Congress's committee reports: API type+number against GovInfo CRPT package ids, parts collapsed."""
    rows = _congress_list(congress, f"committee-report/{COMPARE_CONGRESS}", "reports", max_pages=12)
    api = {f"{str(r.get('type')).lower()}{r.get('number')}" for r in rows}
    packages = _govinfo_published(
        govinfo, "CRPT", f"{COMPARE_CONGRESS * 2 + 1787}-01-01", f"{COMPARE_YEAR}-12-31", max_pages=6
    )
    gi: set[str] = set()
    for package in packages:
        match = re.fullmatch(r"CRPT-(\d+)([a-z]+)(\d+)", str(package.get("packageId")))
        if match and int(match[1]) == COMPARE_CONGRESS:
            gi.add(f"{match[2]}{int(match[3])}")
    detail = (
        f"API rows {len(rows)} (parts collapse into {len(api)} reports); GovInfo packages in window {len(packages)}"
    )
    return _result("Congress.gov committee-report", "GovInfo CRPT", f"{COMPARE_CONGRESS}th Congress", api, gi, detail)


def compare_hearings(congress: PagedJsonReader, govinfo: PagedJsonReader) -> dict[str, Any]:
    """One Congress's hearings keyed by jacket number: API rows against GovInfo CHRG packages."""
    rows = _congress_list(congress, f"hearing/{COMPARE_CONGRESS}", "hearings", max_pages=20)
    api = {str(r.get("jacketNumber")).lstrip("0") for r in rows if r.get("jacketNumber")}
    packages = _govinfo_published(
        govinfo, "CHRG", f"{COMPARE_CONGRESS * 2 + 1787}-01-01", f"{COMPARE_YEAR}-12-31", max_pages=8
    )
    gi: set[str] = set()
    for package in packages:
        match = re.fullmatch(r"CHRG-(\d+)([a-z]+?)(\d+)", str(package.get("packageId")))
        if match and int(match[1]) == COMPARE_CONGRESS:
            gi.add(match[3].lstrip("0"))
    detail = f"API rows {len(rows)}; GovInfo packages in window {len(packages)}; keyed by jacket number"
    return _result("Congress.gov hearing", "GovInfo CHRG", f"{COMPARE_CONGRESS}th Congress", api, gi, detail)


def compare_nominations(congress: PagedJsonReader, probe: KeylessProbe) -> dict[str, Any]:
    """Current-Congress nominations: the API list against the union of nine Senate LIS feeds, plus feed-only detail lookups."""
    rows = _congress_list(congress, f"nomination/{CURRENT_CONGRESS}", "nominations", max_pages=12)
    api = {str(r.get("citation") or f"PN{r.get('number')}").split("-")[0] for r in rows}
    feeds: dict[str, Any] = {}
    union: set[str] = set()
    for category in NOMINATION_FEEDS:
        root = _xml(probe, f"https://www.senate.gov/legislative/LIS/nominations/Nom{category}.xml", category)
        numbers = {m for el in root.iter() if el.text for m in re.findall(r"PN\d+", el.text)}
        feeds[category] = {"congress": (_texts(root, {"Congress"}) or [None])[0], "count": len(numbers)}
        union |= numbers
    on_detail: dict[str, Any] = {}
    for citation in sorted(union - api)[:5]:
        try:
            value = _keyed_json(congress, f"{CONGRESS_API}/nomination/{CURRENT_CONGRESS}/{citation[2:]}?format=json")
            nomination = value.get("nomination", {})
            on_detail[citation] = {k: nomination.get(k) for k in ("receivedDate", "updateDate")}
        except (PagedJsonSourceError, ProbeError, httpx.HTTPError) as error:
            on_detail[citation] = _error(error)
    detail = (
        f"API rows {len(rows)} collapse to {len(api)} nominations; feed counts sum to {sum(v['count'] for v in feeds.values())} "
        f"over a union of {len(union)}; feed-only nominations on the API detail route: {on_detail}"
    )
    return _result(
        "Congress.gov nomination",
        "Senate LIS nomination feeds (union of 9)",
        f"{CURRENT_CONGRESS}th Congress",
        api,
        union,
        detail,
        feeds=feeds,
        feedOnlyOnDetail=on_detail,
    )


def compare_laws(congress: PagedJsonReader, probe: KeylessProbe) -> dict[str, Any]:
    """Public and private law numbers: the API's law route against the PLAW bulkdata folders."""
    rows = _congress_list(congress, f"law/{CURRENT_CONGRESS}", "bills", max_pages=4)
    api = {
        f"{'private' if 'rivate' in str(law.get('type')) else 'public'} {law.get('number')}"
        for r in rows
        for law in r.get("laws", [])
    }
    bulk: set[str] = set()
    folders: dict[str, int] = {}
    listing = json.loads(
        probe.get(
            f"{GOVINFO_BULK}/PLAW/{CURRENT_CONGRESS}",
            media_types=JSON_TYPES,
            max_bytes=4 * 1024 * 1024,
            accept="application/json",
        ).body
    )
    for folder in [f["name"] for f in listing.get("files", []) if f.get("folder")]:
        files = json.loads(
            probe.get(
                f"{GOVINFO_BULK}/PLAW/{CURRENT_CONGRESS}/{folder}",
                media_types=JSON_TYPES,
                max_bytes=4 * 1024 * 1024,
                accept="application/json",
            ).body
        )
        names = [str(f.get("name")) for f in files.get("files", []) if not f.get("folder")]
        folders[str(folder)] = len(names)
        for name in names:
            match = re.fullmatch(r"PLAW-(\d+)(publ|pvtl)(\d+)\.xml", name)
            if match:
                bulk.add(f"{'public' if match[2] == 'publ' else 'private'} {match[1]}-{int(match[3])}")
    detail = f"API bills with a law number {len(rows)}; bulk folders and file counts {folders} (each folder also holds one zip)"
    return _result("Congress.gov law", "GovInfo PLAW bulkdata", f"{CURRENT_CONGRESS}th Congress", api, bulk, detail)


def compare_bulk_status(congress: PagedJsonReader, probe: KeylessProbe) -> dict[str, Any]:
    """One Congress and one bill type: the bulk status zip against the bill list, on identity, update date and latest action."""
    from spicy_docs.reading.zip_archive import archive_members, open_archive, read_member
    from spicy_docs.sources.congress.bill_status import BillIdentity, BillSourceError, parse_bill_status

    kind = "hres"
    url = f"https://www.govinfo.gov/bulkdata/BILLSTATUS/{CURRENT_CONGRESS}/{kind}/BILLSTATUS-{CURRENT_CONGRESS}-{kind}.zip"
    capture = probe.get(
        url,
        media_types=("application/zip", "application/octet-stream", "application/x-zip-compressed"),
        max_bytes=SAMPLE_MAX_BYTES,
    )
    label = "BILLSTATUS zip"
    archive = open_archive(
        capture.body, max_bytes=SAMPLE_MAX_BYTES, max_entries=5000, max_entry_bytes=4 * 1024 * 1024,
        max_total_bytes=256 * 1024 * 1024, error_type=ProbeError, label=label,
    )  # fmt: skip
    bulk: dict[str, dict[str, Any]] = {}
    refused = 0
    reasons: Counter[str] = Counter()
    for info in archive_members(archive, max_entries=5000, error_type=ProbeError, label=label):
        match = re.fullmatch(rf"BILLSTATUS-{CURRENT_CONGRESS}{kind}(\d+)\.xml", info.filename.rsplit("/", 1)[-1])
        if not match:
            continue
        data = read_member(archive, info, max_bytes=4 * 1024 * 1024, error_type=ProbeError, label=label)
        try:
            status = parse_bill_status(data, identity=BillIdentity(CURRENT_CONGRESS, kind, int(match[1])))
        except BillSourceError as error:
            refused += 1
            reasons[str(error)] += 1
            continue
        action = status.latest_action
        bulk[match[1]] = {
            "update": status.update_date,
            "actionDate": action.action_date if action else None,
            "actionText": (action.text if action else "") or "",
        }
    rows = _walk(
        congress,
        f"{CONGRESS_API}/bill/{CURRENT_CONGRESS}/{kind}?{urlencode({'format': 'json', 'limit': 250})}",
        "bills",
        12,
    )
    api = {
        str(r.get("number")): {
            "update": r.get("updateDate"),
            "actionDate": (r.get("latestAction") or {}).get("actionDate"),
            "actionText": (r.get("latestAction") or {}).get("text") or "",
        }
        for r in rows
    }
    shared = sorted(api.keys() & bulk.keys(), key=int)

    def day(value: Any) -> str:
        return str(value or "")[:10]

    same_update = sum(1 for n in shared if day(api[n]["update"]) == day(bulk[n]["update"]))
    api_newer = sum(1 for n in shared if day(api[n]["update"]) > day(bulk[n]["update"]))
    bulk_newer = sum(1 for n in shared if day(api[n]["update"]) < day(bulk[n]["update"]))
    same_action = sum(
        1
        for n in shared
        if api[n]["actionDate"] == bulk[n]["actionDate"]
        and api[n]["actionText"].strip() == bulk[n]["actionText"].strip()
    )
    differing = [
        n
        for n in shared
        if not (
            api[n]["actionDate"] == bulk[n]["actionDate"]
            and api[n]["actionText"].strip() == bulk[n]["actionText"].strip()
        )
    ][:5]
    detail = (
        f"zip {capture.byte_size:,} B, {len(bulk)} statuses parsed by parse_bill_status, {refused} refused "
        f"({'; '.join(f'{v} × {k}' for k, v in reasons.most_common(3))}); of {len(shared)} shared bills the "
        f"update day is equal on {same_update}, the API is newer on {api_newer}, bulk is newer on {bulk_newer}; latest action equal on "
        f"{same_action}, differing {differing}"
    )
    return _result(
        "Congress.gov bill list", "GovInfo BILLSTATUS bulk zip", f"{CURRENT_CONGRESS}th H.Res.", set(api), set(bulk), detail,
        zipBytes=capture.byte_size, parsed=len(bulk), refused=refused, sameUpdateDay=same_update, apiNewer=api_newer,
        bulkNewer=bulk_newer, sameLatestAction=same_action, differingLatestAction=differing, refusalReasons=dict(reasons),
    )  # fmt: skip


def measure_comparisons(
    congress: PagedJsonReader, govinfo: PagedJsonReader, probe: KeylessProbe, api_key: str
) -> dict[str, Any]:
    """Run every comparison pair, recording a refused pair as an error under its key rather than aborting."""
    out: dict[str, Any] = {}
    pairs = {
        "house-vote": lambda: compare_house_vote(congress, probe),
        "members": lambda: compare_members(congress, probe),
        "daily-record": lambda: compare_daily_record(congress, govinfo),
        "committee-reports": lambda: compare_committee_reports(congress, govinfo),
        "hearings": lambda: compare_hearings(congress, govinfo),
        "nominations": lambda: compare_nominations(congress, probe),
        "laws": lambda: compare_laws(congress, probe),
        "bulk-status": lambda: compare_bulk_status(congress, probe),
    }
    for key, run in pairs.items():
        try:
            out[key] = run()
        except (PagedJsonSourceError, ProbeError, httpx.HTTPError, ValueError) as error:
            out[key] = _error(error, api_key)
        print(f"compare {key}: {json.dumps(out[key])[:160]}", file=sys.stderr)
    return out


VERDICTS: dict[str, str] = {
    "house-vote": "API for the index from the 115th Congress; Clerk XML for history and as the stated source file",
    "members": "API is the roster of record; the chamber files only for committee assignments and the LIS crosswalk",
    "daily-record": "API for the index (volume, issue); GovInfo for bodies; never key the Record on a date",
    "committee-reports": "API index, GovInfo bodies; identical, so either checks the other",
    "hearings": "GovInfo package id is the key; API is the index; treat short API jacket numbers as invalid",
    "nominations": "API for acquisition and history; feeds as a keyless status cross-check, current Congress only",
    "laws": "API for links and freshness, bulk for USLM bodies; carry the bulk lag in the schedule",
    "bulk-status": "Bulk first: every parsable file matches the API on identity and action; the parser's one-text-element rule is the gap",
}
WHY: dict[str, str] = {
    "house-vote": (
        "Every member, every position and the totals agree. The API is tier-1 and indexes votes with bill links but "
        "reaches only the 115th Congress; the Clerk XML is keyless, one document per vote, reaches 1990, and the API "
        "names it as its source."
    ),
    "members": (
        "The API lists everyone who served in the Congress; the chamber files list only the seats filled today, "
        "which is why the API-only members all have ended terms. The files add committee assignments and the "
        "Senate LIS id, and the LIS id is what joins Senate votes to members."
    ),
    "daily-record": (
        "Issue for issue the same once scoped alike; the leftovers are a volume running past the calendar year and "
        "days with two issues. The API's identity is volume and issue, GovInfo's is date and part."
    ),
    "committee-reports": (
        "Identical sets for the 118th Congress. The API is the cheaper index and carries typed fields and text "
        "links; GovInfo holds the bodies and reaches 1817."
    ),
    "hearings": (
        "Near-identical, but the API carries jacket numbers that cannot be real (1, 2, 3, an eight-digit value) "
        "and GovInfo holds a few jackets the API lacks."
    ),
    "nominations": (
        "Equal for the current Congress except one nomination the feeds list and the API list omits while the API "
        "detail route serves it, so the list lags its own detail. The feeds partition by status and overlap: their "
        "counts sum past the union, so a nomination can sit in two feeds."
    ),
    "laws": (
        "Agree on every law both hold. The API runs ahead by the newest laws and bulk lags by several numbers, so "
        "neither is complete at any instant; the lag is the number an acquisition schedule has to carry."
    ),
    "bulk-status": (
        "One Congress and one bill type, the status zip against the bill list. Every file the parser accepts is in "
        "the API and agrees on the latest action except the handful the API updated after the zip was built; the "
        "API is newer on about a tenth of the bills by day and bulk is never newer, which is the delta an API pass "
        "must carry. The files the zip holds and the comparison could not use were refused by this repo's parser "
        "for one reason, its rule that a bill carries exactly one text element; that is port decision 4, measured."
    ),
}


def _summary(c: Mapping[str, Any]) -> str:
    """One comparison's result column, keyed to the extra fields its pair recorded."""
    if "disagreements" in c:
        return f"{len(c['disagreements'])} position disagreements; totals {'equal' if c['onlyACount'] == c['onlyBCount'] == 0 else 'differ'}"
    if "apiOnlyMembers" in c:
        ended = sum(1 for m in c["apiOnlyMembers"] if m.get("ended"))
        return f"API-only {c['onlyACount']}, {ended} with ended terms"
    if "feedOnlyOnDetail" in c:
        return f"feed-only {c['onlyBCount']}, {len(c['feedOnlyOnDetail'])} served by the API detail route"
    if "refusalReasons" in c:
        return f"{c.get('parsed', 0):,} parsed, {c.get('refused', 0)} refused by the parser; API newer on {c.get('apiNewer', 0)}, bulk never"
    return f"only A {c['onlyACount']}, only B {c['onlyBCount']}"


def render_comparisons(measures: Mapping[str, Any]) -> list[str]:
    """The comparisons table plus its per-verdict reasoning; empty when no comparison pass has run."""
    comparisons = measures.get("comparisons")
    if not comparisons:
        return []
    compared = str(measures.get("comparedAt", ""))[:10]
    lines = [
        "### Comparisons: overlapping routes on one bounded scope",
        "",
        (
            f"Measured {compared} in {sum(measures.get('compareRequests', {}).values())} requests; the differing "
            "identifiers and the per-pair detail are in the JSON."
        ),
        "",
        "| Pair | Scope | A | B | Both | Only A | Only B | Result | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, c in comparisons.items():
        if "error" in c:
            lines.append(f"| {key} | | | | | | | error: {_cell(c.get('message', ''))[:80]} | |")
            continue
        cells = (
            f"{c['a']} vs {c['b']}", c["scope"], f"{c['aCount']:,}", f"{c['bCount']:,}", f"{c['both']:,}",
            f"{c['onlyACount']:,}", f"{c['onlyBCount']:,}", _summary(c), VERDICTS.get(key, ""),
        )  # fmt: skip
        lines.append("| " + " | ".join(_cell(v) for v in cells) + " |")
    lines.append("")
    lines.append("Why each verdict:")
    lines.append("")
    for key, c in comparisons.items():
        if key in WHY and "error" not in c:
            lines.append(f"- **{c['a']} vs {c['b']}.** {WHY[key]}")
    lines.append("")
    return lines
