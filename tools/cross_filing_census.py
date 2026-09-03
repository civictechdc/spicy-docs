#!/usr/bin/env python3
"""Census cross-filed regulations.gov documents in one pass over the release list.

SD-16: consolidates six throwaway session scripts that each made a *separate*
~1.94M-record pass over the same releases, all keyed on the source's own
``objectId``: duplicate document ids sharing one objectId, whether the copies
agree in content, genuine co-issued rules vs. component/parent catch-all-docket
pairs, the letters segment in some document ids, and same-agency id repeats.

Every count below states its own population as a sibling field -- one of the
six original scripts' outputs was misread as a rate over the whole corpus when
it was a rate over a filtered subset, and that error nearly reached a
decision-maker. All counts are over input RECORDS read via
``SourceNativeReleaseReader.iter_records()``, not built catalog items: a
catalog build's dispositions can drop or transform records, so these numbers
will not equal catalog item counts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rulespec_artifacts import LocalMemberSource

from spicy_docs.source_native import SourceNativeReleaseReader
from spicy_docs.source_native_profiles import REGULATIONS_GOV_DOCUMENT_PROFILE
from spicy_docs.source_native_store import LocalSourceNativeBlobStore

DOCUMENTS_PROFILE_NAME = "regulations-gov-documents"
CATCH_ALL_DOCKET_SUFFIX = "_FRDOC_0001"
IDENTITY_FIELDS = ("title", "pageCount", "frDocNum", "documentType", "postedDate")
# EPA-HQ-OW-2025-0322-DRAFT-29781 -> ... docketSeq(0322) DRAFT docSeq(29781): a
# letters segment between the trailing <digits>-<LETTERS>-<digits>.
TAIL_SEGMENT_PATTERN = re.compile(r"-(\d+)-([A-Za-z][A-Za-z0-9]*)-(\d+)$")
_EXAMPLE_CAP = 8


def _normalized_title(value: object) -> str:
    return value.strip().lower().replace("–", "-") if isinstance(value, str) else ""


def _identity_signature(row: dict[str, Any]) -> tuple[object, ...]:
    return tuple(_normalized_title(row["title"]) if f == "title" else row[f] for f in IDENTITY_FIELDS)


def _is_catch_all(docket: str) -> bool:
    return docket.endswith(CATCH_ALL_DOCKET_SUFFIX)


def _examples(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [{"objectId": oid, "rows": rows} for oid, rows in list(groups.items())[:_EXAMPLE_CAP]]


def _scan(releases: list[list[str]], store: LocalSourceNativeBlobStore) -> dict[str, Any]:
    """Make the single admitted pass over every documents release and accumulate raw tallies."""
    considered = [r for r in releases if r[2] == DOCUMENTS_PROFILE_NAME]
    total = frdoc = repeats_within_agency = grammar_matched = 0
    by_object: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ids_per_agency: dict[str, set[str]] = defaultdict(set)
    segment_counts: Counter[str] = Counter()
    segment_agencies: dict[str, set[str]] = defaultdict(set)
    segment_examples: dict[str, list[str]] = defaultdict(list)

    for root_str, artifact_digest, _profile in considered:
        root = Path(root_str)
        receipt = json.loads((root / "receipts" / "publication.json").read_text())
        reader = SourceNativeReleaseReader(
            LocalMemberSource(root),
            blob_source=store,
            profile=REGULATIONS_GOV_DOCUMENT_PROFILE,
            expected_pin=None,
            accepted_verifier_implementation_ids=frozenset({receipt["verifierImplementationId"]}),
        )
        if reader.pin.artifact_digest != artifact_digest:
            raise SystemExit(
                f"artifact digest mismatch for {root}: input list says {artifact_digest}, "
                f"admitted release is {reader.pin.artifact_digest}"
            )
        agency = root.name.removeprefix("regs-documents-")
        for rec in reader.iter_records():
            attrs = rec["record"]["data"]["attributes"]
            record_id = rec["sourceRecordId"]
            total += 1
            docket = attrs.get("docketId") or ""
            frdoc += _is_catch_all(docket)
            repeats_within_agency += record_id in ids_per_agency[agency]
            ids_per_agency[agency].add(record_id)
            object_id = attrs.get("objectId")
            if object_id:
                by_object[object_id].append(
                    {f: attrs.get(f) for f in IDENTITY_FIELDS} | {"agency": agency, "id": record_id, "docket": docket}
                )
            match = TAIL_SEGMENT_PATTERN.search(record_id)
            if match is not None:
                grammar_matched += 1
                segment = match.group(2).upper()
                segment_counts[segment] += 1
                segment_agencies[segment].add(agency)
                if len(segment_examples[segment]) < 3:
                    segment_examples[segment].append(record_id)

    return {
        "releasesConsidered": len(considered),
        "releasesSkipped": len(releases) - len(considered),
        "total": total,
        "frdoc": frdoc,
        "by_object": by_object,
        "repeats_within_agency": repeats_within_agency,
        "grammar_matched": grammar_matched,
        "segment_counts": segment_counts,
        "segment_agencies": segment_agencies,
        "segment_examples": segment_examples,
    }


def _report(scan: dict[str, Any]) -> dict[str, Any]:
    """Turn the raw tallies from :func:`_scan` into the six-part report, every subset labelled."""
    by_object: dict[str, list[dict[str, Any]]] = scan["by_object"]
    duplicate = {oid: rows for oid, rows in by_object.items() if len({r["id"] for r in rows}) > 1}
    repeated_id = {oid: rows for oid, rows in duplicate.items() if len(rows) > len({r["id"] for r in rows})}
    same_agency = {oid: rows for oid, rows in duplicate.items() if len({r["agency"] for r in rows}) == 1}
    cross_agency = {oid: rows for oid, rows in duplicate.items() if oid not in same_agency}

    co_issued: dict[str, list[dict[str, Any]]] = {}
    single_real_docket: dict[str, list[dict[str, Any]]] = {}
    three_or_more_rows = 0
    for oid, rows in cross_agency.items():
        three_or_more_rows += len(rows) > 2
        real_rows = [r for r in rows if not _is_catch_all(r["docket"])]
        target = co_issued if len({r["agency"] for r in real_rows}) > 1 else single_real_docket
        target[oid] = rows

    agree: dict[str, list[dict[str, Any]]] = {}
    disagree: dict[str, list[dict[str, Any]]] = {}
    field_disagreement = dict.fromkeys(IDENTITY_FIELDS, 0)
    for oid, rows in duplicate.items():
        if len({_identity_signature(r) for r in rows}) == 1:
            agree[oid] = rows
            continue
        disagree[oid] = rows
        for field in IDENTITY_FIELDS:
            values = {_normalized_title(r["title"]) if field == "title" else r[field] for r in rows}
            field_disagreement[field] += len(values) > 1

    suspects = {
        oid: rows
        for oid, rows in duplicate.items()
        if len({r["frDocNum"] for r in rows}) > 1 or len({r["pageCount"] for r in rows}) > 1
    }
    suspects_all_fr_doc_num_null = sum(1 for rows in suspects.values() if all(r["frDocNum"] is None for r in rows))
    segment_counts: Counter[str] = scan["segment_counts"]
    segment_agencies: dict[str, set[str]] = scan["segment_agencies"]

    return {
        "scope": {
            "unitOfCount": (
                "input records read via SourceNativeReleaseReader.iter_records(), not built catalog "
                "items -- a catalog build's dispositions may drop or transform records, so these "
                "counts do not equal catalog item counts"
            ),
            "profileConsidered": DOCUMENTS_PROFILE_NAME,
            "releasesConsidered": scan["releasesConsidered"],
            "releasesSkipped": scan["releasesSkipped"],
            "releasesSkippedPopulation": (
                f"entries in the input release list whose profile is not '{DOCUMENTS_PROFILE_NAME}' "
                "(for example federal-register or regulations-gov-dockets); no count below includes them"
            ),
        },
        "totals": {
            "documentsScanned": scan["total"],
            "distinctObjectIds": len(by_object),
            "documentsInFrdocCatchAllDockets": scan["frdoc"],
            "documentsInFrdocCatchAllDocketsPopulation": (
                f"of documentsScanned, count whose docketId ends with '{CATCH_ALL_DOCKET_SUFFIX}'"
            ),
        },
        "duplicateGroups": {
            "population": "objectIds observed on more than one distinct sourceRecordId, out of distinctObjectIds",
            "count": len(duplicate),
            "withRepeatedSourceRecordId": {
                "population": (
                    "of duplicateGroups.count, groups where at least one sourceRecordId string repeats "
                    "(a redundant re-observation) alongside the genuinely distinct ids"
                ),
                "count": len(repeated_id),
            },
            "sameAgency": {
                "population": "of duplicateGroups.count, groups whose rows all belong to one agency",
                "count": len(same_agency),
            },
            "crossAgency": {
                "population": "of duplicateGroups.count, groups whose rows span more than one agency",
                "count": len(cross_agency),
            },
        },
        "crossAgencyBreakdown": {
            "population": "of duplicateGroups.crossAgency.count",
            "withThreeOrMoreObservationRows": three_or_more_rows,
            "coIssued": {
                "population": (
                    "cross-agency groups with two or more non-catch-all (real) dockets held by "
                    "different agencies -- genuine co-issued rules"
                ),
                "count": len(co_issued),
                "examples": _examples(co_issued),
            },
            "singleRealDocket": {
                "population": (
                    "cross-agency groups whose non-catch-all dockets belong to only one agency "
                    "(parent/component catch-all-docket shape, not a genuine co-issued rule)"
                ),
                "count": len(single_real_docket),
            },
        },
        "contentComparison": {
            "population": f"duplicateGroups.count groups, compared on: {', '.join(IDENTITY_FIELDS)}",
            "fieldsCompared": list(IDENTITY_FIELDS),
            "agree": len(agree),
            "disagree": len(disagree),
            "disagreeingFieldBreakdown": {
                "population": (
                    "of contentComparison.disagree groups, count where this field's values differ "
                    "across the group's rows; a group can be counted under more than one field"
                ),
                "counts": field_disagreement,
            },
            "examples": _examples(disagree),
        },
        "suspects": {
            "population": (
                "subset of duplicateGroups.count where frDocNum or pageCount specifically disagree -- "
                "narrower than contentComparison.disagree, which also weighs title/documentType/postedDate"
            ),
            "count": len(suspects),
            "allFrDocNumNull": {
                "population": "of suspects.count, groups where every row's frDocNum is null",
                "count": suspects_all_fr_doc_num_null,
            },
            "examples": _examples(suspects),
        },
        "idGrammar": {
            "population": "all documentsScanned records' sourceRecordId strings",
            "pattern": TAIL_SEGMENT_PATTERN.pattern,
            "matched": scan["grammar_matched"],
            "distinctSegmentValues": len(segment_counts),
            "segments": {
                segment: {
                    "population": f"of idGrammar.matched, records whose letters segment is '{segment}'",
                    "count": count,
                    "agencyCount": len(segment_agencies[segment]),
                    "agencies": sorted(segment_agencies[segment])[:_EXAMPLE_CAP],
                    "examples": scan["segment_examples"][segment],
                }
                for segment, count in segment_counts.most_common(40)
            },
        },
        "documentIdRepeatsWithinAgency": {
            "population": (
                "counted while iterating documentsScanned records grouped by the agency each record's "
                "own release was read under; a repeat is the same sourceRecordId observed more than "
                "once inside one agency's own release stream"
            ),
            "count": scan["repeats_within_agency"],
        },
    }


def census(release_list: Path, blob_store: Path) -> dict[str, Any]:
    releases = json.loads(release_list.read_text())
    store = LocalSourceNativeBlobStore(blob_store, create=False)
    return _report(_scan(releases, store))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--releases", type=Path, required=True, help="JSON [root, artifactDigest, profile] triples")
    parser.add_argument("--blob-store", type=Path, required=True, help="Explicit persistent blob store")
    args = parser.parse_args(argv)
    print(json.dumps(census(args.releases, args.blob_store), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
