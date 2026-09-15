"""Capture one complete AO-number year with separate metadata and originals.

Run with ``uv run --frozen --extra acquisition python examples/fec_legal_year.py
ROOT --year 2024 --env-file PATH --key-name FEC_API_KEY``. Re-running reuses
verified metadata and successful originals, retrying every unsuccessful original.
``--verify-only`` performs retained replay without credentials or HTTP.

The selection is the union of the complete legal/aos/YEAR- XML listing and every
supporting-document asset in ao_year=YEAR search/detail JSON. AO number year is not issuance year.
Linked/cited other opinions remain references. Originals are bounded by aggregate
bytes and requests; every discovered URL or missing document URL has a disposition.
This example does not publish a release or claim a frozen publisher snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from rulespec_artifacts import LocalBlobSource

from spicy_docs.reading.refusals import retain_refused_response
from spicy_docs.reading.s3_listing import parse_s3_listing
from spicy_docs.sources.fec.catalog import BUCKET, BUCKET_URL, official_url
from spicy_docs.sources.fec.client import FecClient
from spicy_docs.sources.fec.metadata import api_page, parse_api, resolve_link, split_record
from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key, scrub_credential
from spicy_docs.transport.download import HttpRefusal


def encoded(value):
    return json.dumps(value, default=str, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded(value) + b"\n")
    temporary.replace(path)


def pin(path):
    return {"file": path.name, "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}


def blob_bytes(store, evidence):
    with LocalBlobSource(store).open(evidence["sha256"]) as stream:
        raw = stream.read(evidence["bytes"] + 1)
    if len(raw) != evidence["bytes"] or "sha256:" + hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
        raise ValueError("retained source bytes differ from their pin")
    return raw


def verify_page(page, *, label, store, year):
    """Reparse complete retained responses; compare all mapped fields and pointers."""
    raw = blob_bytes(store, page["evidence"])
    if label == "listing":
        prefix = f"legal/aos/{year}-"
        objects, token = parse_s3_listing(raw, bucket=BUCKET, prefix=prefix)
        records = [
            split_record(
                {
                    **asdict(obj),
                    "url": BUCKET_URL + quote(obj.key, safe="/"),
                    "fec_url": "https://www.fec.gov/files/" + quote(obj.key, safe="/"),
                },
                source_pointer=None,
            )
            for obj in objects
        ]
        changes = {"continuation-token": token} if token else None
    else:
        value = parse_api(raw)
        rows, changes, context = api_page(value, url=page["request_url"], mode="legal" if label == "search" else "docs")
        records = [split_record(row, source_pointer=pointer) for pointer, row in rows]
        if context.get("pagination") != page.get("pagination"):
            raise ValueError("retained legal pagination changed")
    next_url = None
    if changes is not None:
        url = urlsplit(page["request_url"])
        pairs = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True) if k not in changes]
        pairs.extend((k, str(v)) for k, v in changes.items())
        next_url = urlunsplit((url.scheme, url.netloc, url.path, urlencode(pairs), ""))
    if encoded(records) != encoded(page["records"]) or next_url != page["next_url"]:
        raise ValueError("retained metadata, associations or continuation differs from source bytes")


def capture_metadata(client, root, year, *, secret=""):
    """A failed metadata traversal keeps its partial log; retry starts a fresh observation."""
    path = root / f"metadata-{uuid4().hex}.jsonl"
    events = []
    with path.open("xb") as stream:

        def record(label, pages):
            try:
                for page in pages:
                    event = {"label": label, "page": page}
                    stream.write(encoded(event) + b"\n")
                    stream.flush()
                    events.append(event)
            except (ValueError, RuntimeError, OSError) as error:
                failure = {
                    "operation": label,
                    "complete": False,
                    "partial_metadata": pin(path),
                    "error": scrub_credential(str(error), secret)[:1000],
                }
                refused = retain_refused_response(error, store=root / "blobs", max_bytes=8 * 1024**2, credential=secret)
                if refused:
                    failure["refused_evidence"] = refused
                save(path.with_suffix(".failure.json"), failure)
                raise

        record("listing", client.objects(f"legal/aos/{year}-", max_pages=20))
        record(
            "search",
            client.api(
                "/v1/legal/search/",
                params={"type": "advisory_opinions", "ao_year": year, "hits_returned": 100},
                max_pages=20,
            ),
        )
        try:
            cases = case_ids(events, year)
        except ValueError as error:
            save(
                path.with_suffix(".failure.json"),
                {
                    "operation": "case-selection",
                    "complete": False,
                    "partial_metadata": pin(path),
                    "error": scrub_credential(str(error), secret)[:1000],
                },
            )
            raise
        for case in cases:
            record("detail:" + case, client.api(f"/v1/legal/docs/advisory_opinions/{case}", max_pages=1))
    manifest = {
        "year": year,
        "metadata": pin(path),
        "observed_at": datetime.now(UTC).isoformat(),
        "scope": "Complete observed AO-number year search plus legal/aos/YEAR- listing; no issuance-year or historical completeness claim.",
    }
    try:
        load_plan(root, manifest=manifest)
    except (ValueError, TypeError, KeyError) as error:
        save(
            path.with_suffix(".failure.json"),
            {
                "operation": "metadata-validation",
                "complete": False,
                "partial_metadata": pin(path),
                "error": scrub_credential(str(error), secret)[:1000],
            },
        )
        raise
    save(root / "selection.json", manifest)
    return manifest


def case_ids(events, year):
    search = [event["page"] for event in events if event["label"] == "search"]
    cases = [row["metadata"]["ao_no"] for page in search for row in page["records"]]
    totals = {page["pagination"]["total_advisory_opinions"] for page in search}
    if totals != {len(cases)} or len(set(cases)) != len(cases):
        raise ValueError("legal search count or unique AO membership differs")
    if any(re.fullmatch(f"{year}-[0-9]+", case) is None for case in cases):
        raise ValueError("legal search returned an AO outside the selected number year")
    # Directory-only cases still receive an explicit detail request.
    directories = {
        row["metadata"]["key"].split("/")[2]
        for event in events
        if event["label"] == "listing"
        for row in event["page"]["records"]
    }
    if any(re.fullmatch(f"{year}-[0-9]+", case) is None for case in directories):
        raise ValueError("legal directory falls outside the selected AO number year")
    return sorted(set(cases) | directories)


def load_plan(root, *, manifest=None):
    if manifest is None:
        manifest = json.loads((root / "selection.json").read_bytes())
    path = root / manifest["metadata"]["file"]
    if pin(path) != manifest["metadata"]:
        raise ValueError("selected metadata inventory changed")
    events = [json.loads(line) for line in path.read_bytes().splitlines()]
    year = manifest["year"]
    by_label = {}
    for event in events:
        label, page = event["label"], event["page"]
        verify_page(page, label=label, store=root / "blobs", year=year)
        previous = by_label.setdefault(label, [])
        if not previous:
            url = urlsplit(official_url(page["request_url"]))
            query = parse_qs(url.query)
            if label == "listing":
                valid = url.hostname == urlsplit(BUCKET_URL).hostname and query == {
                    "list-type": ["2"],
                    "prefix": [f"legal/aos/{year}-"],
                    "max-keys": ["1000"],
                }
            elif label == "search":
                valid = (
                    url.hostname == "api.open.fec.gov"
                    and url.path == "/v1/legal/search/"
                    and query == {"type": ["advisory_opinions"], "ao_year": [str(year)], "hits_returned": ["100"]}
                )
            else:
                valid = (
                    url.hostname == "api.open.fec.gov"
                    and not query
                    and url.path == ("/v1/legal/docs/advisory_opinions/" + label.removeprefix("detail:"))
                )
            if not valid:
                raise ValueError("initial metadata request differs from the declared complete year selection")
        if previous and previous[-1]["next_url"] != page["request_url"]:
            raise ValueError("metadata traversal omits or repeats a page")
        previous.append(page)
    if any(pages[-1]["next_url"] is not None for pages in by_label.values()):
        raise ValueError("metadata traversal is incomplete")
    cases = case_ids(events, year)
    if set(by_label) != {"listing", "search", *("detail:" + case for case in cases)}:
        raise ValueError("selected metadata operations differ from case membership")
    items, aliases, unavailable, case_outcomes = {}, {}, [], []
    for event in events:
        if event["label"] != "listing":
            continue
        for row in event["page"]["records"]:
            obj = row["metadata"]
            if obj["url"] in items:
                raise ValueError("listed original repeats")
            items[obj["url"]] = {"url": obj["url"], "listing": obj, "associations": []}
            aliases[obj["fec_url"]] = obj["url"]
    for event in events:
        label, page = event["label"], event["page"]
        if label == "listing":
            continue
        if label.startswith("detail:"):
            case = label.removeprefix("detail:")
            if len(page["records"]) > 1 or any(row["metadata"].get("ao_no") != case for row in page["records"]):
                raise ValueError("legal detail identity differs from requested AO")
            case_outcomes.append(
                {
                    "ao_no": case,
                    "disposition": "returned" if page["records"] else "requested-empty",
                    "evidence": page["evidence"],
                }
            )
        for row in page["records"]:
            case = row["metadata"]["ao_no"]
            # Citation links remain references; only this case's documents are selected.
            assets = [
                asset
                for asset in row["assets"]
                if asset["source_pointer"].startswith(row["source_pointer"] + "/documents/")
            ]
            pointers = {asset["source_pointer"] for asset in assets}
            for index, document in enumerate(row["metadata"].get("documents", [])):
                pointer = row["source_pointer"] + f"/documents/{index}/url"
                if not isinstance(document.get("url"), str) or not document["url"]:
                    unavailable.append(
                        {
                            "ao_no": case,
                            "operation": label,
                            "disposition": "unavailable-missing-url",
                            "source_pointer": pointer,
                            "evidence": page["evidence"],
                        }
                    )
                elif pointer not in pointers:
                    assets.append(
                        {"url": resolve_link(document["url"], base="https://www.fec.gov/"), "source_pointer": pointer}
                    )
            for asset in assets:
                try:
                    url = official_url(asset["url"])
                except ValueError:
                    unavailable.append(
                        {
                            "ao_no": case,
                            "operation": label,
                            "disposition": "unavailable-outside-approved-hosts",
                            "source_url": asset["url"],
                            "source_pointer": asset["source_pointer"],
                            "evidence": page["evidence"],
                        }
                    )
                    continue
                target = aliases.get(url, url)
                item = items.setdefault(target, {"url": target, "listing": None, "associations": []})
                item["associations"].append(
                    {
                        "ao_no": case,
                        "operation": label,
                        "source_url": url,
                        "source_pointer": asset["source_pointer"],
                        "evidence": page["evidence"],
                    }
                )
    return manifest, {
        "originals": sorted(items.values(), key=lambda item: item["url"]),
        "unavailable": unavailable,
        "cases": case_outcomes,
    }


def acquire_originals(client, root, plan, *, max_bytes, secret=""):
    path = root / "originals.json"
    prior = original_rows(root)
    if prior and [row["selected"] for row in prior] != plan["originals"]:
        raise ValueError("original selection changed on resume")
    rows = prior or [{"selected": item, "disposition": "unrequested", "attempts": []} for item in plan["originals"]]
    save(path, rows)

    def checkpoint(row):
        # Atomic per-object state survives interruption without rewriting the population.
        progress = root / "original-progress"
        progress.mkdir(exist_ok=True)
        save(progress / (hashlib.sha256(row["selected"]["url"].encode()).hexdigest() + ".json"), row)

    used = 0
    for row in rows:
        if row["disposition"] == "acquired":
            blob_bytes(root / "blobs", row["acquisition"])
            used += row["acquisition"]["bytes"]
    if used > max_bytes:
        raise ValueError("already acquired originals exceed the selected aggregate byte bound")
    for number, row in enumerate(rows, 1):
        if row["disposition"] == "acquired":
            continue
        item = row["selected"]
        listing = item["listing"]
        remaining = max_bytes - used
        if remaining <= 0 or listing and listing["size"] > remaining:
            row["disposition"] = "unrequested-byte-bound"
            checkpoint(row)
            continue
        try:
            result = client.download(
                item["url"],
                max_bytes=min(remaining, 32 * 1024**2),
                expected_size=listing["size"] if listing else None,
                etag=listing["etag"] if listing else None,
            )
            row.update(disposition="acquired", acquisition=result)
            used += result["bytes"]
        except (ValueError, RuntimeError, OSError) as error:
            row["disposition"] = "failed"
            row["attempts"].append(
                {"at": datetime.now(UTC).isoformat(), "error": scrub_credential(str(error), secret)[:1000]}
            )
            refused = retain_refused_response(error, store=root / "blobs", max_bytes=8 * 1024**2, credential=secret)
            if refused:
                row["attempts"][-1]["refused_evidence"] = refused
            checkpoint(row)
            if (
                isinstance(error, CredentialRefusedError)
                or isinstance(error, HttpRefusal)
                and error.status in {401, 403}
            ):
                raise
        checkpoint(row)
        print(f"original {number}/{len(rows)}: {row['disposition']}", flush=True)
    save(path, rows)
    return rows


def original_rows(root):
    path = root / "originals.json"
    rows = json.loads(path.read_bytes()) if path.exists() else []
    by_url = {row["selected"]["url"]: row for row in rows}
    for progress in (root / "original-progress").glob("*.json"):
        row = json.loads(progress.read_bytes())
        url = row["selected"]["url"]
        previous = by_url.get(url)
        if (
            previous is None
            or previous["selected"] != row["selected"]
            or progress.stem != hashlib.sha256(url.encode()).hexdigest()
        ):
            raise ValueError("original progress changed a selected association")
        by_url[url] = row
    return [by_url[row["selected"]["url"]] for row in rows]


def verify(root):
    manifest, plan = load_plan(root)
    rows = original_rows(root)
    if [row["selected"] for row in rows] != plan["originals"]:
        raise ValueError("original dispositions omit or change a selected association")
    for row in rows:
        if row["disposition"] == "acquired":
            acquisition = row["acquisition"]
            blob_bytes(root / "blobs", acquisition)
            listing = row["selected"]["listing"]
            if acquisition["url"] != row["selected"]["url"] or listing and acquisition["bytes"] != listing["size"]:
                raise ValueError("acquired original differs from its selected source")
        elif row["disposition"] not in {"failed", "unrequested-byte-bound"}:
            raise ValueError("selected original lacks a completed disposition")
    return {
        "year": manifest["year"],
        "metadata": manifest["metadata"],
        "originals": pin(root / "originals.json"),
        "progress": [pin(path) for path in sorted((root / "original-progress").glob("*.json"))],
        "cases": plan["cases"],
        "unavailable": plan["unavailable"],
        "counts": dict(Counter(row["disposition"] for row in rows)),
        "acquisition_complete": all(row["disposition"] == "acquired" for row in rows)
        and not plan["unavailable"]
        and all(case["disposition"] == "returned" for case in plan["cases"]),
        "acquired_bytes": sum(row["acquisition"]["bytes"] for row in rows if row["disposition"] == "acquired"),
        "scope": manifest["scope"],
        "verification": "All selected response bytes replayed, all associations compared, every acquired original hashed; PDF text/pages are not parsed.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--key-name", default="FEC_API_KEY")
    parser.add_argument("--zyte-on-denial", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=100 * 1024**2)
    parser.add_argument("--max-requests", type=int, default=250)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not 1975 <= args.year < datetime.now(UTC).year or args.max_bytes <= 0:
        raise ValueError("select a complete historical AO number year and positive byte bound")
    args.root.mkdir(parents=True, exist_ok=True)
    if not args.verify_only:
        key = read_api_key(args.env_file, args.key_name) if args.env_file else os.environ[args.key_name]
        from spicy_docs.sources.zyte import ZyteHttpFetcher

        zyte = (
            (
                ZyteHttpFetcher(read_api_key(args.env_file, "ZYTE_TOKEN"))
                if args.env_file
                else ZyteHttpFetcher.from_environment()
            )
            if args.zyte_on_denial
            else None
        )
        with FecClient(
            store=args.root / "blobs", api_key=key, zyte_on_denial=zyte, max_requests=args.max_requests, min_interval=1
        ) as client:
            if not (args.root / "selection.json").exists():
                capture_metadata(client, args.root, args.year, secret=key)
            manifest, plan = load_plan(args.root)
            if manifest["year"] != args.year:
                raise ValueError("resume cannot change the selected AO year")
            acquire_originals(client, args.root, plan, max_bytes=args.max_bytes, secret=key)
    result = verify(args.root)
    result["execution"] = {
        "command": sys.argv,
        "implementation": pin(Path(__file__).resolve()),
        "observed_at": datetime.now(UTC).isoformat(),
        "max_original_bytes": args.max_bytes,
        "max_requests": args.max_requests,
        "requests": 0 if args.verify_only else client.http.request_count,
    }
    save(args.root / "verification.json", result)
    print(json.dumps({key: result[key] for key in ("counts", "acquired_bytes", "acquisition_complete")}))
    return 0 if result["acquisition_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
