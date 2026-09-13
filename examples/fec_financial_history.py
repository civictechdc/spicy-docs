"""Capture selected financial CSV histories through the existing FEC reader.

Every run creates a fresh observation directory; a shared blob store retains old
versions. A pinned previous receipt permits verified reuse after a fresh listing.
This source example neither normalizes financial rows nor schedules dataset jobs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from spicy_docs.sources.fec.client import FecClient
from spicy_docs.transport.credentials import scrub_credential

PREFIXES = ("bulk-downloads/19", "bulk-downloads/20", "bulk-downloads/data.fec.gov/lobbyist_bundle.csv")
SELECTOR = (
    r"bulk-downloads/(?:\d{4}/(?:CommunicationCosts|ElectioneeringComm)_\d{4}\.csv|data\.fec\.gov/lobbyist_bundle\.csv)"
)


def read_previous(path: Path | None, expected_sha256: str | None) -> dict | None:
    if path is None and expected_sha256 is None:
        return None
    if path is None or expected_sha256 is None:
        raise ValueError("previous receipt requires its exact SHA-256")
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024**2 + 1)
    if len(raw) > 8 * 1024**2:
        raise ValueError("previous receipt exceeds 8 MiB")
    if hashlib.sha256(raw).hexdigest() != expected_sha256.removeprefix("sha256:"):
        raise ValueError("previous receipt differs from its pin")
    value = json.loads(raw)
    if value["format"] != "fec-financial-history-observation-1" or value["selector"] != SELECTOR:
        raise ValueError("previous receipt has a different source selection")
    return value


def capture(client, output: Path, *, previous=None, max_bytes=128 * 1024**2, max_objects=100, max_pages=5):
    """Bound selected bytes before transfer; retain each acquisition outcome."""
    if any(type(x) is not int or x <= 0 for x in (max_bytes, max_objects, max_pages)):
        raise ValueError("all acquisition bounds must be positive integers")
    output.mkdir(parents=True, exist_ok=False)
    old = {row["source"]["key"]: row for row in previous["objects"]} if previous else {}
    selected = {}
    result = {
        "format": "fec-financial-history-observation-1",
        "observed_at": datetime.now(UTC).isoformat(),
        "prefixes": list(PREFIXES),
        "selector": SELECTOR,
        "bounds": {"bytes": max_bytes, "objects": max_objects, "pages_per_prefix": max_pages},
        "enumeration_complete": False,
        "objects": [],
        "limits": "Only matching files in these observed prefixes; no frozen publisher snapshot, financial interpretation or whole-FEC coverage. A missing previously listed key is not proof of publisher deletion.",
    }
    try:
        with (output / "listings.jsonl").open("x") as stream:
            for prefix in PREFIXES:
                for page in client.objects(prefix, max_pages=max_pages):
                    stream.write(json.dumps(page) + "\n")
                    stream.flush()
                    for record in page["records"]:
                        source = record["metadata"]
                        if re.fullmatch(SELECTOR, source["key"]):
                            if source["key"] in selected:
                                raise ValueError("duplicate selected source key")
                            selected[source["key"]] = {"source": source, "listing_evidence": page["evidence"]}
                            if len(selected) > max_objects:
                                raise ValueError("selected object bound exceeded before transfer")
        result["enumeration_complete"] = True
        result["not_listed_this_run"] = sorted(old.keys() - selected.keys())
        result["selected_bytes"] = sum(row["source"]["size"] for row in selected.values())
        if result["selected_bytes"] > max_bytes:
            raise ValueError("selected byte bound exceeded before transfer")
        for key, row in sorted(selected.items()):
            source = row["source"]
            prior = old.get(key)
            same = prior and all(prior["source"][k] == source[k] for k in ("url", "etag", "size", "last_modified"))
            prior_asset = prior.get("asset") if same and prior.get("outcome") == "acquired" else None
            row["change"] = "unchanged-listing" if same else "changed-listing" if prior else "newly-listed"
            try:
                if source["size"] == 0:
                    row["outcome"] = "listed-zero-bytes-not-acquired"
                else:
                    asset = client.download(
                        source["url"],
                        max_bytes=source["size"],
                        expected_size=source["size"],
                        expected_sha256=prior_asset["sha256"] if prior_asset else None,
                        etag=source["etag"],
                    )
                    # Reuse proves bytes, not a new observation of the original body.
                    if not asset["downloaded"] and prior_asset:
                        asset["response"] = prior_asset["response"]
                    row.update(outcome="acquired", asset=asset)
            except (ValueError, RuntimeError, OSError) as error:
                row.update(outcome="failed", error=scrub_credential(str(error), "")[:1000])
            result["objects"].append(row)
            with (output / "objects.jsonl").open("a") as stream:
                stream.write(json.dumps(row) + "\n")
            print(f"{key}: {row['outcome']}", flush=True)
    except (ValueError, RuntimeError, OSError) as error:
        result["error"] = scrub_credential(str(error), "")[:1000]
        recorded = {row["source"]["key"] for row in result["objects"]}
        result["objects"].extend(
            dict(row, outcome="not-requested") for key, row in selected.items() if key not in recorded
        )
    result["acquisition_complete"] = (
        result["enumeration_complete"]
        and "error" not in result
        and all(row["outcome"] == "acquired" for row in result["objects"])
    )
    result["requests"] = client.http.request_count
    result["completed_at"] = datetime.now(UTC).isoformat()
    with (output / "listings.jsonl").open("rb") as stream:
        result["listing_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    (output / "observation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--previous-sha256")
    parser.add_argument("--max-bytes", type=int, default=128 * 1024**2)
    parser.add_argument("--max-objects", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()
    previous = read_previous(args.previous, args.previous_sha256)
    with FecClient(store=args.store, max_requests=100, min_interval=0.25) as client:
        result = capture(
            client,
            args.output,
            previous=previous,
            max_bytes=args.max_bytes,
            max_objects=args.max_objects,
            max_pages=args.max_pages,
        )
    if args.previous:
        result["previous_receipt"] = {"path": str(args.previous), "sha256": args.previous_sha256}
    result["blob_store"] = str(args.store.resolve())
    (args.output / "observation.json").write_text(json.dumps(result, indent=2) + "\n")
    raise SystemExit(0 if result["acquisition_complete"] else 1)


if __name__ == "__main__":
    main()
