#!/usr/bin/env python3
"""What moved when a producer change republished a source-native release?

A producer change is testable without a fresh crawl: replay the retained
acquisition evidence through the new code (``replay_federal_register_release``)
and compare the two releases. This is the comparison half. It answers the
question a receipt actually has to answer -- *did the change add records, or
did it also perturb existing ones?* -- and it answers it from the published
records of both releases.

That is deliberately a different route from ``fr_discarded_distinctness``,
which measures the same recovery from the OLD release's pre-collapse
acquisition evidence. Different member role, different code path, different
notion of the quantity: what the builder emitted, versus what the acquisition
pages contained. Two routes agreeing is evidence; one route agreeing with
itself is a formatting assertion.

Identity fields are named by the caller rather than guessed, because the whole
point of a comparison like this is that a release's identity policy may be the
thing that changed. For a Federal Register composite-identity rebuild::

    --identity-field document_number --identity-field publication_date

Baseline records are held as a digest of the canonical payload, so memory is
one small entry per record rather than the corpus.

Promoted from a session-scratch script on 2026-09-05, for the reason
``fr_discarded_distinctness`` records in its own docstring (SD-18): its numbers
were load-bearing in a receipt while the code that produced them lived only in
a scratchpad. Reads blobs through ``LocalSourceNativeBlobStore``, which
verifies each blob's bytes against its digest, rather than hand-joining
``sha256:<hex>`` references into filesystem paths.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spicy_docs.source_native import ROLE_RECORDS
from spicy_docs.source_native_store import LocalSourceNativeBlobStore

MANIFEST_PATH: tuple[str, str] = ("manifests", "source-native.json")
RECEIPT_PATH: tuple[str, str] = ("receipts", "publication.json")


def _canonical_digest(payload: Any) -> bytes:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).digest()


def _records(release_root: Path, store: LocalSourceNativeBlobStore):
    members = json.loads(release_root.joinpath(*MANIFEST_PATH).read_text())["members"]
    for member in (m for m in members if m["role"] == ROLE_RECORDS):
        with store.open(member["blobRef"]) as handle:
            for line in handle:
                yield json.loads(line)


def _identity(record: dict[str, Any], fields: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(record.get(f) for f in fields)


def compare(
    baseline_root: Path,
    candidate_root: Path,
    blob_store: Path,
    identity_fields: tuple[str, ...],
    compare_fields: tuple[str, ...],
) -> dict[str, Any]:
    store = LocalSourceNativeBlobStore(blob_store, create=False)

    print("pass A: digesting baseline records", file=sys.stderr)
    baseline: dict[tuple[Any, ...], bytes] = {}
    for row in _records(baseline_root, store):
        record = row["record"]
        key = _identity(record, identity_fields)
        if key in baseline:
            raise SystemExit(f"baseline repeats identity {key!r}; identity fields do not identify a record")
        baseline[key] = _canonical_digest(record)

    print(f"pass B: comparing candidate against {len(baseline):,} baseline records", file=sys.stderr)
    matched = 0
    changed: list[tuple[Any, ...]] = []
    added: dict[Any, list[dict[str, Any]]] = collections.defaultdict(list)
    candidate_count = 0
    seen: set[tuple[Any, ...]] = set()
    for row in _records(candidate_root, store):
        record = row["record"]
        candidate_count += 1
        key = _identity(record, identity_fields)
        if key in seen:
            raise SystemExit(f"candidate repeats identity {key!r}; identity is not unique in the candidate")
        seen.add(key)
        prior = baseline.get(key)
        if prior is None:
            added[key[0]].append(record)
        elif prior == _canonical_digest(record):
            matched += 1
        else:
            changed.append(key)

    result: dict[str, Any] = {
        "baselineRelease": str(baseline_root),
        "candidateRelease": str(candidate_root),
        "identityFields": list(identity_fields),
        "baselineRecordCount": len(baseline),
        "candidateRecordCount": candidate_count,
        "recordCountDelta": candidate_count - len(baseline),
        "baselineRecordsMatchedByteForByte": matched,
        "baselineRecordsChanged": len(changed),
        "baselineRecordsChangedExamples": [list(k) for k in changed[:10]],
        "baselineRecordsMissingFromCandidate": len(baseline) - matched - len(changed),
        "addedRecordCount": sum(len(v) for v in added.values()),
        "addedRecordCountPopulation": "candidate records whose identity tuple is absent from the baseline",
        "addedOverDistinctFirstIdentityField": len(added),
        "receipts": {
            side: {
                k: json.loads(root.joinpath(*RECEIPT_PATH).read_text()).get(k)
                for k in (
                    "publishedRecordCount",
                    "discardedObservationCount",
                    "semanticVerdict",
                    "releaseSchemaDigest",
                    "verifierImplementationId",
                )
            }
            for side, root in (("baseline", baseline_root), ("candidate", candidate_root))
        },
    }

    if not compare_fields or not added:
        return result

    # For each added record, compare against the baseline record sharing its
    # first identity field (for FR: the surviving record for that document
    # number). Same four-field comparison fr_discarded_distinctness uses, so the
    # two routes produce comparable splits.
    print("pass C: reading comparison fields for the added records", file=sys.stderr)
    survivor_key: dict[Any, tuple[Any, ...]] = {}
    for key in baseline:
        survivor_key.setdefault(key[0], key)
    survivors: dict[Any, dict[str, Any]] = {}
    for row in _records(baseline_root, store):
        record = row["record"]
        key = _identity(record, identity_fields)
        if key[0] in added and survivor_key.get(key[0]) == key:
            survivors[key[0]] = {f: record.get(f) for f in compare_fields}

    identical = differing = title_variants = 0
    field_diff: collections.Counter[str] = collections.Counter()
    no_survivor = 0
    for head, records in added.items():
        survivor = survivors.get(head)
        if survivor is None:
            no_survivor += 1
            continue
        for record in records:
            diff = [f for f in compare_fields if record.get(f) != survivor[f]]
            field_diff.update(diff)
            if diff:
                differing += 1
                # Heuristic, and labelled as one: a title that is a prefix of the
                # survivor's is very likely a republication. It narrows the
                # residual; it decides no single case.
                st = str(survivor.get("title") or "").strip().rstrip(".;, ")
                dt = str(record.get("title") or "").strip().rstrip(".;, ")
                if st and dt and (st.startswith(dt) or dt.startswith(st)):
                    title_variants += 1
            else:
                identical += 1

    result |= {
        "comparedOn": list(compare_fields),
        "addedIdenticalToSurvivor": identical,
        "addedDifferingFromSurvivor": differing,
        "addedTitlePrefixVariants": title_variants,
        "addedTitlePrefixVariantsNote": "heuristic: one title a prefix of the other. Narrows the "
        "residual needing body-level adjudication; decides no single case, and a genuinely "
        "different document can share a title prefix with the survivor.",
        "addedDifferingResidual": differing - title_variants,
        "differingFieldCounts": dict(field_diff),
        "addedWithoutSurvivor": no_survivor,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-release", type=Path, required=True)
    parser.add_argument("--candidate-release", type=Path, required=True)
    parser.add_argument("--blob-store", type=Path, required=True, help="Explicit persistent blob store")
    parser.add_argument(
        "--identity-field",
        action="append",
        required=True,
        metavar="NAME",
        help="Record field forming the identity tuple; repeat in order. Named rather than "
        "guessed because a release's identity policy may be what changed.",
    )
    parser.add_argument(
        "--compare-field",
        action="append",
        default=None,
        metavar="NAME",
        help="Field to split added records on, against the baseline record sharing their first "
        "identity field. Repeat. Omit to report membership only.",
    )
    args = parser.parse_args(argv)
    report = compare(
        args.baseline_release,
        args.candidate_release,
        args.blob_store,
        tuple(args.identity_field),
        tuple(args.compare_field or ()),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
