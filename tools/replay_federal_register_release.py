#!/usr/bin/env python3
"""Republish one Federal Register source-native release from its own retained
acquisition evidence -- no network access, ever.

WHY (SD-25). ``b590d86`` changed Federal Register identity from
``document_number`` alone to the composite ``(document_number,
publication_date)``. The release already published at
``~/Work/corpora/supply-2026-09-02/releases/fr-full-1994-2026`` was built
under the old identity and silently evicted 483 observations across 474
reused document numbers -- real documents, including ``00-111``'s
2000-01-14 rule, discarded because a later same-number filing collapsed
onto it. Republishing under the current :data:`FEDERAL_REGISTER_PROFILE`
recovers them as records. A fresh crawl cannot be used to measure this: the
live Federal Register API returns *today's* corpus, so "record count rises
by exactly 483" would measure the corpus moving, not the code. The only way
to isolate the identity change is to replay the exact bytes the original
acquisition already retained.

THE SEAM. ``iter_federal_register_pages(fetch, *, query_scope, ...)`` takes
``FederalRegisterFetch = Callable[[str], bytes]`` -- a URL in, response
bytes out. The published release records, on each acquisition-page row,
both ``requestKey`` (the exact URL requested) and ``evidenceBlobRef`` (the
digest of the retained response). Replaying is therefore a pure function of
that release's own evidence: build ``{requestKey: evidenceBlobRef}`` once
(:func:`build_request_map`), resolve each hit through the blob store lazily
inside the fetch closure (:func:`build_replay_fetch`) rather than loading
every retained response into memory up front, and hand that fetch to the
unmodified production pipeline
(``SourceNativeReleasePublisher(FEDERAL_REGISTER_PROFILE).publish(...)``).

NO FALLBACK, BY CONSTRUCTION. A ``fetch`` call for a URL the mapping does
not carry raises :class:`ReplayEvidenceMissingError` immediately, naming the
URL -- it never returns anything and there is no other code path in this
module that could reach a transport. This module imports no HTTP client:
no ``httpx``, no ``urllib.request``, no ``socket``, no ``ssl``, no
``spicy_docs.sources.zyte``, no ``spicy_docs.source_native_cli`` (which
wires up the live fetchers) -- measured by importing this module alone and
checking ``sys.modules`` for exactly those names; none appear. That
measurement is *why* :data:`FEDERAL_REGISTER_PROFILE` below is built here
from :mod:`spicy_docs.federal_register_source_native` directly rather than
imported from ``spicy_docs.source_native_profiles`` (which is otherwise the
canonical place a caller gets this object, e.g.
``spicy_docs.source_native_cli``): that module unconditionally also builds
the GAO product-page profile, which imports ``spicy_docs.sources.zyte``,
which imports ``urllib.request`` -- so importing it, even only for the one
name needed here, would put a transport-capable module into this process
that a grep of this file alone could not rule out. The fields below are
copied verbatim from ``source_native_profiles.FEDERAL_REGISTER_PROFILE``
(duplicated, not re-derived: every value still comes from
``federal_register_source_native``'s own public functions and constants,
which a test below pins equal to the real profile field for field). The
better long-term fix -- lazily importing GAO inside
``source_native_profiles.py``, the same way ``source_native_cli.py``
already lazily imports ``public_table``'s pyarrow dependency -- is outside
this tool's writable scope.

THE QUERY SCOPE is read from the source release itself -- its sole
``source-native-scopes`` member, on disk ``records/scopes.jsonl`` -- never
taken as a CLI argument (see :func:`_read_query_scope`). A replay under a
scope the operator merely believes matches the original is not a replay; a
scope read back from the release is byte-identical by construction.

SCALE NOTE. :func:`build_request_map` reads every row of every
``source-acquisition-ledger``-role member -- that role covers two row
shapes, acquisition-page rows (``requestKey``, ``evidenceBlobRef``, ...) and
acquisition-ledger rows (``sourceRecordId``, ``observationRef``,
``failure``, no ``requestKey``) -- and keeps only the former, identified by
``requestKey``'s presence rather than by the manifest's own
``partitionKind`` label, so it stays correct even if that partitioning
detail changes. That is one linear, streamed pass over every retained
ledger row (bounded per-line memory; nothing is held in aggregate but the
small ``{requestKey: evidenceBlobRef}`` map), not just the page rows -- named
here because the acquisition-ledger row population is normally much larger
than the acquisition-page row population.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rulespec_artifacts import (
    LocalMemberSource,
    MemberDescriptor,
    MemberSource,
    Producer,
    VerifiedArtifact,
    admit_artifact,
    iter_member_descriptors,
)

from spicy_docs import federal_register_source_native as federal_register
from spicy_docs.source_native import (
    CURRENT_PRODUCER_PRODUCT,
    ROLE_LEDGER,
    ROLE_SCOPES,
    VERIFIER_ID,
    VERIFIER_VERSION,
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
    verify_source_native_admission,
)
from spicy_docs.source_native_profile import SourceNativeProfile
from spicy_docs.source_native_store import LocalSourceNativeBlobStore

#: Publication receipt path, relative to a release root. Not imported from
#: ``spicy_docs.source_native`` (its ``RECEIPT_KEY`` is private to that
#: module) -- mirrors the same hardcoded-path convention already used by
#: ``tools/fr_discarded_distinctness.py``'s ``RECEIPT_PATH``.
_RECEIPT_PATH: tuple[str, str] = ("receipts", "publication.json")


#: Mirrors ``source_native_profiles._federal_register_record_scope`` (private
#: to that module). See the module docstring's NO FALLBACK section for why
#: this is copied rather than imported from ``source_native_profiles``.
def _federal_register_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    del query_scope
    if (
        not isinstance(page_window, tuple)
        or len(page_window) != 2
        or not all(isinstance(value, date) for value in page_window)
    ):
        raise federal_register.FederalRegisterSourceError("Federal Register page lacks a validated date window")
    typed_window = cast(tuple[date, date], page_window)
    record_date = date.fromisoformat(str(record["publication_date"]))
    if not typed_window[0] <= record_date <= typed_window[1]:
        raise federal_register.FederalRegisterSourceError("Federal Register result falls outside its date window")


#: Mirrors ``spicy_docs.source_native_profiles.FEDERAL_REGISTER_PROFILE``
#: field for field. Not imported from there: see the module docstring's NO
#: FALLBACK section. ``tests/test_replay_federal_register_release.py`` pins
#: this against the real profile so the two cannot silently drift apart.
FEDERAL_REGISTER_ACQUISITION_POLICY_ID = "urn:spicy-regs:acquisition:federal-register-paginated"
FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION = "1.1"
FEDERAL_REGISTER_SOURCE_SCHEMA_KEY = "schemas/federal-register-document-1.0.schema.json"
FEDERAL_REGISTER_PROFILE = SourceNativeProfile(
    name="Federal Register",
    source_system_id=federal_register.SOURCE_SYSTEM_ID,
    source_system_version=federal_register.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=FEDERAL_REGISTER_ACQUISITION_POLICY_ID,
    acquisition_policy_version=FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION,
    scope_id=federal_register.SCOPE_ID,
    source_schema_key=FEDERAL_REGISTER_SOURCE_SCHEMA_KEY,
    source_schema=federal_register.FEDERAL_REGISTER_DOCUMENT_SCHEMA,
    record_stem="federal-register",
    max_traversals=federal_register.MAX_RECONCILIATION_TRAVERSALS,
    source_state_scope="observed-crawl",
    traversal_acceptance="stable-consecutive-traversals",
    acquisition_policy=federal_register.federal_register_acquisition_policy,
    validate_query_scope=federal_register.federal_register_query_scope,
    parse_page_response=federal_register.parse_page_response,
    next_page=federal_register.federal_register_next_page_url,
    traversal_check=federal_register.FederalRegisterTraversalCheck,
    classify_record=federal_register.classify_document,
    wrap_record=federal_register.source_record,
    record_digest=federal_register.source_record_digest,
    rendition_rows=federal_register.rendition_rows,
    source_schema_declaration=federal_register.source_schema_declaration,
    source_schema_digest=federal_register.source_schema_digest,
    validate_record_scope=_federal_register_record_scope,
    records_included=federal_register.federal_register_records_included,
    acquisition_check=federal_register.FederalRegisterAcquisitionCheck,
    page_window=federal_register.federal_register_request_window,
    observation_version=federal_register.federal_register_observation_version,
    refuse_equal_observation_versions=False,
)
iter_federal_register_pages = federal_register.iter_federal_register_pages


class ReplayEvidenceMissingError(SourceNativeReleaseError):
    """A replay fetch asked for a request the source release never retained.

    Raised instead of returning anything, and instead of reaching for any
    live transport -- there is none in this module to reach for.
    """


@dataclass(slots=True)
class ReplayFetchStats:
    """Counts distinguishing distinct URLs served from total fetch calls.

    ``iter_federal_register_pages`` defaults to ``traversals=2``, so the
    same URL is requested again in the second traversal; ``call_count``
    counts every call (repeats included), ``served_urls`` counts each
    distinct URL once.
    """

    call_count: int = 0
    served_urls: set[str] = field(default_factory=set)


def _require_separate_paths(left: Path, right: Path, *, labels: tuple[str, str]) -> None:
    """Refuse two CLI paths that alias or nest one another.

    Mirrors ``spicy_docs.source_native_cli._require_separate_paths`` -- that
    helper is private to a module this tool's writable scope excludes, so
    the same small check is reproduced here rather than imported.
    """

    resolved_left = Path(left).absolute().resolve(strict=False)
    resolved_right = Path(right).absolute().resolve(strict=False)
    if (
        resolved_left == resolved_right
        or resolved_left.is_relative_to(resolved_right)
        or resolved_right.is_relative_to(resolved_left)
    ):
        raise SourceNativeReleaseError(f"{labels[0]} and {labels[1]} must not overlap")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _instant(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise SourceNativeReleaseError("replay clock must return a timezone-aware instant")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _admit_source_release(
    release_root: Path,
    blob_store: Path,
) -> tuple[MemberSource, LocalSourceNativeBlobStore, VerifiedArtifact, list[MemberDescriptor]]:
    """Cheap-tier admission of the source release: structural and bounded
    receipt/root agreement, the same check ``SourceNativeReleaseReader`` runs
    on open. Not the expensive full acquisition replay
    (``verify_source_native_release``) -- that recomputes the *original*
    acquisition from evidence, which is redundant work here: this tool is
    about to do exactly that recomputation itself, for the *new* release,
    through the ordinary build gate inside ``SourceNativeReleasePublisher.publish``.
    """

    source = LocalMemberSource(release_root)
    blob_source = LocalSourceNativeBlobStore(blob_store, create=False)
    artifact = admit_artifact(
        source,
        blob_source=blob_source,
        semantic_verifier=lambda candidate, member_source: verify_source_native_admission(
            candidate,
            member_source,
            profile=FEDERAL_REGISTER_PROFILE,
            blob_source=blob_source,
        ),
    )
    members = list(iter_member_descriptors(artifact, source))
    return source, blob_source, artifact, members


def _read_query_scope(members: Sequence[MemberDescriptor], source: MemberSource) -> dict[str, Any]:
    """The source release's own recorded query scope -- read from its sole
    ``source-native-scopes`` member (on disk: ``records/scopes.jsonl``,
    ``spicy_docs.source_native.SCOPES_KEY``), located here by role rather
    than by a hardcoded path so this stays correct even if that path
    changes. Never taken as a CLI argument: a replay under any other scope
    would drive ``iter_federal_register_pages`` over a different date
    window than the one this evidence was acquired for, comparing unlike
    populations rather than replaying the one that exists.
    """

    scope_members = [member for member in members if member.role == ROLE_SCOPES]
    if len(scope_members) != 1 or scope_members[0].object_key is None:
        raise SourceNativeReleaseError("source release must carry exactly one local source-native-scopes member")
    with source.open(scope_members[0].object_key) as stream:
        raw = stream.read()
    rows = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != 1:
        raise SourceNativeReleaseError("source release query-scope record must carry exactly one row")
    scope_row = json.loads(rows[0])
    if (
        not isinstance(scope_row, Mapping)
        or scope_row.get("scopeId") != FEDERAL_REGISTER_PROFILE.scope_id
        or scope_row.get("sourceSystemId") != FEDERAL_REGISTER_PROFILE.source_system_id
        or not isinstance(scope_row.get("fields"), Mapping)
    ):
        raise SourceNativeReleaseError("source release query-scope record differs from the Federal Register profile")
    fields = dict(scope_row["fields"])
    canonical = dict(FEDERAL_REGISTER_PROFILE.validate_query_scope(fields))
    if canonical != fields:
        raise SourceNativeReleaseError("source release query scope is not canonical")
    return canonical


def _iter_ledger_rows(member: MemberDescriptor, blob_source: LocalSourceNativeBlobStore) -> Iterator[Mapping[str, Any]]:
    if member.blob_ref is None:
        raise SourceNativeReleaseError("source-acquisition-ledger member must use an external blobRef")
    with blob_source.open(member.blob_ref) as stream:
        for line in stream:
            if not line.strip():
                continue
            yield json.loads(line)


def _extract_request_map(
    members: Sequence[MemberDescriptor],
    blob_source: LocalSourceNativeBlobStore,
) -> tuple[dict[str, str], int]:
    """``{requestKey: evidenceBlobRef}`` plus the total acquisition-page row
    count (population: every row carrying ``requestKey``, across every
    ``source-acquisition-ledger`` member and every retained traversal -- a
    URL requested again in a later traversal contributes one row per
    traversal, so this total can exceed the distinct-key count of the
    returned mapping).
    """

    ledger_members = [member for member in members if member.role == ROLE_LEDGER]
    if not ledger_members:
        raise SourceNativeReleaseError("source release carries no source-acquisition-ledger members")
    request_map: dict[str, str] = {}
    page_row_count = 0
    for member in ledger_members:
        for row in _iter_ledger_rows(member, blob_source):
            if "requestKey" not in row:
                continue  # an acquisition-ledger row (sourceRecordId/observationRef/failure), not a page row
            page_row_count += 1
            request_key = row["requestKey"]
            evidence_ref = row.get("evidenceBlobRef")
            if not isinstance(request_key, str) or not request_key:
                raise SourceNativeReleaseError("acquisition-page row carries an invalid requestKey")
            if not isinstance(evidence_ref, str) or not evidence_ref:
                raise SourceNativeReleaseError(f"acquisition-page row for {request_key!r} carries no evidenceBlobRef")
            previous = request_map.get(request_key)
            if previous is not None and previous != evidence_ref:
                raise SourceNativeReleaseError(
                    f"source release records two different evidence bodies for one requestKey: {request_key!r}"
                )
            request_map[request_key] = evidence_ref
    return request_map, page_row_count


def build_request_map(release_root: Path, blob_store: Path) -> tuple[dict[str, str], int]:
    """Admit ``release_root`` and return its ``{requestKey: evidenceBlobRef}``
    map and total acquisition-page row count. Public so a caller (or a test)
    can inspect exactly what the replay will serve without driving a full
    publish.
    """

    _source, resolved_blob_source, _artifact, members = _admit_source_release(Path(release_root), Path(blob_store))
    return _extract_request_map(members, resolved_blob_source)


def build_replay_fetch(
    request_map: Mapping[str, str],
    blob_source: LocalSourceNativeBlobStore,
) -> tuple[Callable[[str], bytes], ReplayFetchStats]:
    """One offline stand-in for ``FederalRegisterFetch``, and the counters it
    updates as it is called.

    A miss raises :class:`ReplayEvidenceMissingError` immediately, naming
    the URL, rather than returning anything or reaching for a transport --
    this module imports none. A hit resolves the retained evidence lazily,
    through the blob store, one response at a time -- not by holding every
    retained response in memory up front.
    """

    stats = ReplayFetchStats()

    def replay_fetch(url: str) -> bytes:
        stats.call_count += 1
        evidence_ref = request_map.get(url)
        if evidence_ref is None:
            raise ReplayEvidenceMissingError(
                f"no retained acquisition evidence for request {url!r}; the source release "
                "never recorded this requestKey, and this replay refuses to fetch it over the network"
            )
        stats.served_urls.add(url)
        with blob_source.open(evidence_ref) as stream:
            return stream.read()

    return replay_fetch, stats


def replay(
    *,
    release_root: Path,
    blob_store: Path,
    destination: Path,
    implementation_id: str,
    clock: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    """Republish one Federal Register source-native release from retained
    evidence only, and return the JSON-ready summary described in the module
    docstring."""

    release_root = Path(release_root)
    blob_store = Path(blob_store)
    destination = Path(destination)
    _require_separate_paths(release_root, blob_store, labels=("--release-root", "--blob-store"))
    _require_separate_paths(destination, blob_store, labels=("--destination", "--blob-store"))
    _require_separate_paths(destination, release_root, labels=("--destination", "--release-root"))
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to replace immutable release: {destination}")

    source, resolved_blob_source, source_artifact, members = _admit_source_release(release_root, blob_store)
    query_scope = _read_query_scope(members, source)
    request_map, source_page_row_count = _extract_request_map(members, resolved_blob_source)
    replay_fetch, stats = build_replay_fetch(request_map, resolved_blob_source)

    producer = Producer(
        product=CURRENT_PRODUCER_PRODUCT,
        implementation_id=implementation_id,
        verifier_id=VERIFIER_ID,
        verifier_version=VERIFIER_VERSION,
        verifier_implementation_id=implementation_id,
    )
    build = SourceNativeReleaseBuild(
        query_scope=query_scope,
        producer=producer,
        started_at=_instant(clock),
    )
    published = SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE,
        blob_store=resolved_blob_source,
        clock=clock,
    ).publish(
        iter_federal_register_pages(replay_fetch, query_scope=query_scope),
        build=build,
        destination=destination,
    )
    receipt = json.loads(destination.joinpath(*_RECEIPT_PATH).read_text(encoding="utf-8"))

    return {
        "sourceRelease": str(release_root),
        "sourceReleaseDigest": source_artifact.pin.artifact_digest,
        "sourceReleaseLogicalId": source_artifact.pin.logical_id,
        "queryScope": query_scope,
        "queryScopePopulation": "read verbatim from the source release's own records/scopes.jsonl member, never taken as an argument",
        "sourceDistinctRequestKeyCount": len(request_map),
        "sourceDistinctRequestKeyCountPopulation": (
            "distinct requestKey values across every acquisition-page row (identified by that row "
            "carrying requestKey) in every source-acquisition-ledger member of the source release"
        ),
        "sourcePageRowCount": source_page_row_count,
        "sourcePageRowCountPopulation": (
            "every acquisition-page row read; a requestKey the source release requested again in a "
            "later traversal contributes one row per traversal, so this can exceed the distinct count above"
        ),
        "replayFetchCallCount": stats.call_count,
        "replayFetchCallCountPopulation": "every call this run made to the replay fetch, including repeats across traversals",
        "replayDistinctRequestKeysServed": len(stats.served_urls),
        "replayDistinctRequestKeysServedPopulation": (
            "distinct URLs this run resolved bytes for from retained evidence during this publish"
        ),
        "distinctRequestKeysMatchSource": len(request_map) == len(stats.served_urls),
        "publishedRelease": str(published.root),
        "publishedReleaseDigest": published.artifact.pin.artifact_digest,
        "publishedReleaseLogicalId": published.artifact.pin.logical_id,
        "publishedRecordCount": receipt["publishedRecordCount"],
        "discardedObservationCount": receipt["discardedObservationCount"],
        "inputObservationCount": receipt["inputObservationCount"],
        "recordCountsPopulation": "read from the newly published release's own receipts/publication.json",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--release-root",
        type=Path,
        required=True,
        help="Source Federal Register release directory to replay (holds artifact.json, manifests/, "
        "receipts/, records/scopes.jsonl)",
    )
    parser.add_argument(
        "--blob-store",
        type=Path,
        required=True,
        help="Persistent content-addressed store holding the source release's retained evidence; also "
        "where the republished release's own payload blobs are written (already-present bytes, "
        "including reused evidence, are recognized and not rewritten)",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Root of the new release this replay publishes; must not already exist",
    )
    parser.add_argument(
        "--implementation-id",
        required=True,
        help="Producer/verifier implementation id for the republished release, e.g. "
        "git+file:///path/to/spicy-docs@<commit sha>",
    )
    args = parser.parse_args(argv)
    summary = replay(
        release_root=args.release_root,
        blob_store=args.blob_store,
        destination=args.destination,
        implementation_id=args.implementation_id,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
