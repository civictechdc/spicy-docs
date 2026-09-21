#!/usr/bin/env python3
"""Census the multi-observation record identities in one published release.

``iter_records()`` yields only the winner; this replays the accepted traversal's
acquisition-pages evidence to recover every discarded observation too. For the
federal-register profile it also answers, as named fields rather than
re-derived prose, what a sibling identity-scheme decision needs: number/date
uniqueness, legacy/modern shape collisions, modern-form reuse across dates,
letter-prefixed numbers that only collide once stripped, and an integrity
check on the X-family's self-encoded date.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from rulespec_artifacts import ArtifactPin, LocalMemberSource

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.source_native import SourceNativeReleaseReader
from spicy_docs.source_native.profiles import (
    FEDERAL_REGISTER_PROFILE,
    REGULATIONS_GOV_COMMENT_PROFILE,
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.source_native.regulations_gov import (
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    comment_source_issued_version,
    source_issued_version,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

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
_EXAMPLE_CAP = 20

# Measured 2026-09-02: legacy NN- runs 1994 through 2009-08-19, modern YYYY- starts 2010-01-06, so
# membership by *form* (below) differs from membership by year. LEGACY is wider than "NN-" alone
# (2-4 digit year, short suffix) so an early-2010 number with a still-short sequence is checked
# against it too. Both patterns are reported in the output so a reader can check the definition.
MODERN_NUMBER_PATTERN = re.compile(r"^\d{4}-\d+$")
LEGACY_NUMBER_PATTERN = re.compile(r"^\d{2,4}-[0-9A-Za-z]{1,4}$")
# X94-11209 is well-formed-legacy once its leading letter is stripped; group(1) is that stripped form.
LETTER_PREFIXED_LEGACY_PATTERN = re.compile(r"^[A-Za-z](\d{2}-[0-9A-Za-z]+)$")
# X##-<tail> encodes YY-{seq}{MM}{DD} (X94-10503 is 1994-05-03; X05-10916 is 2005-09-16, verified
# live). The date is the tail's LAST four digits and the sequence is whatever precedes it, so the
# tail is matched by width range and read right-anchored: a fixed five-digit pattern with
# left-anchored slicing silently excluded the six-digit tails and misread any longer one.
X_FORM_PATTERN = re.compile(r"^X(\d{2})-(\d{5,7})$")


def _federal_register_findings(date_digests: dict[str, dict[str, list[str]]]) -> dict[str, object]:
    """Report the number/date identity-scheme evidence a sibling decision needs."""
    same_number_different_date = differing_digest_pairs = identical_digest_redundant = 0
    letter_total = letter_differing = letter_same = 0
    modern_form_collisions: list[dict[str, object]] = []
    legacy_and_modern: list[str] = []
    x_form_mismatches: list[dict[str, object]] = []
    letter_same_examples: list[dict[str, object]] = []
    for number, by_date in sorted(date_digests.items()):
        dates = sorted(by_date)
        if len(dates) > 1:
            same_number_different_date += 1
            if MODERN_NUMBER_PATTERN.fullmatch(number):
                modern_form_collisions.append({"recordId": number, "dates": dates})
        for digests_seen in by_date.values():
            distinct = len(set(digests_seen))
            if distinct == 1 and len(digests_seen) > 1:
                identical_digest_redundant += len(digests_seen) - 1
            elif distinct > 1:
                differing_digest_pairs += 1  # unreachable in any release that published
        if MODERN_NUMBER_PATTERN.fullmatch(number) and LEGACY_NUMBER_PATTERN.fullmatch(number):
            legacy_and_modern.append(number)
        x_match = X_FORM_PATTERN.fullmatch(number)
        if x_match is not None:
            year_prefix = int(x_match.group(1))
            year = year_prefix + (1900 if year_prefix >= 50 else 2000)
            suffix = x_match.group(2)
            encoded = f"{year:04d}-{suffix[-4:-2]}-{suffix[-2:]}"
            if encoded not in by_date:
                x_form_mismatches.append({"recordId": number, "encodedDate": encoded, "publicationDates": dates})
        letter_match = LETTER_PREFIXED_LEGACY_PATTERN.fullmatch(number)
        stripped = letter_match.group(1) if letter_match is not None else None
        if stripped is not None and stripped in date_digests:
            letter_total += 1
            shared = sorted(set(by_date) & set(date_digests[stripped]))
            if shared:
                letter_same += 1
                if len(letter_same_examples) < _EXAMPLE_CAP:
                    letter_same_examples.append({"letterForm": number, "strippedForm": stripped, "dates": shared})
            else:
                letter_differing += 1

    return {
        "numberAndDateUniquelyIdentify": differing_digest_pairs == 0,
        "numberAndDateUniquelyIdentifyBasis": (
            "the collapse groups observations by (document_number, publication_date) and refuses "
            "to publish a pair whose canonical record digests differ, so a release that published "
            "is itself the proof the pair uniquely identifies one record for every pair it covers"
        ),
        "sameNumberDifferentDateCount": same_number_different_date,
        "sameNumberSameDateIdenticalDigestCount": identical_digest_redundant,
        "sameNumberSameDateDifferingDigestCount": differing_digest_pairs,
        "collisionCountingBasis": (
            "numberAndDate*, modernFormCollisions, and legacyFormAlsoParsesAsModern are all "
            "counted over unnormalized document numbers, no prefix or case folding applied"
        ),
        "legacyFormAlsoParsesAsModern": bool(legacy_and_modern),
        "legacyFormAlsoParsesAsModernCount": len(legacy_and_modern),
        "legacyFormAlsoParsesAsModernExamples": legacy_and_modern[:_EXAMPLE_CAP],
        "legacyPattern": LEGACY_NUMBER_PATTERN.pattern,
        "modernPattern": MODERN_NUMBER_PATTERN.pattern,
        "modernFormCollisions": modern_form_collisions,
        "modernFormCollisionCount": len(modern_form_collisions),
        "modernFormCollisionsBasis": (
            "membership is the number's form (fullmatches the modern YYYY-NNNNN pattern), not the "
            "year of its dates: legacy NN- runs 1994 through 2009-08-19 and modern YYYY- starts "
            "2010-01-06, so a year-named field would read as covering 2000-2009, which are legacy-form"
        ),
        "letterPrefixStripCollisions": {
            "totalCount": letter_total,
            "differingDateCount": letter_differing,
            "sameDateCount": letter_same,
            "sameDateExamples": letter_same_examples,
            "basis": (
                "computed here, over this release's own numbers, by stripping each letter-prefixed "
                "legacy-shaped number's leading letter and checking whether the stripped form is a "
                "distinct number in this release; a shared date means no date qualifier can "
                "disambiguate the pair. A pinned reference corpus measured this same artifact "
                "elsewhere as 2,382 total (2,372 differing-date, 10 same-date) -- these three counts "
                "are computed here, over this release, not copied from that corpus. Raw values are "
                "cleanly disjoint, so the artifact only appears if someone normalizes"
            ),
        },
        "xFormDateEncodingMismatches": x_form_mismatches,
        "xFormDateEncodingMismatchCount": len(x_form_mismatches),
        "xFormPattern": X_FORM_PATTERN.pattern,
    }


def census(args: argparse.Namespace) -> dict[str, object]:
    """Replay one release's acquisition evidence into multi-observation and discarded-observation counts."""
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
    is_federal_register = args.profile == "federal-register"
    date_digests: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
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
                identity = discovered["sourceRecordId"]
                observations[identity].append(pair)
                digests[identity].add(discovered["recordDigest"])
                # SD-24: sourceRecordId is composite (document_number,
                # publication_date) and never repeats across dates, so the
                # number/date findings below key on the classified record's
                # own document_number instead -- independent of whatever
                # shape sourceRecordId happens to have, exactly as this
                # section's own numbers (not identities) always meant.
                if is_federal_register and pair[0] is not None:
                    date_digests[str(classified["document_number"])][pair[0]].append(discovered["recordDigest"])
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
        if is_federal_register:
            entry["post2000"] = any(raw is not None and raw > "1999-12-31" for raw, _ in seen)
        multi_observation.append(entry)
    result: dict[str, object] = {
        "profile": args.profile,
        "multiObservationRecords": multi_observation,
        "totals": {
            "records": len(observations),
            "multiObservationIds": len(multi_observation),
            "discardedObservations": discarded,
        },
    }
    if is_federal_register:
        result.update(_federal_register_findings(date_digests))
        scope = json.loads((args.release / "records/scopes.jsonl").read_text().splitlines()[0])
        result["coverage"] = {
            "queryScope": scope["fields"],
            # SD-24: distinct document_numbers, not distinct identities --
            # composite sourceRecordId means len(observations) now counts
            # (number, date) pairs, which overcounts a number reused across
            # dates. date_digests is keyed by document_number (see above).
            "distinctNumberCount": len(date_digests),
            "caveat": (
                "this census describes the crawled Federal Register (1994 onward, the API's own "
                "coverage) and is not evidence about the printed Register before that"
            ),
            "eFamilySpilloverNote": (
                "a year-coded family can legitimately spill into the following January "
                "(E8-30793 was published 2009-01-02, 74 FR 130) -- do not mint an off-by-one-year "
                "identity from the code alone"
            ),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    """Print the census JSON for the selected release and profile."""
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
