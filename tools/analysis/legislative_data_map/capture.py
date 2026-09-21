"""Measure the map's inputs: Congress.gov counts and freshness, GovInfo coverage, the CDTF catalog and publisher samples.

Coverage floors are lower bounds from a bounded descent; publisher errors are never read as emptiness.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from spicy_docs.reading.paged_json import PagedJsonReader, PagedJsonSourceError
from spicy_docs.reading.xml import parse_xml
from spicy_docs.sources.congress.listing import CongressListingReader
from spicy_docs.sources.govinfo.discovery import GovInfoDiscoveryReader, published_url
from spicy_docs.transport.capture import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError, scrub_credential
from tools.analysis.legislative_data_map.rows import (
    CONGRESS_ROUTES,
    CURRENT_CONGRESS,
    GOVINFO_COVERAGE,
    SAMPLES,
    XML_TYPES,
    CongressRoute,
)
from tools.analysis.shared import (
    CONGRESS_API,
    GOVINFO_BULK,
    JSON_TYPES,
    REQUESTS,
    KeylessProbe,
    ProbeError,
    ProbeUnavailableError,
    local_name,
)

GOVINFO_API = "https://api.govinfo.gov"
CDTF_CATALOG = "https://usgpo.github.io/innovation/data.json"
CURRENT_RECORD_VOLUME = 172
CURRENT_YEAR = 2026
FIRST_YEAR = 1789
ERROR_TOLERANCE = 6
LEADING_EMPTY_TOLERANCE = 6
SAMPLE_MAX_BYTES = 16 * 1024 * 1024
BULK_SIZED = ("BILLSTATUS", "BILLS", "BILLSUM", "PLAW")
IDENTITY_NAMES = re.compile(r"congress|session|number|rollcall|jacket|vote_num", re.IGNORECASE)
DATED_NAMES = re.compile(r"date|update|modif|publish", re.IGNORECASE)


def _capture_facts(capture: CapturedBodyResponse) -> dict[str, Any]:
    """The identity facts of one captured response: resolved URL, status, media type, size, digest, time."""
    return {
        "resolvedUrl": capture.resolved_url,
        "statusCode": capture.status_code,
        "contentType": capture.content_type,
        "byteSize": capture.byte_size,
        "sha256": capture.sha256,
        "observedAt": capture.observed_at,
    }


def _error(error: Exception, api_key: str = "") -> dict[str, Any]:
    """A JSON-safe error record with the message scrubbed of credentials before truncation."""
    facts: dict[str, Any] = {"error": type(error).__name__, "message": scrub_credential(str(error), api_key)[:300]}
    capture = getattr(error, "capture", None)
    if isinstance(capture, CapturedBodyResponse):
        facts["statusCode"] = capture.status_code
        facts["contentType"] = capture.content_type
    return facts


# --- Congress.gov ---------------------------------------------------------------


def _congress_url(path: str) -> str:
    """A Congress.gov JSON list URL bounded to ``limit=1``."""
    return f"{CONGRESS_API}/{path}?{urlencode({'format': 'json', 'limit': 1})}"


def _count(reader: PagedJsonReader, url: str, records_key: str) -> int:
    """One route's declared total, falling back to the records actually returned when it declares none."""
    REQUESTS[reader.family.name] += 1
    page = reader.page(url, records_key=records_key)
    return page.declared_count if page.declared_count is not None else len(page.records)


def measure_latest(reader: PagedJsonReader, route: CongressRoute, api_key: str) -> dict[str, Any]:
    """Newest update date on the route's most specific list, the current Congress where it has one.

    The API honors ``sort=updateDate`` on some routes only. Asking both directions and comparing the first
    record says which; where the sort is ignored, the first record's date is a floor on the newest update,
    never the newest itself.
    """
    candidates = [route.descent.format(c=route.start)] if route.descent else []
    candidates.append(route.route)
    out: dict[str, Any] = {}
    for path in dict.fromkeys(candidates):
        try:
            dates = []
            for order in ("desc", "asc"):
                REQUESTS[reader.family.name] += 1
                url = _congress_url(path) + "&" + urlencode({"sort": f"updateDate {order}"})
                page = reader.page(url, records_key=route.records_key)
                dates.append(page.records[0].get("updateDate") if page.records else None)
        except (PagedJsonSourceError, httpx.HTTPError) as error:
            out["latestUpdateError"] = _error(error, api_key)
            continue
        if dates[0]:
            out.pop("latestUpdateError", None)
            out.update({"latestUpdate": dates[0], "latestSortHonored": dates[0] != dates[1], "latestPath": path})
            break
    return out


def measure_congress(reader: CongressListingReader, *, max_descent: int, api_key: str) -> dict[str, Any]:
    """Per-route declared totals, newest update dates, and a bounded descent to each coverage floor."""
    out: dict[str, Any] = {}
    for route in CONGRESS_ROUTES:
        facts: dict[str, Any] = {"recordsKey": route.records_key}
        try:
            facts["total"] = _count(reader, _congress_url(route.route), route.records_key)
        except (PagedJsonSourceError, httpx.HTTPError) as error:
            facts["totalError"] = _error(error, api_key)
        facts.update(measure_latest(reader, route, api_key))
        if route.descent is None:
            out[route.route] = facts
            continue
        counts: dict[int, int] = {}
        errors: dict[int, dict[str, Any]] = {}
        earliest: int | None = None
        empty_after = leading_empty = 0
        stop = "cap"
        for step in range(max_descent):
            key = route.start - step
            if key < 1:
                stop = "floor"
                break
            try:
                count = _count(reader, _congress_url(route.descent.format(c=key)), route.records_key)
            except (PagedJsonSourceError, httpx.HTTPError) as error:
                # A publisher error is not an observation of emptiness; a few are tolerated, then the walk stops.
                errors[key] = _error(error, api_key)
                if len(errors) >= ERROR_TOLERANCE:
                    stop = "error"
                    break
                continue
            counts[key] = count
            if count > 0:
                earliest, empty_after = key, 0
            elif earliest is None:
                leading_empty += 1
                if leading_empty >= LEADING_EMPTY_TOLERANCE:
                    stop = "never-populated"
                    break
            else:
                empty_after += 1
                if empty_after >= 2:
                    stop = "two-empty"
                    break
        facts.update(
            {"descentPath": route.descent, "earliest": earliest, "descentStop": stop, "byKey": counts, "errors": errors}
        )
        out[route.route] = facts
        print(f"congress {route.route}: total={facts.get('total')} earliest={earliest} stop={stop}", file=sys.stderr)
    return out


def _published_count(reader: GovInfoDiscoveryReader, code: str, year: int) -> int:
    """How many packages one collection declares published on or after ``{year}-01-01``."""
    return _count(reader, published_url(f"{year}-01-01", collections=[code], page_size=1), "packages")


def _bulk_listing(probe: KeylessProbe, path: str) -> list[Mapping[str, Any]]:
    """The ``files`` array of one keyless GovInfo bulkdata JSON listing."""
    capture = probe.get(
        f"{GOVINFO_BULK}/{path}", media_types=JSON_TYPES, max_bytes=8 * 1024 * 1024, accept="application/json"
    )
    return json.loads(capture.body).get("files", [])


def _sized_folder(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    """ZIP and loose-file byte totals plus a file count for one bulkdata folder listing."""
    zips = [f for f in entries if str(f.get("name", "")).endswith(".zip")]
    files = [f for f in entries if not f.get("folder") and f not in zips]
    return {
        "zipBytes": sum(int(f.get("size") or 0) for f in zips),
        "zipModified": (str(zips[0].get("formattedLastModifiedTime")) if zips else None),
        "fileBytes": sum(int(f.get("size") or 0) for f in files),
        "files": len(files),
    }


def measure_govinfo(reader: GovInfoDiscoveryReader, probe: KeylessProbe, *, api_key: str) -> dict[str, Any]:
    """Package counts from the collections inventory, per-collection earliest issue year, and bulkdata ranges."""
    out: dict[str, Any] = {"collections": {}, "coverage": {}, "bulkdata": {}}
    REQUESTS[reader.family.name] += 1
    page = reader.page(f"{GOVINFO_API}/collections", records_key="collections")
    for record in page.records:
        code = str(record.get("collectionCode", ""))
        out["collections"][code] = {
            "name": record.get("collectionName"),
            "packageCount": record.get("packageCount"),
            "granuleCount": record.get("granuleCount"),
        }
    for code in GOVINFO_COVERAGE:
        if code not in out["collections"]:
            out["coverage"][code] = {"error": "not in the collections inventory"}
            continue
        try:
            total = _published_count(reader, code, FIRST_YEAR)
            low, high = FIRST_YEAR, CURRENT_YEAR
            if total == 0:
                out["coverage"][code] = {"total": 0, "earliestYear": None}
                continue
            while low < high:
                mid = (low + high + 1) // 2
                if _published_count(reader, code, mid) == total:
                    low = mid
                else:
                    high = mid - 1
            out["coverage"][code] = {"total": total, "earliestYear": low}
        except (PagedJsonSourceError, httpx.HTTPError) as error:
            out["coverage"][code] = _error(error, api_key)
        print(f"govinfo {code}: {out['coverage'][code]}", file=sys.stderr)
    for code in sorted(out["collections"]):
        try:
            files = _bulk_listing(probe, code)
        except ProbeError:
            continue
        folders = [str(f.get("name")) for f in files if f.get("folder")]
        numeric = sorted(int(n) for n in folders if n.isdigit())
        out["bulkdata"][code] = {
            "folders": len(folders),
            "numericRange": [numeric[0], numeric[-1]] if numeric else None,
            "topLevelFiles": sum(1 for f in files if not f.get("folder")),
            "topLevelBytes": sum(int(f.get("size") or 0) for f in files if not f.get("folder")),
            "newestFolder": (str(files[0].get("formattedLastModifiedTime")) if files else None),
        }
    for code in BULK_SIZED:
        if code not in out["bulkdata"]:
            continue
        try:
            subfolders = [
                str(f.get("name")) for f in _bulk_listing(probe, f"{code}/{CURRENT_CONGRESS}") if f.get("folder")
            ]
        except ProbeError as error:
            out["bulkdata"][code]["currentCongress"] = _error(error)
            continue
        types: dict[str, Any] = {}
        for folder in subfolders:
            try:
                types[folder] = _sized_folder(_bulk_listing(probe, f"{code}/{CURRENT_CONGRESS}/{folder}"))
            except ProbeError as error:
                types[folder] = _error(error)
        sized = [t for t in types.values() if "zipBytes" in t]
        out["bulkdata"][code]["currentCongress"] = {
            "congress": CURRENT_CONGRESS,
            "types": types,
            "zipBytes": sum(t["zipBytes"] for t in sized),
            "fileBytes": sum(t["fileBytes"] for t in sized),
            "files": sum(t["files"] for t in sized),
        }
        print(
            f"bulk {code}/{CURRENT_CONGRESS}: {out['bulkdata'][code]['currentCongress']['zipBytes']} zip bytes",
            file=sys.stderr,
        )
    return out


def measure_catalog(probe: KeylessProbe) -> dict[str, Any]:
    """The CDTF catalog's entry count, periodicity/format caveats and per-identifier titles."""
    capture = probe.get(CDTF_CATALOG, media_types=JSON_TYPES, max_bytes=8 * 1024 * 1024)
    datasets = json.loads(capture.body)["dataset"]

    def landing(entry: Mapping) -> str:
        page = entry.get("landingPage")
        return str(page.get("accessURL", "")) if isinstance(page, dict) else str(page or "")

    roots = deep = missing = 0
    for entry in datasets:
        for dist in entry.get("distribution", []):
            url = dist.get("accessURL")
            if not url:
                missing += 1
            elif urlsplit(url).path.strip("/"):
                deep += 1
            else:
                roots += 1
    landings = Counter(landing(e) for e in datasets if landing(e))
    entries = {
        e["identifier"].removeprefix("CDTF-DATASET-"): {
            "title": e.get("title"),
            "accrualPeriodicity": e.get("accrualPeriodicity"),
            "landingPage": landing(e),
        }
        for e in datasets
    }
    return {
        **_capture_facts(capture),
        "entries": len(datasets),
        "withAccrualPeriodicity": sum(1 for e in datasets if e.get("accrualPeriodicity")),
        "withFormatOrTemporal": sum(
            1
            for e in datasets
            if e.get("temporal") or any(d.get("format") or d.get("mediaType") for d in e.get("distribution", []))
        ),
        "distributionAccessUrl": {"homepageRoot": roots, "deep": deep, "missing": missing},
        "duplicateLandingPages": {url: n for url, n in landings.items() if n > 1},
        "byId": entries,
    }


def _identity_order(names: list[str]) -> list[str]:
    """Congress, then session, then the item number, then anything else: the order a reader keys on."""

    def rank(name: str) -> tuple[int, str]:
        lowered = name.lower()
        if "congress" in lowered:
            return (0, lowered)
        if "session" in lowered:
            return (1, lowered)
        if any(k in lowered for k in ("rollcall", "vote_num", "jacket", "displaynumber")) or lowered == "number":
            return (2, lowered)
        return (3, lowered)

    return sorted(names, key=rank)


def _xml_shape(body: bytes, key: str) -> dict[str, Any]:
    """Root, namespace, first- and second-level children and identity-looking names of one XML sample."""
    root = parse_xml(
        body, max_bytes=len(body), error_type=ProbeError, label=key, allow_external_doctype=True, max_depth=64
    )

    children = Counter(local_name(child.tag) for child in root)
    grandchildren = Counter(local_name(g.tag) for child in root for g in child)
    names = set(children) | set(grandchildren) | set(root.attrib) | {a for child in root for a in child.attrib}
    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else None
    return {
        "root": local_name(root.tag),
        "namespace": namespace,
        "rootAttributes": sorted(root.attrib),
        "children": dict(children.most_common(12)),
        "childCount": sum(children.values()),
        "depth2": sorted(grandchildren)[:40],
        "depth2Counts": dict(grandchildren.most_common(8)),
        "identityNames": _identity_order([n for n in names if IDENTITY_NAMES.search(n)])[:8],
        "datedNames": sorted(n for n in names if DATED_NAMES.search(n))[:4],
    }


def _json_shape(value: Any) -> dict[str, Any]:
    """Top-level keys and, for arrays, record count and the distribution of ``id`` key families."""
    if isinstance(value, dict):
        return {"keys": sorted(value)[:12], "count": value.get("count")}
    if isinstance(value, list):
        kinds = Counter(k for record in value if isinstance(record, dict) for k in (record.get("id") or {}))
        first = value[0] if value and isinstance(value[0], dict) else {}
        return {"count": len(value), "keys": sorted(first)[:12], "idKinds": dict(kinds.most_common(16))}
    return {}


def measure_samples(probe: KeylessProbe) -> dict[str, Any]:
    """One keyless capture and shape per publisher sample: size, digest, root and stated identity names."""
    out: dict[str, Any] = {}
    for key, (url, media_types) in SAMPLES.items():
        try:
            capture = probe.get(url, media_types=media_types, max_bytes=SAMPLE_MAX_BYTES)
            facts = {"url": url, **_capture_facts(capture)}
            if media_types is JSON_TYPES:
                facts["shape"] = _json_shape(json.loads(capture.body))
            elif media_types == ("text/html",):
                facts["shape"] = {"html": True}
            else:
                facts["shape"] = _xml_shape(capture.body, key)
        except CredentialRefusedError as error:
            facts = {"url": url, "error": "CredentialRefusedError", "message": str(error)[:120], "statusCode": 403}
        except (ProbeError, ValueError) as error:
            facts = {"url": url, **_error(error)}
        out[key] = facts
        print(f"sample {key}: {facts.get('statusCode', facts.get('error'))}", file=sys.stderr)
    return out


# --- comparisons: overlapping routes measured against each other on a bounded scope ---------------

COMPARE_CONGRESS = 118
COMPARE_YEAR = 2025
COMPARE_VOLUME = 171
NOMINATION_FEEDS = (
    "CivilianConfirmed", "CivilianPendingCalendar", "CivilianPendingCommittee", "FailedOrReturned",
    "NonCivilianConfirmed", "NonCivilianPendingCommittee", "NonCivilianPendingCalendar", "Privileged", "Withdrawn",
)  # fmt: skip
BIOGUIDE_TAGS = frozenset({"bioguideID", "bioguideId", "bioguide_id"})


def _bioguides(root: Any) -> set[str]:
    """Bioguide ids wherever a publisher file keeps them: a named child element or any attribute naming bioguide."""
    found = set(_texts(root, BIOGUIDE_TAGS))
    for el in root.iter():
        found |= {v.strip() for k, v in el.attrib.items() if "bioguide" in k.lower() and v.strip()}
    return found


def _texts(root: Any, names: frozenset[str] | set[str]) -> list[str]:
    """Stripped text of every element whose local name is in ``names``."""
    return [el.text.strip() for el in root.iter() if local_name(el.tag) in names and el.text and el.text.strip()]


def _walk(reader: PagedJsonReader, url: str, records_key: str, max_pages: int) -> list[Mapping[str, Any]]:
    """Every record from up to ``max_pages`` pages of a keyed list, counted against the shared counter."""
    rows: list[Mapping[str, Any]] = []
    for page in reader.pages(url, records_key=records_key, max_pages=max_pages):
        REQUESTS[reader.family.name] += 1
        rows.extend(page.records)
    return rows


def _congress_list(reader: PagedJsonReader, path: str, key: str, max_pages: int) -> list[Mapping[str, Any]]:
    """Walk a Congress.gov list route at ``limit=250``, the publisher's page maximum."""
    return _walk(reader, f"{CONGRESS_API}/{path}?{urlencode({'format': 'json', 'limit': 250})}", key, max_pages)


def _govinfo_published(
    reader: PagedJsonReader, code: str, start: str, end: str, max_pages: int
) -> list[Mapping[str, Any]]:
    """Walk one GovInfo collection's published-packages window, a bounded number of pages."""
    return _walk(reader, published_url(start, end, collections=[code], page_size=1000), "packages", max_pages)


def _keyed_json(reader: PagedJsonReader, url: str) -> Mapping[str, Any]:
    """One keyed JSON GET parsed as a mapping, bounded and validated by the reader."""
    REQUESTS[reader.family.name] += 1
    value, _ = reader.capture_validated(
        url,
        media_types=JSON_TYPES,
        parse=lambda capture, _limit: json.loads(capture.body),
        max_bytes=4 * 1024 * 1024,
        unavailable=ProbeUnavailableError,
        context={"operation": "json", "url": url},
    )
    return value


def _xml(probe: KeylessProbe, url: str, key: str) -> Any:
    """Fetch one keyless XML sample and return its parsed root element."""
    capture = probe.get(url, media_types=XML_TYPES, max_bytes=SAMPLE_MAX_BYTES)
    return parse_xml(
        capture.body,
        max_bytes=len(capture.body),
        error_type=ProbeError,
        label=key,
        allow_external_doctype=True,
        max_depth=64,
    )


def _result(a: str, b: str, scope: str, left: set[str], right: set[str], detail: str, **extra: Any) -> dict[str, Any]:
    """The common comparison record: both sides' counts, their overlap, and capped per-side-only samples."""
    return {
        "a": a, "b": b, "scope": scope,
        "aCount": len(left), "bCount": len(right), "both": len(left & right),
        "onlyA": sorted(left - right)[:40], "onlyACount": len(left - right),
        "onlyB": sorted(right - left)[:40], "onlyBCount": len(right - left),
        "detail": detail, **extra,
    }  # fmt: skip
