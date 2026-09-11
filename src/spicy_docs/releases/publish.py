"""Stage, verify, and publish one immutable source-native release."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from rulespec_artifacts import (
    ROOT_OBJECT_KEY,
    LocalMemberSource,
    MemberDescriptor,
    MemberManifestReference,
    admit_artifact,
    build_artifact_root,
    canonical_json_bytes,
    describe_member_from_receipt,
    schema_bundle_digest,
)

from spicy_docs.releases.format import (
    _RECEIPT_SHAPE,
    FORMAT,
    FORMAT_VERSION,
    KIND,
    MANIFEST_KEY,
    PARTITION_BUCKET_COUNT,
    PARTITION_KINDS,
    PARTITION_LEDGER,
    PARTITION_PAGES,
    PARTITION_RECORDS,
    PARTITION_RENDITIONS,
    RECEIPT_KEY,
    RELEASE_SCHEMA_ID,
    RELEASE_SCHEMA_KEY,
    ROLE_RECEIPT,
    ROLE_RELEASE_SCHEMA,
    ROLE_SCHEMA,
    ROLE_SCOPES,
    SCOPES_KEY,
    PublishedSourceNativeRelease,
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    _instant,
    _now,
    _utc,
    installed_release_schema_bundle,
)
from spicy_docs.releases.indexing import (
    index_pages,
)
from spicy_docs.releases.observations import (
    _accepted_traversal,
    _full_ledger_rows,
    _page_rows,
    _policy_digest,
    _query_mappings,
    _query_renditions,
    _section_digest,
    _source_state_digest,
)
from spicy_docs.releases.partitions import (
    _ByteAccounting,
    _partition_policy,
    _PayloadPartition,
    _stage_partition,
)
from spicy_docs.releases.profile import (
    SourceNativePage,
    SourceNativeProfile,
)
from spicy_docs.releases.verify import (
    verify_source_native_release,
)
from spicy_docs.storage.blobs import SourceNativeBlobStore
from spicy_docs.storage.publication import publish_directory_once, write_bytes_once


class SourceNativeReleasePublisher:
    """Build one source release through injected source-specific semantics."""

    def __init__(
        self,
        profile: SourceNativeProfile,
        *,
        blob_store: SourceNativeBlobStore,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._profile = profile
        self._blob_store = blob_store
        self._clock = clock

    def publish(
        self,
        pages: Iterable[SourceNativePage],
        *,
        build: SourceNativeReleaseBuild,
        destination: Path,
    ) -> PublishedSourceNativeRelease:
        profile = self._profile
        canonical_scope = dict(profile.validate_query_scope(build.query_scope))
        if canonical_scope != dict(build.query_scope):
            raise SourceNativeReleaseError(f"{profile.name} query scope is not canonical")
        destination = Path(destination)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"refusing to replace immutable release: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".staging", dir=destination.parent))
        scratch = Path(tempfile.mkdtemp(prefix="source-native-index-", dir=destination.parent))
        accounting = _ByteAccounting()
        evidence_members: dict[str, MemberDescriptor] = {}
        try:
            connection = sqlite3.connect(scratch / "release.sqlite3")
            try:
                index_pages(
                    connection,
                    pages,
                    blob_store=self._blob_store,
                    accounting=accounting,
                    evidence_members=evidence_members,
                    query_scope=canonical_scope,
                    profile=profile,
                )
                traversal_count = int(connection.execute("SELECT count(DISTINCT traversal) FROM pages").fetchone()[0])
                accepted = _accepted_traversal(
                    connection,
                    traversal_count=traversal_count,
                    profile=profile,
                )
                return self._publish_indexed(
                    connection,
                    staging=staging,
                    scratch=scratch,
                    destination=destination,
                    build=build,
                    accepted_traversal=accepted,
                    traversal_count=traversal_count,
                    profile=profile,
                    blob_store=self._blob_store,
                    accounting=accounting,
                    evidence_descriptors=tuple(evidence_members[key] for key in sorted(evidence_members)),
                )
            finally:
                connection.close()
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            shutil.rmtree(staging, ignore_errors=True)

    def _publish_indexed(
        self,
        connection: sqlite3.Connection,
        *,
        staging: Path,
        scratch: Path,
        destination: Path,
        build: SourceNativeReleaseBuild,
        accepted_traversal: int,
        traversal_count: int,
        profile: SourceNativeProfile,
        blob_store: SourceNativeBlobStore,
        accounting: _ByteAccounting,
        evidence_descriptors: tuple[MemberDescriptor, ...],
    ) -> PublishedSourceNativeRelease:
        scopes = [
            {
                "fields": dict(build.query_scope),
                "scopeId": profile.scope_id,
                "scopeKind": "source-collection",
                "sourceSystemId": profile.source_system_id,
            }
        ]
        schema_declarations = [profile.source_schema_declaration()]
        record_query = "SELECT record_payload FROM observations "
        selected_record_query = record_query + "WHERE traversal = ? AND selected = 1 ORDER BY source_record_id"
        observation_query = (
            "SELECT record_payload FROM observations WHERE traversal = ? "
            "ORDER BY source_record_id, source_version IS NULL, source_version DESC"
        )
        published_record_count = int(
            connection.execute(
                "SELECT count(*) FROM observations WHERE traversal = ? AND selected = 1",
                (accepted_traversal,),
            ).fetchone()[0]
        )
        input_observation_count = int(
            connection.execute(
                "SELECT count(*) FROM observations WHERE traversal = ?",
                (accepted_traversal,),
            ).fetchone()[0]
        )
        failed_record_count = int(
            connection.execute(
                "SELECT count(*) FROM failures WHERE traversal = ?",
                (accepted_traversal,),
            ).fetchone()[0]
        )

        def records() -> Iterator[Mapping[str, Any]]:
            return _query_mappings(connection, selected_record_query, (accepted_traversal,))

        def observations() -> Iterator[Mapping[str, Any]]:
            return _query_mappings(connection, observation_query, (accepted_traversal,))

        def renditions() -> Iterator[Mapping[str, Any]]:
            return _query_renditions(connection, accepted_traversal)

        rendition_count = sum(1 for _ in renditions())
        release_schemas = installed_release_schema_bundle()
        page_count = int(connection.execute("SELECT count(*) FROM pages").fetchone()[0])
        accepted_page_count = int(
            connection.execute("SELECT count(*) FROM pages WHERE traversal = ?", (accepted_traversal,)).fetchone()[0]
        )
        partitions = _stage_indexed_partitions(
            connection,
            accepted_traversal=accepted_traversal,
            scratch=scratch,
            blob_store=blob_store,
            accounting=accounting,
        )
        partition_counts = {
            kind: sum(
                partition.member.record_count or 0 for partition in partitions if partition.partition_kind == kind
            )
            for kind in PARTITION_KINDS
        }
        if (
            partition_counts[PARTITION_RECORDS] != published_record_count
            or partition_counts[PARTITION_RENDITIONS] != rendition_count
            or partition_counts[PARTITION_LEDGER] != published_record_count + failed_record_count
            or partition_counts[PARTITION_PAGES] != page_count
        ):
            raise SourceNativeReleaseError("partitioned source-native accounting differs")

        schema_set_digest = _section_digest(
            "spicyregs-source-schema-set/1", "schemas", len(schema_declarations), schema_declarations
        )
        state_digest = _source_state_digest(
            (len(scopes), scopes),
            (len(schema_declarations), schema_declarations),
            (published_record_count, records()),
            (rendition_count, renditions()),
        )
        input_digest = _section_digest(
            "spicyregs-input-observations/1", "observations", input_observation_count, observations()
        )
        ledger_digest = _section_digest(
            "spicyregs-acquisition-ledger/1",
            "entries",
            published_record_count + failed_record_count,
            _full_ledger_rows(connection, accepted_traversal),
        )
        reconciliation_digest = _section_digest(
            "spicyregs-source-reconciliation/1",
            "pages",
            accepted_page_count,
            _page_rows(connection, accepted_traversal, accepted_only=True),
        )
        release_schema_digest = schema_bundle_digest(release_schemas)
        completed_at = _instant(self._clock)
        if _utc(completed_at, "completed_at") < _utc(build.started_at, "started_at"):
            raise SourceNativeReleaseError("publisher completion precedes acquisition start")
        spec = {
            "acquisitionPolicyDigest": _policy_digest(build, profile),
            "acquisitionPolicyId": profile.acquisition_policy_id,
            "acquisitionPolicyVersion": profile.acquisition_policy_version,
            "releaseSchemaDigest": release_schema_digest,
            "sourceNativeSchemaSetDigest": schema_set_digest,
            "sourceStateDigest": state_digest,
            "sourceStateScope": profile.source_state_scope,
            "sourceSystemId": profile.source_system_id,
            "sourceSystemVersion": profile.source_system_version,
        }
        receipt: dict[str, Any] = {
            "acquisitionEvidenceCount": len(evidence_descriptors),
            "acquisitionLedgerDigest": ledger_digest,
            "acquisitionPolicyDigest": _policy_digest(build, profile),
            "completedAt": completed_at,
            "deterministicFailureCount": failed_record_count,
            "discoveredRecordCount": input_observation_count + failed_record_count,
            "discardedObservationCount": (input_observation_count - published_record_count),
            "failedRecordCount": failed_record_count,
            "format": FORMAT,
            "formatVersion": FORMAT_VERSION,
            "inputObservationCount": input_observation_count,
            "inputObservationDigest": input_digest,
            "partitionPolicy": _partition_policy(),
            "payloadPartitions": [partition.receipt() for partition in partitions],
            "publishedRecordCount": published_record_count,
            "reconciliationDigest": reconciliation_digest,
            "reconciliationPassCount": traversal_count,
            "releaseSchemaDigest": release_schema_digest,
            "releaseSchemaId": RELEASE_SCHEMA_ID,
            "renditionIndexCount": rendition_count,
            "semanticVerdict": "pass",
            "sourceNativeSchemaSetDigest": schema_set_digest,
            "sourceStateDigest": state_digest,
            "sourceStateScope": profile.source_state_scope,
            "sourceSystemId": profile.source_system_id,
            "startedAt": build.started_at,
            "transientFailureCount": 0,
            "unclassedFailureCount": 0,
            "verifierId": build.producer.verifier_id,
            "verifierImplementationId": build.producer.verifier_implementation_id,
            "verifierVersion": build.producer.verifier_version,
            "warnings": [],
        }
        publication_bytes = _write_metadata(
            staging,
            profile=profile,
            build=build,
            spec=spec,
            receipt=receipt,
            scopes=scopes,
            release_schemas=release_schemas,
            external_members=(*evidence_descriptors, *(partition.member for partition in partitions)),
        )
        artifact = admit_artifact(
            LocalMemberSource(staging),
            blob_source=blob_store,
            semantic_verifier=lambda artifact, source: verify_source_native_release(
                artifact,
                source,
                profile=profile,
                blob_source=blob_store,
            ),
            scratch_directory=scratch / "verify",
        )
        publish_directory_once(staging, destination)
        return PublishedSourceNativeRelease(
            destination,
            artifact,
            byte_measurements={
                "payloadBytesRead": accounting.payload_bytes_read,
                "payloadBytesReused": accounting.payload_bytes_reused,
                "payloadBytesWritten": accounting.payload_bytes_written,
                "publicationBytesWritten": publication_bytes,
            },
        )


def _stage_indexed_partitions(
    connection: sqlite3.Connection,
    *,
    accepted_traversal: int,
    scratch: Path,
    blob_store: SourceNativeBlobStore,
    accounting: _ByteAccounting,
) -> list[_PayloadPartition]:
    """Write the four ordered payload kinds into their fixed identity buckets."""
    partitions: list[_PayloadPartition] = []
    for partition_id in (f"{index:02d}" for index in range(PARTITION_BUCKET_COUNT)):
        rows_by_kind: tuple[tuple[str, Iterable[Mapping[str, Any]]], ...] = (
            (
                PARTITION_LEDGER,
                _full_ledger_rows(connection, accepted_traversal, partition_id),
            ),
            (
                PARTITION_PAGES,
                _page_rows(
                    connection,
                    accepted_traversal,
                    partition_id=partition_id,
                ),
            ),
            (
                PARTITION_RECORDS,
                _query_mappings(
                    connection,
                    "SELECT record_payload FROM observations WHERE traversal = ? AND selected = 1 AND partition_id = ? "
                    "ORDER BY source_record_id",
                    (accepted_traversal, partition_id),
                ),
            ),
            (
                PARTITION_RENDITIONS,
                _query_renditions(connection, accepted_traversal, partition_id),
            ),
        )
        for partition_kind, rows in rows_by_kind:
            partition = _stage_partition(
                scratch,
                blob_store=blob_store,
                accounting=accounting,
                partition_kind=partition_kind,
                partition_id=partition_id,
                rows=rows,
            )
            if partition is not None:
                partitions.append(partition)
    partitions.sort(key=lambda value: (value.partition_kind, value.partition_id))
    return partitions


def _write_metadata(
    staging: Path,
    *,
    profile: SourceNativeProfile,
    build: SourceNativeReleaseBuild,
    spec: Mapping[str, Any],
    receipt: dict[str, Any],
    scopes: list[dict[str, Any]],
    release_schemas: Mapping[str, Mapping[str, Any]],
    external_members: tuple[MemberDescriptor, ...],
) -> int:
    """Write metadata once and report the resulting local file sizes."""
    scopes_bytes = b"".join(chunk for value in scopes for chunk in (canonical_json_bytes(value), b"\n"))
    source_schema_bytes = canonical_json_bytes(profile.source_schema)
    release_schema_bytes = canonical_json_bytes(release_schemas)
    refs = [member.blob_ref for member in external_members]
    if None in refs or len(set(refs)) != len(refs):
        raise SourceNativeReleaseError("source-native external payload members must have distinct content identities")
    receipt = _RECEIPT_SHAPE.parse(receipt)
    receipt_bytes = canonical_json_bytes(receipt)
    local_members = (
        describe_member_from_receipt(
            object_key=SCOPES_KEY,
            sha256="sha256:" + hashlib.sha256(scopes_bytes).hexdigest(),
            role=ROLE_SCOPES,
            media_type="application/x-ndjson",
            byte_size=len(scopes_bytes),
            record_count=1,
        ),
        describe_member_from_receipt(
            object_key=RECEIPT_KEY,
            sha256="sha256:" + hashlib.sha256(receipt_bytes).hexdigest(),
            role=ROLE_RECEIPT,
            media_type="application/json",
            byte_size=len(receipt_bytes),
        ),
        describe_member_from_receipt(
            object_key=RELEASE_SCHEMA_KEY,
            sha256="sha256:" + hashlib.sha256(release_schema_bytes).hexdigest(),
            role=ROLE_RELEASE_SCHEMA,
            media_type="application/schema+json",
            byte_size=len(release_schema_bytes),
            schema_id=RELEASE_SCHEMA_ID,
        ),
        describe_member_from_receipt(
            object_key=profile.source_schema_key,
            sha256="sha256:" + hashlib.sha256(source_schema_bytes).hexdigest(),
            role=ROLE_SCHEMA,
            media_type="application/schema+json",
            byte_size=len(source_schema_bytes),
            schema_id=str(profile.source_schema["$id"]),
        ),
    )
    manifest, manifest_bytes = MemberManifestReference.for_members(
        scope_kind="global",
        scope_id="source-native",
        object_key=MANIFEST_KEY,
        members=(*local_members, *external_members),
    )
    root = build_artifact_root(
        kind=KIND,
        spec=spec,
        producer=build.producer,
        manifests=(manifest,),
        supersedes=build.supersedes,
    )
    root_bytes = canonical_json_bytes(root)
    members = (
        (SCOPES_KEY, scopes_bytes),
        (profile.source_schema_key, source_schema_bytes),
        (RELEASE_SCHEMA_KEY, release_schema_bytes),
        (RECEIPT_KEY, receipt_bytes),
        (MANIFEST_KEY, manifest_bytes),
        (ROOT_OBJECT_KEY, root_bytes),
    )
    for key, payload in members:
        write_bytes_once(staging / key, payload)
    return sum((staging / key).stat().st_size for key, _ in members)
