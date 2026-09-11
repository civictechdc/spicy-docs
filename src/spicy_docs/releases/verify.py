"""Compare a release against full offline acquisition replay."""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Iterator, Mapping
from itertools import zip_longest
from pathlib import Path
from typing import Any

from rulespec_artifacts import (
    BlobSource,
    MemberSource,
    VerifiedArtifact,
)

from spicy_docs.releases.admission import (
    _member_index,
    verify_source_native_admission,
)
from spicy_docs.releases.format import (
    _RECEIPT_SHAPE,
    FAILURE_CLASS_DETERMINISTIC,
    PARTITION_LEDGER,
    PARTITION_PAGES,
    PARTITION_RECORDS,
    PARTITION_RENDITIONS,
    REASON_RECORD_UNCLASSIFIABLE,
    RECEIPT_KEY,
    ROLE_EVIDENCE,
    SCOPES_KEY,
    SourceNativeReleaseError,
)
from spicy_docs.releases.observations import (
    _ordered_rendition_rows,
    _policy_for_scope,
    _query_mappings,
    _section_digest,
    _source_state_digest,
)
from spicy_docs.releases.partitions import (
    _partition_rows,
    _payload_partitions,
    _read_jsonl,
    _read_one_json,
)
from spicy_docs.releases.profile import (
    SourceNativeProfile,
)
from spicy_docs.releases.replay import (
    _replay_acquisition,
)


def verify_source_native_release(
    artifact: VerifiedArtifact,
    source: MemberSource,
    *,
    profile: SourceNativeProfile,
    blob_source: BlobSource | None,
) -> None:
    """Recompute the selected source profile at the producer gate."""

    verify_source_native_admission(
        artifact,
        source,
        profile=profile,
        blob_source=blob_source,
    )
    _, by_ref, by_role = _member_index(artifact, source)
    spec = artifact.root["spec"]
    if not isinstance(spec, Mapping):
        raise SourceNativeReleaseError("source-native root spec is not an object")
    receipt = _RECEIPT_SHAPE.parse(_read_one_json(source, RECEIPT_KEY))
    partitions = _payload_partitions(receipt, by_ref)
    scopes = list(_read_jsonl(source, SCOPES_KEY))
    if len(scopes) != 1 or set(scopes[0]) != {"fields", "scopeId", "scopeKind", "sourceSystemId"}:
        raise SourceNativeReleaseError(f"{profile.name} source scope differs")
    if (
        scopes[0].get("scopeId") != profile.scope_id
        or scopes[0].get("scopeKind") != "source-collection"
        or scopes[0].get("sourceSystemId") != profile.source_system_id
        or not isinstance(scopes[0].get("fields"), Mapping)
    ):
        raise SourceNativeReleaseError(f"{profile.name} source scope values differ")
    query_scope = dict(profile.validate_query_scope(scopes[0]["fields"]))
    if query_scope != dict(scopes[0]["fields"]):
        raise SourceNativeReleaseError(f"{profile.name} source scope is not canonical")
    policy_digest = _section_digest(
        "spicyregs-acquisition-policy/1", "policy", 1, (_policy_for_scope(query_scope, profile),)
    )
    if policy_digest != spec["acquisitionPolicyDigest"]:
        raise SourceNativeReleaseError("acquisition-policy digest differs")
    schema_declarations = [profile.source_schema_declaration()]
    schema_set_digest = _section_digest(
        "spicyregs-source-schema-set/1", "schemas", len(schema_declarations), schema_declarations
    )
    if schema_set_digest != spec["sourceNativeSchemaSetDigest"]:
        raise SourceNativeReleaseError("source-native schema-set digest differs")
    evidence_members = {member.blob_ref: member for member in by_role[ROLE_EVIDENCE] if member.blob_ref is not None}
    with tempfile.TemporaryDirectory(prefix="source-native-verify-") as directory:
        connection = sqlite3.connect(Path(directory) / "replay.sqlite3")
        try:
            accepted, traversal_count = _replay_acquisition(
                connection,
                source=source,
                blob_source=blob_source,
                evidence_members=evidence_members,
                page_partitions=partitions[PARTITION_PAGES],
                query_scope=query_scope,
                profile=profile,
            )
            if receipt["reconciliationPassCount"] != traversal_count:
                raise SourceNativeReleaseError("reconciliation pass count differs")
            published_record_count = int(
                connection.execute(
                    "SELECT count(*) FROM observations WHERE traversal = ? AND selected = 1",
                    (accepted,),
                ).fetchone()[0]
            )
            input_observation_count = int(
                connection.execute(
                    "SELECT count(*) FROM observations WHERE traversal = ?",
                    (accepted,),
                ).fetchone()[0]
            )

            def replayed_records() -> Iterator[Mapping[str, Any]]:
                return _query_mappings(
                    connection,
                    "SELECT record_payload FROM observations "
                    "WHERE traversal = ? AND selected = 1 ORDER BY source_record_id",
                    (accepted,),
                )

            def replayed_observations() -> Iterator[Mapping[str, Any]]:
                return _query_mappings(
                    connection,
                    "SELECT record_payload FROM observations WHERE traversal = ? "
                    "ORDER BY source_record_id, source_version IS NULL, source_version DESC",
                    (accepted,),
                )

            def admitted_records() -> Iterator[Mapping[str, Any]]:
                return _partition_rows(
                    source,
                    blob_source,
                    partitions[PARTITION_RECORDS],
                )

            def expected_renditions() -> Iterator[Mapping[str, Any]]:
                for row in replayed_records():
                    record = row.get("record")
                    if not isinstance(record, Mapping):
                        raise SourceNativeReleaseError(f"published {profile.name} record payload is invalid")
                    yield from _ordered_rendition_rows(
                        profile,
                        profile.classify_record(record),
                    )

            rendition_count = sum(1 for _ in expected_renditions())

            sentinel = object()
            observed_count = 0
            for actual, expected in zip_longest(admitted_records(), replayed_records(), fillvalue=sentinel):
                if actual is sentinel or expected is sentinel or actual != expected:
                    raise SourceNativeReleaseError("published records differ from replayed source evidence")
                observed_count += 1
            if observed_count != published_record_count:
                raise SourceNativeReleaseError("published record count differs from replayed evidence")

            observed_rendition_count = 0
            for actual, expected in zip_longest(
                _partition_rows(
                    source,
                    blob_source,
                    partitions[PARTITION_RENDITIONS],
                ),
                expected_renditions(),
                fillvalue=sentinel,
            ):
                if actual is sentinel or expected is sentinel or actual != expected:
                    raise SourceNativeReleaseError("rendition index differs from source-stated locators")
                observed_rendition_count += 1
            if observed_rendition_count != rendition_count:
                raise SourceNativeReleaseError("rendition count differs from replayed evidence")

            def expected_ledger() -> Iterator[Mapping[str, Any]]:
                # This merge uses replayed facts, never the writer's ledger helper.
                query = (
                    "SELECT source_record_id, evidence_ref, 0 AS failed FROM observations "
                    "WHERE traversal = ? AND selected = 1 "
                    "UNION ALL SELECT source_record_id, evidence_ref, 1 FROM failures "
                    "WHERE traversal = ? ORDER BY source_record_id"
                )
                for source_record_id, evidence_ref, failed in connection.execute(query, (accepted, accepted)):
                    yield {
                        "evidenceBlobRef": evidence_ref,
                        "failure": {
                            "class": FAILURE_CLASS_DETERMINISTIC,
                            "evidenceDigest": evidence_ref,
                            "reasonCode": REASON_RECORD_UNCLASSIFIABLE,
                        }
                        if failed
                        else None,
                        "observationRef": {"sourceRecordId": source_record_id},
                        "sourceRecordId": source_record_id,
                    }

            def admitted_ledger() -> Iterator[Mapping[str, Any]]:
                return _partition_rows(
                    source,
                    blob_source,
                    partitions[PARTITION_LEDGER],
                )

            # Exact comparison proves successful and rejected positions, classes,
            # reasons, and evidence links. A transport outcome is not a fact that
            # can be established by reclassifying these retained page bytes.
            for actual, expected in zip_longest(admitted_ledger(), expected_ledger(), fillvalue=sentinel):
                if actual is sentinel or expected is sentinel or actual != expected:
                    raise SourceNativeReleaseError("acquisition ledger differs from replayed evidence")
            replayed_failed_count = int(
                connection.execute("SELECT count(*) FROM failures WHERE traversal = ?", (accepted,)).fetchone()[0]
            )
            if (
                receipt["deterministicFailureCount"] != replayed_failed_count
                or receipt["transientFailureCount"] != 0
                or receipt["unclassedFailureCount"] != 0
            ):
                raise SourceNativeReleaseError("source-native failure summary differs from replayed evidence")
            observed_ledger_count = published_record_count + replayed_failed_count

            state_digest = _source_state_digest(
                (len(scopes), scopes),
                (len(schema_declarations), schema_declarations),
                (published_record_count, admitted_records()),
                (
                    rendition_count,
                    _partition_rows(
                        source,
                        blob_source,
                        partitions[PARTITION_RENDITIONS],
                    ),
                ),
            )
            if state_digest != spec["sourceStateDigest"]:
                raise SourceNativeReleaseError("source-state digest differs")
            input_digest = _section_digest(
                "spicyregs-input-observations/1", "observations", input_observation_count, replayed_observations()
            )
            if input_digest != receipt["inputObservationDigest"]:
                raise SourceNativeReleaseError("input-observation digest differs")
            ledger_digest = _section_digest(
                "spicyregs-acquisition-ledger/1", "entries", observed_ledger_count, admitted_ledger()
            )
            if ledger_digest != receipt["acquisitionLedgerDigest"]:
                raise SourceNativeReleaseError("acquisition-ledger digest differs")
            accepted_page_count = int(connection.execute("SELECT count(*) FROM pages WHERE accepted = 1").fetchone()[0])
            accepted_pages = _query_mappings(
                connection,
                "SELECT payload FROM pages WHERE accepted = 1 ORDER BY traversal, page",
            )
            reconciliation_digest = _section_digest(
                "spicyregs-source-reconciliation/1", "pages", accepted_page_count, accepted_pages
            )
            if reconciliation_digest != receipt["reconciliationDigest"]:
                raise SourceNativeReleaseError("source-reconciliation digest differs")
            counts = {
                "acquisitionEvidenceCount": len(evidence_members),
                "discoveredRecordCount": input_observation_count + replayed_failed_count,
                "discardedObservationCount": (input_observation_count - published_record_count),
                "failedRecordCount": replayed_failed_count,
                "inputObservationCount": input_observation_count,
                "publishedRecordCount": published_record_count,
                "renditionIndexCount": rendition_count,
            }
            for name, expected in counts.items():
                if receipt.get(name) != expected:
                    raise SourceNativeReleaseError(f"receipt count differs at {name}")
        finally:
            connection.close()
