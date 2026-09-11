"""Open an admitted source release and stream selected records."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
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
    PARTITION_RECORDS,
    PARTITION_RENDITIONS,
    RECEIPT_KEY,
    SourceNativeReleaseError,
)
from spicy_docs.releases.partitions import (
    _partition_rows,
    _payload_partitions,
    _read_one_json,
)
from spicy_docs.releases.profile import (
    SourceNativeProfile,
)


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
        spec = self._artifact.root["spec"]
        self.source_state_scope = str(spec["sourceStateScope"])
        self.source_system_id = str(spec["sourceSystemId"])
        self.source_system_version = str(spec["sourceSystemVersion"])
        self.source_state_digest = str(spec["sourceStateDigest"])
        self.source_native_schema_set_digest = str(spec["sourceNativeSchemaSetDigest"])

    @property
    def pin(self) -> ArtifactPin:
        return self._artifact.pin

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
