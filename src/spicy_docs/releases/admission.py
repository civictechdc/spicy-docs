"""Bounded source-native admission under a recognized producer policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rulespec_artifacts import (
    ROOT_OBJECT_KEY,
    BlobSource,
    MemberDescriptor,
    MemberSource,
    VerifiedArtifact,
    iter_member_descriptors,
    schema_bundle_digest,
)

from spicy_docs.releases.format import (
    _RECEIPT_SHAPE,
    ALWAYS_REQUIRED_ROLES,
    FORMAT,
    FORMAT_VERSION,
    KIND,
    KNOWN_ACQUISITION_POLICY_VERSIONS,
    KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS,
    MAX_ROW_BYTES,
    PARTITION_KINDS,
    PARTITION_LEDGER,
    PARTITION_RECORDS,
    PARTITION_RENDITIONS,
    RECEIPT_KEY,
    RELEASE_SCHEMA_ID,
    RELEASE_SCHEMA_KEY,
    REQUIRED_ROLES,
    ROLE_EVIDENCE,
    ROLE_LEDGER,
    ROLE_RECEIPT,
    ROLE_RECORDS,
    ROLE_RELEASE_SCHEMA,
    ROLE_RENDITIONS,
    ROLE_SCHEMA,
    ROLE_SCOPES,
    SCOPES_KEY,
    SPEC_FIELDS,
    SUPPORTED_PRODUCER_PRODUCTS,
    VERIFIER_ID,
    VERIFIER_VERSION,
    SourceNativeReleaseError,
    _utc,
)
from spicy_docs.releases.observations import (
    _digest_records,
)
from spicy_docs.releases.partitions import (
    _payload_partitions,
    _read_one_json,
)
from spicy_docs.source_native_profile import (
    SourceNativeProfile,
)


def _member_index(
    artifact: VerifiedArtifact,
    source: MemberSource,
) -> tuple[
    dict[str, MemberDescriptor],
    dict[str, MemberDescriptor],
    dict[str, list[MemberDescriptor]],
]:
    by_key: dict[str, MemberDescriptor] = {}
    by_ref: dict[str, MemberDescriptor] = {}
    by_role: dict[str, list[MemberDescriptor]] = {}
    for member in iter_member_descriptors(artifact, source):
        if member.object_key is not None:
            by_key[member.object_key] = member
        elif member.blob_ref is not None:
            by_ref[member.blob_ref] = member
        else:
            raise SourceNativeReleaseError("source-native member has no location")
        by_role.setdefault(member.role, []).append(member)
    roles = frozenset(by_role)
    if not ALWAYS_REQUIRED_ROLES <= roles <= REQUIRED_ROLES:
        raise SourceNativeReleaseError(
            f"source-native roles differ; missing={sorted(ALWAYS_REQUIRED_ROLES - roles)}, "
            f"unknown={sorted(roles - REQUIRED_ROLES)}"
        )
    for role in (ROLE_RECORDS, ROLE_RENDITIONS, ROLE_LEDGER, ROLE_EVIDENCE):
        if any(member.blob_ref is None for member in by_role.get(role, ())):
            raise SourceNativeReleaseError(f"source-native {role} payload members must use external blobRef locations")
    for role in (ROLE_SCOPES, ROLE_SCHEMA, ROLE_RELEASE_SCHEMA, ROLE_RECEIPT):
        if any(member.object_key is None for member in by_role[role]):
            raise SourceNativeReleaseError(f"source-native {role} publication members must be local")
    return by_key, by_ref, by_role


def _failure_summary_counts(receipt: Mapping[str, Any]) -> tuple[int, int, int]:
    """Return the receipt's (deterministic, transient, unclassed) tally.

    All three are optional (``_RECEIPT_OPTIONAL_FIELDS``); an absent count
    reads as zero, so an old, all-success receipt reconciles trivially
    against ``failedRecordCount == 0`` without carrying these keys at all.
    """

    counts: list[int] = []
    for field in ("deterministicFailureCount", "transientFailureCount", "unclassedFailureCount"):
        value = receipt.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SourceNativeReleaseError(f"source-native receipt count is invalid at {field}")
        counts.append(value)
    return counts[0], counts[1], counts[2]


def verify_source_native_admission(
    artifact: VerifiedArtifact,
    source: MemberSource,
    *,
    profile: SourceNativeProfile,
    blob_source: BlobSource | None,
) -> None:
    """Check bounded receipt/root agreement for consumer open."""

    by_key, by_ref, by_role = _member_index(artifact, source)
    if by_ref and blob_source is None:
        raise SourceNativeReleaseError("source-native external members require an injected blob source")
    if artifact.root.get("kind") != KIND:
        raise SourceNativeReleaseError("artifact is not a SpicyRegs source-native release")
    spec = artifact.root.get("spec")
    if not isinstance(spec, Mapping):
        raise SourceNativeReleaseError("source-native root spec is not an object")
    if set(spec) != SPEC_FIELDS:
        raise SourceNativeReleaseError("source-native root spec fields differ")
    if (
        spec.get("sourceSystemId") != profile.source_system_id
        or spec.get("sourceSystemVersion") != profile.source_system_version
        or spec.get("acquisitionPolicyId") != profile.acquisition_policy_id
        or spec.get("sourceStateScope") != profile.source_state_scope
    ):
        raise SourceNativeReleaseError(f"source-native root names an unsupported {profile.name} profile")
    accepted_versions = KNOWN_ACQUISITION_POLICY_VERSIONS.get(
        profile.acquisition_policy_id, frozenset({profile.acquisition_policy_version})
    )
    if spec.get("acquisitionPolicyVersion") not in accepted_versions:
        raise SourceNativeReleaseError(
            f"source-native root names a {profile.name} acquisition policy version this project "
            f"has not published under: {spec.get('acquisitionPolicyVersion')!r}"
        )
    receipts = by_role[ROLE_RECEIPT]
    if len(receipts) != 1 or receipts[0].object_key != RECEIPT_KEY:
        raise SourceNativeReleaseError("source-native release must carry one publication receipt")
    singleton_members = {
        ROLE_RELEASE_SCHEMA: RELEASE_SCHEMA_KEY,
        ROLE_SCHEMA: profile.source_schema_key,
        ROLE_SCOPES: SCOPES_KEY,
    }
    for role, object_key in singleton_members.items():
        members = by_role[role]
        if len(members) != 1 or members[0].object_key != object_key:
            raise SourceNativeReleaseError(f"source-native release must carry one {role} member")
    receipt = _RECEIPT_SHAPE.parse(_read_one_json(source, RECEIPT_KEY))
    partitions = _payload_partitions(receipt, by_ref)
    for field in (
        "acquisitionPolicyDigest",
        "releaseSchemaDigest",
        "sourceNativeSchemaSetDigest",
        "sourceStateDigest",
        "sourceStateScope",
        "sourceSystemId",
    ):
        if receipt.get(field) != spec.get(field):
            raise SourceNativeReleaseError(f"receipt differs from root spec at {field}")
    producer = artifact.root.get("producer")
    if not isinstance(producer, Mapping):
        raise SourceNativeReleaseError("source-native producer record is absent")
    if (
        producer.get("product") not in SUPPORTED_PRODUCER_PRODUCTS
        or producer.get("verifierId") != VERIFIER_ID
        or producer.get("verifierVersion") != VERIFIER_VERSION
    ):
        raise SourceNativeReleaseError("source-native producer names an unsupported verifier")
    for receipt_field, producer_field in (
        ("verifierId", "verifierId"),
        ("verifierVersion", "verifierVersion"),
        ("verifierImplementationId", "verifierImplementationId"),
    ):
        if receipt.get(receipt_field) != producer.get(producer_field):
            raise SourceNativeReleaseError(f"receipt differs from producer at {receipt_field}")
    if receipt.get("semanticVerdict") != "pass":
        raise SourceNativeReleaseError("source-native receipt is not publishable")
    failed_record_count = receipt.get("failedRecordCount")
    if failed_record_count != 0:
        deterministic, transient, unclassed = _failure_summary_counts(receipt)
        if deterministic + transient + unclassed != failed_record_count:
            raise SourceNativeReleaseError("source-native failure summary does not reconcile with failedRecordCount")
        if unclassed:
            raise SourceNativeReleaseError("source-native receipt records an unclassed acquisition failure")
        if transient:
            raise SourceNativeReleaseError("source-native receipt records a transient acquisition failure")
        # A deterministic failure is a fact about this one acquisition
        # attempt, not a fact about the item: no consumer may cache "no
        # body, do not ask again" from it, because a later release that
        # succeeds for the same sourceRecordId supersedes it outright.
    if (
        receipt.get("format") != FORMAT
        or receipt.get("formatVersion") != FORMAT_VERSION
        or receipt.get("releaseSchemaId") != RELEASE_SCHEMA_ID
    ):
        raise SourceNativeReleaseError("source-native receipt format is unsupported")
    started = _utc(str(receipt.get("startedAt")), "receipt.startedAt")
    completed = _utc(str(receipt.get("completedAt")), "receipt.completedAt")
    if completed < started:
        raise SourceNativeReleaseError("source-native receipt completion precedes start")
    for field in (
        "acquisitionEvidenceCount",
        "discoveredRecordCount",
        "discardedObservationCount",
        "failedRecordCount",
        "inputObservationCount",
        "publishedRecordCount",
        "reconciliationPassCount",
        "renditionIndexCount",
    ):
        value = receipt.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SourceNativeReleaseError(f"source-native receipt count is invalid at {field}")
    if (
        receipt["inputObservationCount"] != receipt["publishedRecordCount"] + receipt["discardedObservationCount"]
        or receipt["discoveredRecordCount"] != receipt["inputObservationCount"] + receipt["failedRecordCount"]
    ):
        raise SourceNativeReleaseError("source-native receipt count equations differ")
    partition_counts = {
        kind: sum(value.member.record_count or 0 for value in partitions[kind]) for kind in PARTITION_KINDS
    }
    if (
        partition_counts[PARTITION_RECORDS] != receipt["publishedRecordCount"]
        or partition_counts[PARTITION_RENDITIONS] != receipt["renditionIndexCount"]
        or partition_counts[PARTITION_LEDGER] != receipt["publishedRecordCount"] + receipt["failedRecordCount"]
        or receipt["acquisitionEvidenceCount"] != len(by_role[ROLE_EVIDENCE])
    ):
        raise SourceNativeReleaseError("source-native receipt counts differ from payload membership")
    measurements = receipt["byteMeasurements"]
    payload_bytes = sum(member.byte_size for member in by_ref.values())
    if (
        measurements["payloadBytesRead"] != payload_bytes
        or measurements["payloadBytesReused"] > payload_bytes
        or measurements["payloadBytesWritten"] > payload_bytes
    ):
        raise SourceNativeReleaseError("source-native payload byte measurements do not reconcile")
    with source.open(ROOT_OBJECT_KEY) as stream:
        root_bytes = stream.read(MAX_ROW_BYTES + 1)
    if len(root_bytes) > MAX_ROW_BYTES:
        raise SourceNativeReleaseError("source-native root exceeds its product limit")
    publication_roles = {
        ROLE_SCOPES,
        ROLE_SCHEMA,
        ROLE_RELEASE_SCHEMA,
        ROLE_RECEIPT,
    }
    publication_bytes = (
        sum(member.byte_size for role in publication_roles for member in by_role[role])
        + sum(manifest.byte_size for manifest in artifact.manifests)
        + len(root_bytes)
    )
    if measurements["publicationBytesWritten"] != publication_bytes:
        raise SourceNativeReleaseError("source-native publication byte measurements do not reconcile")
    warnings = receipt.get("warnings")
    if not isinstance(warnings, list) or any(
        not isinstance(value, Mapping)
        or set(value) != {"code", "message"}
        or not isinstance(value.get("code"), str)
        or not value.get("code")
        or not isinstance(value.get("message"), str)
        or not value.get("message")
        for value in warnings
    ):
        raise SourceNativeReleaseError("source-native receipt warnings are not closed")
    if warnings != sorted(warnings, key=lambda value: (value["code"], value["message"])):
        raise SourceNativeReleaseError("source-native receipt warnings are not sorted")
    if profile.source_schema_key not in by_key or RELEASE_SCHEMA_KEY not in by_key:
        raise SourceNativeReleaseError("source-native schema members are absent")
    release_schemas = _read_one_json(source, RELEASE_SCHEMA_KEY)
    embedded_bundle_digest = schema_bundle_digest(release_schemas)
    if embedded_bundle_digest != spec["releaseSchemaDigest"]:
        raise SourceNativeReleaseError("release schema bundle digest differs from the spec")
    if embedded_bundle_digest not in KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS.values():
        raise SourceNativeReleaseError("release schema bundle is not one this project published")
    source_schema = _read_one_json(source, profile.source_schema_key)
    if source_schema != profile.source_schema:
        raise SourceNativeReleaseError(f"installed {profile.name} source schema differs")
    schema_set_digest = _digest_records(
        "spicyregs-source-schema-set/1",
        "schemas",
        [profile.source_schema_declaration()],
    )
    if schema_set_digest != spec["sourceNativeSchemaSetDigest"]:
        raise SourceNativeReleaseError("source-native schema-set digest differs")
