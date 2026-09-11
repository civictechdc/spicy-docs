#!/usr/bin/env python3
"""Census cross-filed regulations.gov records in one pass over the release list.

SD-16: consolidates six throwaway session scripts that each made a *separate*
~1.94M-record pass over the same releases, all keyed on the source's own
``objectId``: duplicate document ids sharing one objectId, whether the copies
agree in content, genuine co-issued rules vs. component/parent catch-all-docket
pairs, the letters segment in some document ids, and same-agency id repeats.

SD-17: a receipt claimed a regulations-gov-dockets duplicate-identity count
measured once by a throwaway script whose output existed only in a chat log --
unre-derivable with any committed tool. ``--profile dockets`` runs the same
duplicate-identity question (which sourceRecordIds appear in more than one
release, and which objectIds carry more than one sourceRecordId) over the
regulations-gov-dockets selector, so that count becomes re-derivable too. Two
analyses stay document-only because they are not analogous, not narrower
versions of the same question: the id-grammar letters-segment census keys on
the document-id shape ``<docket>-<docSeq>-<LETTERS>-<docSeq>``, which docket
ids (identical to the docket itself, e.g. ``EPA-2020-0001``) never carry; and
the co-issued-vs-parent/component split reads a document's own ``docketId``
attribute to tell a record's identity apart from the docket it belongs to --
dockets have no such attribute, because a docket record's id *is* the docket.
The ``suspects`` narrowing (``frDocNum``/``pageCount`` disagreement) is the
same story: neither field exists on a docket record. All three appear in the
dockets report as a ``*NotApplicable`` sibling naming why, rather than being
silently dropped or forced onto a shape they do not fit. Content comparison
still runs for dockets, on the nearest available fields: see
``DOCKET_IDENTITY_FIELDS``.

Every count below states its own population as a sibling field -- one of the
six original scripts' outputs was misread as a rate over the whole corpus when
it was a rate over a filtered subset, and that error nearly reached a
decision-maker. All counts are over input RECORDS read via
``SourceNativeReleaseReader.iter_records()``, not built catalog items: a
catalog build's dispositions can drop or transform records, so these numbers
will not equal catalog item counts. One run scans exactly one profile (the
release list is filtered to it before anything else runs) and the report's
``scope.profileConsidered`` names it, so a report never blends counts from a
selector it did not scan.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rulespec_artifacts import LocalMemberSource

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.source_native import SourceNativeReleaseReader
from spicy_docs.source_native_profiles import REGULATIONS_GOV_DOCKET_PROFILE, REGULATIONS_GOV_DOCUMENT_PROFILE
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

DOCUMENTS_PROFILE_NAME = "regulations-gov-documents"
DOCKETS_PROFILE_NAME = "regulations-gov-dockets"
CATCH_ALL_DOCKET_SUFFIX = "_FRDOC_0001"
DOCUMENT_IDENTITY_FIELDS = ("title", "pageCount", "frDocNum", "documentType", "postedDate")
# Dockets carry no pageCount, frDocNum, documentType, or postedDate (see
# DOCKET_ATTRIBUTE_FIELDS in regulations_gov_source_native.py). title and
# docketType/modifyDate are the direct analogs of documentType/postedDate;
# shortTitle and dkAbstract are the nearest available content signals
# standing in for the two fields that have no docket counterpart.
DOCKET_IDENTITY_FIELDS = ("title", "shortTitle", "dkAbstract", "docketType", "modifyDate")
# EPA-HQ-OW-2025-0322-DRAFT-29781 -> ... docketSeq(0322) DRAFT docSeq(29781): a
# letters segment between the trailing <digits>-<LETTERS>-<digits>. Document
# ids only -- a docket id ends at the docket itself and never carries this tail.
TAIL_SEGMENT_PATTERN = re.compile(r"-(\d+)-([A-Za-z][A-Za-z0-9]*)-(\d+)$")
_EXAMPLE_CAP = 8


@dataclass(frozen=True)
class _ProfileConfig:
    """Everything that differs between the documents and dockets selectors."""

    profile_name: str
    source_native_profile: SourceNativeProfile
    release_root_prefix: str
    scanned_label: str
    identity_fields: tuple[str, ...]
    repeats_key: str
    other_profile_example: str
    # A document's own docketId attribute distinguishes its identity from the
    # docket it belongs to; a docket record has no such attribute (its id IS
    # the docket), so the catch-all-membership total and the co-issued split
    # -- both of which read that attribute -- are only computed when this is True.
    docket_attribute_applicable: bool
    id_grammar_applicable: bool
    suspects_applicable: bool


_PROFILE_CONFIGS: dict[str, _ProfileConfig] = {
    "documents": _ProfileConfig(
        profile_name=DOCUMENTS_PROFILE_NAME,
        source_native_profile=REGULATIONS_GOV_DOCUMENT_PROFILE,
        release_root_prefix="regs-documents-",
        scanned_label="documentsScanned",
        identity_fields=DOCUMENT_IDENTITY_FIELDS,
        repeats_key="documentIdRepeatsWithinAgency",
        other_profile_example=DOCKETS_PROFILE_NAME,
        docket_attribute_applicable=True,
        id_grammar_applicable=True,
        suspects_applicable=True,
    ),
    "dockets": _ProfileConfig(
        profile_name=DOCKETS_PROFILE_NAME,
        source_native_profile=REGULATIONS_GOV_DOCKET_PROFILE,
        release_root_prefix="regs-dockets-",
        scanned_label="docketsScanned",
        identity_fields=DOCKET_IDENTITY_FIELDS,
        repeats_key="docketIdRepeatsWithinAgency",
        other_profile_example=DOCUMENTS_PROFILE_NAME,
        docket_attribute_applicable=False,
        id_grammar_applicable=False,
        suspects_applicable=False,
    ),
}


def _normalized_title(value: object) -> str:
    return value.strip().lower().replace("–", "-") if isinstance(value, str) else ""


def _identity_signature(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[object, ...]:
    return tuple(_normalized_title(row["title"]) if f == "title" else row[f] for f in fields)


def _is_catch_all(docket: str) -> bool:
    return docket.endswith(CATCH_ALL_DOCKET_SUFFIX)


def _examples(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [{"objectId": oid, "rows": rows} for oid, rows in list(groups.items())[:_EXAMPLE_CAP]]


def _scan(releases: list[list[str]], store: LocalSourceNativeBlobStore, config: _ProfileConfig) -> dict[str, Any]:
    """Make the single admitted pass over every release of ``config``'s profile and accumulate raw tallies."""
    considered = [r for r in releases if r[2] == config.profile_name]
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
            profile=config.source_native_profile,
            expected_pin=None,
            accepted_verifier_implementation_ids=frozenset({receipt["verifierImplementationId"]}),
        )
        if reader.pin.artifact_digest != artifact_digest:
            raise SystemExit(
                f"artifact digest mismatch for {root}: input list says {artifact_digest}, "
                f"admitted release is {reader.pin.artifact_digest}"
            )
        agency = root.name.removeprefix(config.release_root_prefix)
        for rec in reader.iter_records():
            attrs = rec["record"]["data"]["attributes"]
            record_id = rec["sourceRecordId"]
            total += 1
            docket: str | None = None
            if config.docket_attribute_applicable:
                docket = attrs.get("docketId") or ""
                frdoc += _is_catch_all(docket)
            repeats_within_agency += record_id in ids_per_agency[agency]
            ids_per_agency[agency].add(record_id)
            object_id = attrs.get("objectId")
            if object_id:
                row = {f: attrs.get(f) for f in config.identity_fields} | {"agency": agency, "id": record_id}
                if docket is not None:
                    row["docket"] = docket
                by_object[object_id].append(row)
            if config.id_grammar_applicable:
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


def _report(scan: dict[str, Any], config: _ProfileConfig) -> dict[str, Any]:
    """Turn the raw tallies from :func:`_scan` into the labelled report for ``config``'s profile."""
    by_object: dict[str, list[dict[str, Any]]] = scan["by_object"]
    duplicate = {oid: rows for oid, rows in by_object.items() if len({r["id"] for r in rows}) > 1}
    repeated_id = {oid: rows for oid, rows in duplicate.items() if len(rows) > len({r["id"] for r in rows})}
    same_agency = {oid: rows for oid, rows in duplicate.items() if len({r["agency"] for r in rows}) == 1}
    cross_agency = {oid: rows for oid, rows in duplicate.items() if oid not in same_agency}

    agree: dict[str, list[dict[str, Any]]] = {}
    disagree: dict[str, list[dict[str, Any]]] = {}
    field_disagreement = dict.fromkeys(config.identity_fields, 0)
    for oid, rows in duplicate.items():
        if len({_identity_signature(r, config.identity_fields) for r in rows}) == 1:
            agree[oid] = rows
            continue
        disagree[oid] = rows
        for field in config.identity_fields:
            values = {_normalized_title(r["title"]) if field == "title" else r[field] for r in rows}
            field_disagreement[field] += len(values) > 1

    result: dict[str, Any] = {
        "scope": {
            "unitOfCount": (
                "input records read via SourceNativeReleaseReader.iter_records(), not built catalog "
                "items -- a catalog build's dispositions may drop or transform records, so these "
                "counts do not equal catalog item counts"
            ),
            "profileConsidered": config.profile_name,
            "releasesConsidered": scan["releasesConsidered"],
            "releasesSkipped": scan["releasesSkipped"],
            "releasesSkippedPopulation": (
                f"entries in the input release list whose profile is not '{config.profile_name}' "
                f"(for example federal-register or {config.other_profile_example}); no count below "
                "includes them"
            ),
        },
        "totals": {
            config.scanned_label: scan["total"],
            "distinctObjectIds": len(by_object),
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
        "contentComparison": {
            "population": f"duplicateGroups.count groups, compared on: {', '.join(config.identity_fields)}",
            "fieldsCompared": list(config.identity_fields),
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
        config.repeats_key: {
            "population": (
                f"counted while iterating {config.scanned_label} records grouped by the agency each "
                "record's own release was read under; a repeat is the same sourceRecordId observed "
                "more than once inside one agency's own release stream"
            ),
            "count": scan["repeats_within_agency"],
        },
    }

    three_or_more_rows = sum(len(rows) > 2 for rows in cross_agency.values())
    cross_agency_breakdown: dict[str, Any] = {
        "population": "of duplicateGroups.crossAgency.count",
        "withThreeOrMoreObservationRows": three_or_more_rows,
    }
    if config.docket_attribute_applicable:
        co_issued: dict[str, list[dict[str, Any]]] = {}
        single_real_docket: dict[str, list[dict[str, Any]]] = {}
        for oid, rows in cross_agency.items():
            real_rows = [r for r in rows if not _is_catch_all(r["docket"])]
            target = co_issued if len({r["agency"] for r in real_rows}) > 1 else single_real_docket
            target[oid] = rows
        cross_agency_breakdown["coIssued"] = {
            "population": (
                "cross-agency groups with two or more non-catch-all (real) dockets held by "
                "different agencies -- genuine co-issued rules"
            ),
            "count": len(co_issued),
            "examples": _examples(co_issued),
        }
        cross_agency_breakdown["singleRealDocket"] = {
            "population": (
                "cross-agency groups whose non-catch-all dockets belong to only one agency "
                "(parent/component catch-all-docket shape, not a genuine co-issued rule)"
            ),
            "count": len(single_real_docket),
        }
    else:
        cross_agency_breakdown["coIssuedAndSingleRealDocketNotApplicable"] = (
            "this split reads each row's own docketId attribute to tell a record's identity apart "
            "from the docket it belongs to; a docket record has no such attribute -- its id IS the "
            "docket -- so the split is not computed for this profile"
        )
    result["crossAgencyBreakdown"] = cross_agency_breakdown

    if config.docket_attribute_applicable:
        result["totals"]["documentsInFrdocCatchAllDockets"] = scan["frdoc"]
        result["totals"]["documentsInFrdocCatchAllDocketsPopulation"] = (
            f"of {config.scanned_label}, count whose docketId ends with '{CATCH_ALL_DOCKET_SUFFIX}'"
        )
    else:
        result["totals"]["catchAllDocketMembershipNotApplicable"] = (
            "dockets have no docketId attribute of their own -- a docket's own id IS the docket -- so "
            "membership in a catch-all docket is not computed for this profile"
        )

    if config.suspects_applicable:
        suspects = {
            oid: rows
            for oid, rows in duplicate.items()
            if len({r["frDocNum"] for r in rows}) > 1 or len({r["pageCount"] for r in rows}) > 1
        }
        suspects_all_fr_doc_num_null = sum(1 for rows in suspects.values() if all(r["frDocNum"] is None for r in rows))
        result["suspects"] = {
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
        }
    else:
        result["suspectsNotApplicable"] = (
            "suspects narrows on frDocNum and pageCount specifically; a docket record carries "
            "neither field, so this subset is not computed for this profile"
        )

    if config.id_grammar_applicable:
        segment_counts: Counter[str] = scan["segment_counts"]
        segment_agencies: dict[str, set[str]] = scan["segment_agencies"]
        result["idGrammar"] = {
            "population": f"all {config.scanned_label} records' sourceRecordId strings",
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
        }
    else:
        result["idGrammarNotApplicable"] = (
            "the letters-segment pattern keys on the document-id shape "
            f"'{TAIL_SEGMENT_PATTERN.pattern}' (a docket/document-sequence pair around a letters "
            "segment); a docket id ends at the docket itself and never carries that trailing shape, "
            "so this census is not computed for this profile"
        )

    return result


def census(release_list: Path, blob_store: Path, profile: str = "documents") -> dict[str, Any]:
    releases = json.loads(release_list.read_text())
    store = LocalSourceNativeBlobStore(blob_store, create=False)
    config = _PROFILE_CONFIGS[profile]
    return _report(_scan(releases, store, config), config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--releases", type=Path, required=True, help="JSON [root, artifactDigest, profile] triples")
    parser.add_argument("--blob-store", type=Path, required=True, help="Explicit persistent blob store")
    parser.add_argument(
        "--profile",
        choices=sorted(_PROFILE_CONFIGS),
        default="documents",
        help="which regulations.gov selector to census (default: documents)",
    )
    args = parser.parse_args(argv)
    print(json.dumps(census(args.releases, args.blob_store, args.profile), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
