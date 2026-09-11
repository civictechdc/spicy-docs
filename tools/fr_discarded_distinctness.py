#!/usr/bin/env python3
"""How many of the Federal Register's discarded observations are distinct documents?

The acquisition policy collapses by /document_number keeping the newest
/publication_date, so where the Register reuses a number the older document is
discarded. The release therefore cannot answer this question -- the discarded
records are only in the acquisition evidence, which is the pre-collapse
population.

Method fixed by doc1 in DocSpec 0003: compare a discarded observation against
the survivor on type, title, agencies and abstract. Deliberately NOT on
document_number or publication_date -- those are what the collapse already
keyed on, and re-measuring them would repeat the census tautology that hid this
in the first place. No inference is drawn from an identifier's year code:
E8-30793 published 2009-01-02 proves a year family spills into January
legitimately.

Two passes so memory stays bounded: pass A keeps only number -> set of dates,
pass B re-reads and retains full records only for numbers observed on more than
one date.

SD-18: promoted from a session-scratch script whose one measured output lived
only in a receipt JSON in the corpora tree, not a committed tool -- the same
"measured once by a throwaway script whose output lived in a chat log" gap that
``tools/cross_filing_census.py`` (SD-16, SD-17) was built to close. This module
takes ``--release-root``/``--blob-store`` in place of the original's hardcoded
``~/Work/corpora`` paths so the same measurement is re-derivable against any
Federal Register source-native release, and reads blobs through
``LocalSourceNativeBlobStore`` (the platform's own content-addressed reader,
which verifies each blob's bytes against its digest) instead of hand-joining
``sha256:<hex>`` blob references into filesystem paths.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spicy_docs.source_native import ROLE_EVIDENCE, ROLE_RECORDS
from spicy_docs.source_native_store import LocalSourceNativeBlobStore

FIELDS: tuple[str, ...] = ("type", "title", "agencies", "abstract")
MANIFEST_PATH: tuple[str, str] = ("manifests", "source-native.json")
RECEIPT_PATH: tuple[str, str] = ("receipts", "publication.json")


def census(release_root: Path, blob_store: Path) -> dict[str, Any]:
    store = LocalSourceNativeBlobStore(blob_store, create=False)
    members = json.loads(release_root.joinpath(*MANIFEST_PATH).read_text())["members"]
    evidence = [m for m in members if m["role"] == ROLE_EVIDENCE]
    records = [m for m in members if m["role"] == ROLE_RECORDS]

    def evidence_results():
        for m in evidence:
            with store.open(m["blobRef"]) as fh:
                page = json.load(fh)
            for row in page.get("results") or ():
                num = row.get("document_number")
                if num is not None:
                    yield num, row

    print("pass A: counting dates per document_number", file=sys.stderr)
    dates: dict[str, set[Any]] = collections.defaultdict(set)
    # Which fields the crawl actually captured. RefSpec had to adjudicate the seven
    # modern-form collisions from document bodies because correction_of answered
    # null -- this records whether the field is even present here, since "absent
    # from the evidence" and "null in the evidence" are different limits with
    # different fixes.
    available_fields: collections.Counter[str] = collections.Counter()
    seen_rows = 0
    for num, row in evidence_results():
        seen_rows += 1
        if seen_rows <= 5000:
            available_fields.update(row.keys())
        dates[num].add(row.get("publication_date"))
    multi = {n for n, ds in dates.items() if len(ds) > 1}
    single_observed = len(dates) - len(multi)
    distinct_observations = sum(len(ds) for ds in dates.values())
    del dates

    # Independent cross-check supplied by doc1: the release receipt carries
    # discardedObservationCount = inputObservationCount - publishedRecordCount, and
    # publication refuses unless the equation balances. That compares two separately
    # computed quantities, so reconciling this enumeration against it is a real check
    # -- unlike the census question that hid this defect, which compared a filter
    # against its own output. If these disagree, one of the two is wrong.
    receipt = json.loads(release_root.joinpath(*RECEIPT_PATH).read_text())
    receipt_input = receipt.get("inputObservationCount")
    receipt_published = receipt.get("publishedRecordCount")
    receipt_discarded = receipt.get("discardedObservationCount")

    print(f"pass B: retaining {len(multi)} multi-date numbers", file=sys.stderr)
    observed: dict[str, dict[Any, dict[str, Any]]] = collections.defaultdict(dict)
    for num, row in evidence_results():
        if num in multi:
            observed[num][row.get("publication_date")] = {f: row.get(f) for f in FIELDS}

    print("reading survivors from the release", file=sys.stderr)
    survivors: dict[str, tuple[Any, dict[str, Any]]] = {}
    for m in records:
        with store.open(m["blobRef"]) as fh:
            for line in fh:
                if not line.strip():
                    continue
                d = json.loads(line)
                num = d.get("sourceRecordId")
                if num in multi:
                    r = d["record"]
                    survivors[num] = (r.get("publication_date"), {f: r.get(f) for f in FIELDS})

    distinct_docs: list[dict[str, Any]] = []
    true_reobs: list[dict[str, Any]] = []
    no_survivor: list[Any] = []
    title_variants: list[dict[str, Any]] = []
    field_diff: collections.Counter[str] = collections.Counter()
    discarded_total = 0
    for num in sorted(multi):
        if num not in survivors:
            no_survivor.append(num)
            continue
        surv_date, surv = survivors[num]
        for date, obs in observed[num].items():
            if date == surv_date:
                continue
            discarded_total += 1
            differing = [f for f in FIELDS if obs[f] != surv[f]]
            for f in differing:
                field_diff[f] += 1
            # Heuristic only, and labelled as such in the output: a discarded record
            # whose title is a prefix/suffix variant of the survivor's (00-12867 differs
            # solely by a trailing "; Republication") is very likely the same document
            # republished, not a reused number. This narrows the residual that needs
            # body-level adjudication; it does not decide any single case.
            st = (surv["title"] or "").strip().rstrip(".;, ")
            dt = (obs["title"] or "").strip().rstrip(".;, ")
            title_variant = bool(st and dt) and (st.startswith(dt) or dt.startswith(st))
            if differing and title_variant:
                title_variants.append(
                    {
                        "documentNumber": num,
                        "survivorTitle": st[:120],
                        "discardedTitle": dt[:120],
                        "differingFields": differing,
                    }
                )
            (distinct_docs if differing else true_reobs).append(
                {
                    "documentNumber": num,
                    "survivorDate": surv_date,
                    "discardedDate": date,
                    "differingFields": differing,
                    "survivorTitle": (surv["title"] or "")[:100],
                    "discardedTitle": (obs["title"] or "")[:100],
                }
            )

    return {
        "population": (
            f"every result row in the {len(evidence)} source-acquisition-evidence members of "
            f"{release_root} -- the pre-collapse population -- compared against the surviving "
            "record for the same document_number in the release's source-native-records members"
        ),
        "comparedOn": list(FIELDS),
        "notComparedOn": [
            "document_number",
            "publication_date",
            "(what the collapse already keyed on; comparing them would restate the filter)",
        ],
        "evidenceRowsRead": seen_rows,
        "distinctDocumentNumbersInEvidence": single_observed + len(multi),
        "numbersObservedOnOneDate": single_observed,
        "numbersObservedOnMoreThanOneDate": len(multi),
        "discardedObservationsExamined": discarded_total,
        "reconciliation": {
            "basis": "release receipt: discardedObservationCount = inputObservationCount - "
            "publishedRecordCount, an equation publication refuses to violate; compared "
            "against this scan's independent enumeration of the discarded observations",
            "receiptInputObservationCount": receipt_input,
            "receiptPublishedRecordCount": receipt_published,
            "receiptDiscardedObservationCount": receipt_discarded,
            "scanDistinctNumberDatePairs": distinct_observations,
            "scanDiscardedObservations": discarded_total,
            "agrees": receipt_discarded == discarded_total,
            "ifThisDisagrees": "one of the two is wrong; do not report the distinctness split until "
            "it is resolved, because the split is computed over this enumeration",
        },
        "discardedThatAreDistinctDocuments": len(distinct_docs),
        "discardedThatAreTrueReobservations": len(true_reobs),
        "distinctDocumentsPopulation": "discarded observations differing from the survivor on at "
        "least one of type/title/agencies/abstract",
        "trueReobservationsPopulation": "discarded observations identical to the survivor on all four compared fields",
        "differingFieldCounts": dict(field_diff),
        "differingFieldCountsPopulation": "of discardedThatAreDistinctDocuments, count differing in "
        "this field; one observation can count under several",
        "numbersWithNoSurvivorInRelease": no_survivor,
        "likelyRepublications": {
            "count": len(title_variants),
            "population": "of discardedThatAreDistinctDocuments, those where one title is a prefix "
            "of the other after trimming trailing punctuation -- e.g. 00-12867, whose "
            "titles differ only by a trailing '; Republication'",
            "status": "HEURISTIC, not an adjudication. It narrows the set needing body-level review; "
            "it does not decide any single case, and a genuinely different document can "
            "share a title prefix with the survivor.",
            "impliedLowerBoundOnDistinctDocuments": "discardedThatAreDistinctDocuments minus this "
            "count, itself still an estimate, not a floor",
            "examples": title_variants[:10],
        },
        "adjudicationLimit": {
            "capturedFields": sorted(available_fields),
            "capturedFieldsPopulation": "distinct field names seen across the first 5,000 evidence result rows",
            "correctionOfCaptured": "correction_of" in available_fields,
            "why": "RefSpec resolved the seven modern-form collisions from document bodies because "
            "correction_of answered null. Here the field was never requested by the "
            "acquisition policy, so it is absent rather than null: this scan cannot "
            "distinguish a self-correction from a reused number by metadata at all, and no "
            "re-reading of the existing evidence would change that. Adding correction_of to "
            "the FR acquisition field list would make future collisions adjudicable, but it "
            "moves the acquisition policy version and cannot recover it retroactively "
            "without refetching.",
        },
        "examples": distinct_docs[:15],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-root",
        type=Path,
        required=True,
        help="Federal Register source-native release directory (holds manifests/source-native.json "
        "and receipts/publication.json)",
    )
    parser.add_argument("--blob-store", type=Path, required=True, help="Explicit persistent blob store")
    args = parser.parse_args(argv)
    print(json.dumps(census(args.release_root, args.blob_store), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
