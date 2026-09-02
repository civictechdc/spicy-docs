#!/usr/bin/env python3
"""Census the multi-observation record identities in one published release.

``iter_records()`` yields only the winner; this replays the accepted traversal's
acquisition-pages evidence to recover every discarded observation too.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rulespec_artifacts import ArtifactPin, LocalMemberSource

from spicy_docs.regulations_gov_source_native import (
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    comment_source_issued_version,
    source_issued_version,
)
from spicy_docs.source_native import SourceNativeReleaseReader
from spicy_docs.source_native_profile import SourceNativeProfile
from spicy_docs.source_native_profiles import (
    FEDERAL_REGISTER_PROFILE,
    REGULATIONS_GOV_COMMENT_PROFILE,
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.source_native_store import LocalSourceNativeBlobStore

PROFILES: dict[str, SourceNativeProfile] = {
    "federal-register": FEDERAL_REGISTER_PROFILE,
    "regulations-gov-documents": REGULATIONS_GOV_DOCUMENT_PROFILE,
    "regulations-gov-dockets": REGULATIONS_GOV_DOCKET_PROFILE,
    "regulations-gov-comments": REGULATIONS_GOV_COMMENT_PROFILE,
}
RAW_VERSION = {
    "federal-register": lambda record: record.get("publication_date"),
    "regulations-gov-documents": lambda record: source_issued_version(record, collection=DOCUMENT_COLLECTION),
    "regulations-gov-dockets": lambda record: source_issued_version(record, collection=DOCKET_COLLECTION),
    "regulations-gov-comments": comment_source_issued_version,
}


def census(args: argparse.Namespace) -> dict[str, object]:
    profile = PROFILES[args.profile]
    raw_version = RAW_VERSION[args.profile]
    assert profile.observation_version is not None  # every profile in PROFILES declares one
    store = LocalSourceNativeBlobStore(args.blob_store, create=False)
    SourceNativeReleaseReader(  # admits and structurally verifies (cheap digest/shape tier)
        LocalMemberSource(args.release),
        blob_source=store,
        profile=profile,
        expected_pin=ArtifactPin(args.logical_id, args.artifact_digest),
        accepted_verifier_implementation_ids=frozenset({args.verifier_implementation_id}),
    )
    receipt = json.loads((args.release / "receipts/publication.json").read_bytes())
    observations: dict[str, list[tuple[str | None, str | None]]] = defaultdict(list)
    digests: dict[str, set[str]] = defaultdict(set)
    for partition in receipt["payloadPartitions"]:
        if partition["partitionKind"] != "acquisition-pages":
            continue
        with store.open(partition["blobRef"]) as stream:
            rows = [row for row in (json.loads(line) for line in stream) if row["accepted"]]
        for row in rows:
            with store.open(row["evidenceBlobRef"]) as evidence:
                response = profile.parse_page_response(evidence.read())
            for discovered, raw in zip(row["discoveredRecords"], response.get("results") or [], strict=True):
                classified = profile.classify_record(raw)
                pair = (raw_version(classified), profile.observation_version(classified))
                observations[discovered["sourceRecordId"]].append(pair)
                digests[discovered["sourceRecordId"]].add(discovered["recordDigest"])
    multi_observation: list[dict[str, object]] = []
    discarded = 0
    for identity, seen in sorted(observations.items()):
        if len(seen) <= 1:
            continue
        discarded += len(seen) - 1
        winner_raw, _ = max(seen, key=lambda pair: (pair[1] is not None, pair[1]))
        entry: dict[str, object] = {
            "recordId": identity,
            "observationCount": len(seen),
            "versions": [raw for raw, _ in seen],
            "winner": winner_raw,
            "distinctDigests": len(digests[identity]),
        }
        if args.profile == "federal-register":
            entry["post2000"] = any(raw is not None and raw > "1999-12-31" for raw, _ in seen)
        multi_observation.append(entry)
    return {
        "profile": args.profile,
        "multiObservationRecords": multi_observation,
        "totals": {
            "records": len(observations),
            "multiObservationIds": len(multi_observation),
            "discardedObservations": discarded,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True, help="Published release root")
    parser.add_argument("--blob-store", type=Path, required=True, help="Explicit persistent blob store")
    parser.add_argument("--logical-id", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--verifier-implementation-id", required=True)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    print(json.dumps(census(parser.parse_args(argv)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
