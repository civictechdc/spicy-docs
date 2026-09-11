"""Open an admitted source release and stream selected records."""

from __future__ import annotations

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
    PARTITION_LEDGER,
    PARTITION_RECORDS,
    PARTITION_RENDITIONS,
    RECEIPT_KEY,
    SCOPES_KEY,
    SourceNativeReleaseError,
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


def _collection_outcome(source: MemberSource, receipt: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Summarize existing metadata after admission, without reopening payloads."""

    if receipt is None:
        receipt = _RECEIPT_SHAPE.parse(_read_one_json(source, RECEIPT_KEY))
    with closing(_read_jsonl(source, SCOPES_KEY)) as scopes:
        scope = next(scopes, None)
        if scope is None or next(scopes, None) is not None or not isinstance(scope.get("fields"), Mapping):
            raise SourceNativeReleaseError("source-native requested scope must be one fields mapping")
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
        receipt = _RECEIPT_SHAPE.parse(_read_one_json(source, RECEIPT_KEY))
        partitions = _payload_partitions(receipt, by_ref)
        self._record_partitions = partitions[PARTITION_RECORDS]
        self._rendition_partitions = partitions[PARTITION_RENDITIONS]
        self._ledger_partitions = partitions[PARTITION_LEDGER]
        self._collection_outcome = _collection_outcome(source, receipt)
        spec = self._artifact.root["spec"]
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
        """Return fresh scope/count metadata; empty input does not prove absence.

        Counts describe the accepted traversal: discovered = input + failed,
        and input = published + discarded. See ``docs/source-native-outcomes.md``
        for the units and coverage limits.
        """

        return deepcopy(self._collection_outcome)

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
        yield from _partition_rows(
            self._source,
            self._blob_source,
            self._record_partitions,
        )

    def iter_renditions(self) -> Iterator[Mapping[str, Any]]:
        yield from _partition_rows(
            self._source,
            self._blob_source,
            self._rendition_partitions,
        )
