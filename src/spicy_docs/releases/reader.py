"""Open an admitted source release and stream selected records."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import closing
from copy import deepcopy
from typing import Any

from rulespec_artifacts import (
    ArtifactPin,
    BlobSource,
    MemberSource,
    admit_artifact,
)

from spicy_docs.releases.admission import (
    _member_index,
    verify_source_native_admission,
)
from spicy_docs.releases.format import (
    _RECEIPT_SHAPE,
    MAX_EVIDENCE_BYTES,
    PARTITION_LEDGER,
    PARTITION_RECORDS,
    PARTITION_RENDITIONS,
    RECEIPT_KEY,
    ROLE_EVIDENCE,
    SCOPES_KEY,
    SourceNativeReleaseError,
)
from spicy_docs.releases.observations import _policy_for_scope, _section_digest
from spicy_docs.releases.partitions import (
    _partition_id,
    _partition_rows,
    _payload_partitions,
    _read_jsonl,
    _read_one_json,
)
from spicy_docs.releases.profile import (
    SourceNativeProfile,
)
from spicy_docs.storage.blobs import iter_verified_blob


def _collection_outcome(
    source: MemberSource,
    *,
    profile: SourceNativeProfile,
    spec: Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize existing metadata after admission, without reopening payloads."""

    if receipt is None:
        receipt = _RECEIPT_SHAPE.parse(_read_one_json(source, RECEIPT_KEY))
    with closing(_read_jsonl(source, SCOPES_KEY)) as scopes:
        scope = next(scopes, None)
        if scope is None or next(scopes, None) is not None or not isinstance(scope.get("fields"), Mapping):
            raise SourceNativeReleaseError("source-native requested scope must be one fields mapping")
    policy = _policy_for_scope(scope["fields"], profile)
    policy_digest = _section_digest("spicyregs-acquisition-policy/1", "policy", 1, (policy,))
    if policy_digest != spec["acquisitionPolicyDigest"]:
        raise SourceNativeReleaseError("acquisition-policy digest differs")
    if receipt["discoveredRecordCount"] == 0:
        record_outcome = "empty"
    elif receipt["failedRecordCount"] == 0:
        record_outcome = "no-record-rejections"
    elif receipt["publishedRecordCount"] == 0:
        record_outcome = "total-rejection"
    else:
        record_outcome = "partial-rejection"
    return {
        "requestedScope": deepcopy(dict(scope["fields"])),
        "sourceStateScope": receipt["sourceStateScope"],
        "traversalAcceptance": profile.traversal_acceptance,
        "acquisitionPolicy": deepcopy(policy),
        **{
            field: spec[field]
            for field in ("acquisitionPolicyId", "acquisitionPolicyVersion", "acquisitionPolicyDigest")
        },
        "recordOutcome": record_outcome,
        **{
            field: receipt[field]
            for field in (
                "acquisitionEvidenceCount",
                "discoveredRecordCount",
                "inputObservationCount",
                "publishedRecordCount",
                "failedRecordCount",
                "discardedObservationCount",
                "reconciliationPassCount",
                "renditionIndexCount",
                "deterministicFailureCount",
                "transientFailureCount",
                "unclassedFailureCount",
            )
        },
        "warnings": deepcopy(receipt["warnings"]),
    }


class SourceNativeReleaseReader:
    """Structurally admit once, then stream records through an injected source."""

    def __init__(
        self,
        source: MemberSource,
        *,
        blob_source: BlobSource,
        profile: SourceNativeProfile,
        accepted_verifier_implementation_ids: frozenset[str],
        expected_pin: ArtifactPin | None = None,
    ) -> None:
        if not accepted_verifier_implementation_ids:
            raise SourceNativeReleaseError("at least one verifier implementation must be accepted")
        self._source = source
        self._blob_source = blob_source
        self._artifact = admit_artifact(
            source,
            blob_source=blob_source,
            expected_pin=expected_pin,
            semantic_verifier=lambda artifact, source: verify_source_native_admission(
                artifact,
                source,
                profile=profile,
                blob_source=blob_source,
            ),
        )
        producer = self._artifact.root["producer"]
        if producer["verifierImplementationId"] not in accepted_verifier_implementation_ids:
            raise SourceNativeReleaseError("source-native verifier implementation is not accepted")
        _, by_ref, _ = _member_index(self._artifact, source)
        self._evidence_members = {ref: member for ref, member in by_ref.items() if member.role == ROLE_EVIDENCE}
        receipt = _RECEIPT_SHAPE.parse(_read_one_json(source, RECEIPT_KEY))
        partitions = _payload_partitions(receipt, by_ref)
        self._record_partitions = partitions[PARTITION_RECORDS]
        self._rendition_partitions = partitions[PARTITION_RENDITIONS]
        self._ledger_partitions = partitions[PARTITION_LEDGER]
        spec = self._artifact.root["spec"]
        self._collection_outcome = _collection_outcome(source, profile=profile, spec=spec, receipt=receipt)
        self.source_state_scope = str(spec["sourceStateScope"])
        self.source_system_id = str(spec["sourceSystemId"])
        self.source_system_version = str(spec["sourceSystemVersion"])
        self.source_state_digest = str(spec["sourceStateDigest"])
        self.source_native_schema_set_digest = str(spec["sourceNativeSchemaSetDigest"])

    @property
    def pin(self) -> ArtifactPin:
        return self._artifact.pin

    @property
    def collection_outcome(self) -> Mapping[str, Any]:
        """Return fresh scope, policy, and counts; empty input does not prove absence.

        Counts describe the accepted traversal: discovered = input + failed,
        and input = published + discarded. See ``docs/source-native-outcomes.md``
        for the units and coverage limits.
        """

        return deepcopy(self._collection_outcome)

    def record_evidence(self, source_record_id: str) -> Mapping[str, Any] | None:
        """Return the selected published record's evidence reference, if present.

        The result carries ``sourceRecordId``, ``observationRef``,
        ``evidenceBlobRef`` and ``failure: None``. It does not enumerate discarded
        observations. Returns None when this release has no published success
        for the identity, including failure-only identities. Lookup scans at
        most one existing ledger partition in bounded memory and closes its
        stream before returning.
        """

        bucket = _partition_id(source_record_id)
        partitions = tuple(partition for partition in self._ledger_partitions if partition.partition_id == bucket)
        with closing(_partition_rows(self._source, self._blob_source, partitions)) as rows:
            for row in rows:
                if row["sourceRecordId"] == source_record_id:
                    return row if row["failure"] is None else None
                if row["sourceRecordId"] > source_record_id:
                    break
        return None

    def iter_record_evidence(self) -> Iterator[Mapping[str, Any]]:
        """Stream selected success evidence in the same identity order as records.

        Bulk consumers can join this iterator with ``iter_records`` without
        rescanning a ledger partition for every identity. Each ledger partition
        is read once, using the existing bounded merge and row checks. Failures
        remain available separately through ``iter_failures``. Close the iterator
        when stopping early; full exhaustion checks partition record counts.
        """

        with closing(_partition_rows(self._source, self._blob_source, self._ledger_partitions)) as rows:
            for row in rows:
                if row["failure"] is None:
                    yield row

    def iter_evidence(self, blob_ref: str) -> Iterator[bytes]:
        """Stream an admitted original; exhausting the iterator rechecks size and digest.

        Consume into temporary storage before using it as verified input. A partial
        read does not establish integrity. Unknown and non-evidence refs refuse.
        """
        member = self._evidence_members.get(blob_ref) if isinstance(blob_ref, str) else None
        if member is None:
            raise SourceNativeReleaseError("reference is not an admitted source evidence member")
        yield from iter_verified_blob(self._blob_source, blob_ref, member.byte_size)

    def read_evidence(self, blob_ref: str, *, max_bytes: int = MAX_EVIDENCE_BYTES) -> bytes:
        """Read one admitted evidence member within a caller-selected byte limit.

        The limit must be a nonnegative integer no larger than the release
        evidence bound. Size and digest are rechecked on the returned bytes,
        including with a custom blob source. Unknown and non-evidence references
        are refused before opening storage. The storage context always closes.
        """

        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 0 <= max_bytes <= MAX_EVIDENCE_BYTES:
            raise ValueError(f"evidence byte limit must be an integer from 0 to {MAX_EVIDENCE_BYTES}")
        member = self._evidence_members.get(blob_ref) if isinstance(blob_ref, str) else None
        if member is None:
            raise SourceNativeReleaseError("reference is not an admitted source evidence member")
        if member.byte_size > max_bytes:
            raise SourceNativeReleaseError("source evidence exceeds the requested byte limit")
        data = bytearray()
        with self._blob_source.open(blob_ref) as stream:
            while len(data) <= max_bytes:
                chunk = stream.read(min(64 * 1024, max_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
        if len(data) > max_bytes:
            raise SourceNativeReleaseError("source evidence exceeds the requested byte limit")
        if len(data) != member.byte_size:
            raise SourceNativeReleaseError("source evidence size differs from admitted member")
        if "sha256:" + hashlib.sha256(data).hexdigest() != blob_ref:
            raise SourceNativeReleaseError("source evidence digest differs from admitted member")
        return bytes(data)

    def iter_failures(self, limit: int = 100) -> Iterator[Mapping[str, Any]]:
        """Stream at most ``limit`` failure ledger rows in source-record order.

        Each row retains its failure, observation, and evidence references.
        Memory is bounded by the fixed partition count and maximum row size;
        finding a late failure can still read the entire ledger.
        """

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("failure limit must be a non-negative integer")
        if limit == 0 or self._collection_outcome["failedRecordCount"] == 0:
            return
        with closing(_partition_rows(self._source, self._blob_source, self._ledger_partitions)) as rows:
            count = 0
            for row in rows:
                if row["failure"] is not None:
                    yield row
                    count += 1
                    if count == limit:
                        return

    def iter_records(self) -> Iterator[Mapping[str, Any]]:
        """Stream selected published records in source identity order."""

        yield from _partition_rows(
            self._source,
            self._blob_source,
            self._record_partitions,
        )

    def iter_renditions(self) -> Iterator[Mapping[str, Any]]:
        """Stream selected rendition rows ordered by source identity."""

        yield from _partition_rows(
            self._source,
            self._blob_source,
            self._rendition_partitions,
        )
