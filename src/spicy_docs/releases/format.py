"""Source-native release identities, closed shapes, and installed schemas."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Final, cast

from jsonschema import Draft202012Validator
from rulespec_artifacts import (
    Producer,
    Supersedes,
    VerifiedArtifact,
    canonical_json_bytes,
    parse_canonical_json,
)

KIND: Final = "spicyregs-source-native-release"
FORMAT: Final = "spicyregs-source-native-release"
FORMAT_VERSION: Final = "1.0"
RELEASE_SCHEMA_ID: Final = "urn:spicy-regs:schema:source-native-release:1.0"
VERIFIER_ID: Final = "urn:spicy-regs:source-native-release-verifier"
VERIFIER_VERSION: Final = "1.0"

#: Producer identities this release format recognizes: the historical
#: publisher (spicy-regs) and the current one (spicy-docs), which now owns
#: faithful acquisition and source-native publication. See the adoption note
#: atop docs/superpowers/specs/2026-08-25-source-native-release-spec.md.
SUPPORTED_PRODUCER_PRODUCTS: Final = frozenset({"spicy-regs", "spicy-docs"})
CURRENT_PRODUCER_PRODUCT: Final = "spicy-docs"
MAX_EVIDENCE_BYTES: Final = 24 * 1024 * 1024
MAX_ROW_BYTES: Final = 4 * 1024 * 1024
PARTITION_BUCKET_COUNT: Final = 64
PARTITION_ALGORITHM: Final = "sha256-utf8-modulo"

PARTITION_RECORDS: Final = "records"
PARTITION_RENDITIONS: Final = "renditions"
PARTITION_LEDGER: Final = "acquisition-records"
PARTITION_PAGES: Final = "acquisition-pages"
PARTITION_KINDS: Final = (
    PARTITION_LEDGER,
    PARTITION_PAGES,
    PARTITION_RECORDS,
    PARTITION_RENDITIONS,
)

ROLE_SCOPES: Final = "source-native-scopes"
ROLE_SCHEMA: Final = "source-native-schema"
ROLE_RECORDS: Final = "source-native-records"
ROLE_RENDITIONS: Final = "rendition-index"
ROLE_RELEASE_SCHEMA: Final = "release-schema"
ROLE_RECEIPT: Final = "source-publication-receipt"
ROLE_LEDGER: Final = "source-acquisition-ledger"
ROLE_EVIDENCE: Final = "source-acquisition-evidence"
PARTITION_ROLES: Final = {
    PARTITION_RECORDS: ROLE_RECORDS,
    PARTITION_RENDITIONS: ROLE_RENDITIONS,
    PARTITION_LEDGER: ROLE_LEDGER,
    PARTITION_PAGES: ROLE_LEDGER,
}
REQUIRED_ROLES: Final = frozenset(
    {
        ROLE_SCOPES,
        ROLE_SCHEMA,
        ROLE_RECORDS,
        ROLE_RENDITIONS,
        ROLE_RELEASE_SCHEMA,
        ROLE_RECEIPT,
        ROLE_LEDGER,
        ROLE_EVIDENCE,
    }
)
ALWAYS_REQUIRED_ROLES: Final = REQUIRED_ROLES - {ROLE_RECORDS, ROLE_RENDITIONS}

SCOPES_KEY: Final = "records/scopes.jsonl"
RELEASE_SCHEMA_KEY: Final = "schemas/source-native-release-1.0.json"
RECEIPT_KEY: Final = "receipts/publication.json"
MANIFEST_KEY: Final = "manifests/source-native.json"

SPEC_FIELDS: Final = frozenset(
    {
        "acquisitionPolicyDigest",
        "acquisitionPolicyId",
        "acquisitionPolicyVersion",
        "releaseSchemaDigest",
        "sourceNativeSchemaSetDigest",
        "sourceStateDigest",
        "sourceStateScope",
        "sourceSystemId",
        "sourceSystemVersion",
    }
)


class SourceNativeReleaseError(ValueError):
    """The source-native product rules refuse a release."""


@dataclass(frozen=True, slots=True)
class SourceNativeReleaseBuild:
    """Publication evidence supplied by the caller, not inferred from a worktree."""

    query_scope: Mapping[str, Any]
    producer: Producer
    started_at: str
    supersedes: Supersedes | None = None

    def __post_init__(self) -> None:
        _utc(self.started_at, "started_at")
        if self.producer.product not in SUPPORTED_PRODUCER_PRODUCTS:
            raise SourceNativeReleaseError(f"producer product must be one of {sorted(SUPPORTED_PRODUCER_PRODUCTS)}")
        if self.producer.verifier_id != VERIFIER_ID or self.producer.verifier_version != VERIFIER_VERSION:
            raise SourceNativeReleaseError("producer names an unsupported source-native verifier")


@dataclass(frozen=True, slots=True)
class PublishedSourceNativeRelease:
    root: Path
    artifact: VerifiedArtifact


def _utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SourceNativeReleaseError(f"{label} must be a canonical UTC instant")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise SourceNativeReleaseError(f"{label} is not a valid UTC instant") from error
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise SourceNativeReleaseError(f"{label} must use canonical UTC spelling")
    return parsed


def _now() -> datetime:
    return datetime.now(UTC)


def _instant(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise SourceNativeReleaseError("publisher clock must return a timezone-aware instant")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _closed_schema(properties: Mapping[str, Any], *, required: Sequence[str] | None = None) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": dict(properties),
        "required": list(required or properties),
        "type": "object",
    }


@dataclass(frozen=True, slots=True)
class _ClosedObjectShape:
    """One declaration for schema generation, writing, and structural parsing.

    ``required`` defaults to every declared property (today's closed-shape
    behaviour, unchanged). A shape may narrow it so a newly added property
    can be read from an old, already-published instance that never carried
    that key -- see ``_RECEIPT_SHAPE``, whose three failure-summary counts
    are optional for exactly this reason.
    """

    name: str
    properties: Mapping[str, Any]
    required: Sequence[str] | None = None

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(self.properties)

    @property
    def schema(self) -> dict[str, Any]:
        return _closed_schema(self.properties, required=self.required)

    def parse(self, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise SourceNativeReleaseError(f"{self.name} is not an object")
        errors = sorted(
            Draft202012Validator(self.schema).iter_errors(value),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if errors:
            where = "/".join(str(part) for part in errors[0].absolute_path)
            suffix = f" at {where}" if where else ""
            raise SourceNativeReleaseError(f"{self.name} structure differs{suffix}: {errors[0].message}")
        return dict(cast(Mapping[str, Any], value))

    def build(self, **values: Any) -> dict[str, Any]:
        return self.parse(values)


_NULLABLE_TEXT_SCHEMA: Final = {"type": ["string", "null"]}
_UINT_SCHEMA: Final = {"minimum": 0, "type": "integer"}
_DIGEST_SCHEMA: Final = {"pattern": "^sha256:[0-9a-f]{64}$", "type": "string"}
_NONEMPTY_TEXT_SCHEMA: Final = {"minLength": 1, "type": "string"}

#: The two failure classes a source-native release may record today. The
#: class boundary asks whether the identical, unchanged request would
#: plausibly succeed if retried -- a property of *this acquisition attempt*,
#: not of the item, so the same sourceRecordId can be "deterministic" in one
#: release and simply absent, having since succeeded, in the next. A value
#: outside this pair is treated as unclassed, never as a silent third kind of
#: "safe to publish".
FAILURE_CLASS_DETERMINISTIC: Final = "deterministic"
#: Why a record was recorded as failed rather than published. A stable
#: identifier, not the exception text: these are counted and aggregated
#: downstream, and every other reason code in this platform is a dotted
#: identifier. The exception message is deliberately not carried -- it varies
#: per record, can echo record content into a sealed artifact, and is
#: reproducible anyway, since the page's evidence blob is retained and
#: reclassifying those bytes raises the same error.
REASON_RECORD_UNCLASSIFIABLE: Final = "source.record-unclassifiable"
FAILURE_CLASS_TRANSIENT: Final = "transient"

#: Stands in for a sourceRecordId on a record that never reached
#: :func:`SourceNativeProfile.wrap_record` -- a record that fails
#: classification or scope validation has, by definition, no source-issued
#: identity this code can trust, which is exactly why it stopped there. See
#: :func:`_unclassified_source_record_id`.
_UNCLASSIFIED_RECORD_ID_PREFIX: Final = "unclassified"

#: One recorded acquisition-attempt failure. Structurally this is any
#: nonempty class/reasonCode with evidence of the attempt; which classes are
#: *publishable* is a semantic policy decision made by the reader and
#: verifier below, not by this shape.
_LEDGER_FAILURE_SCHEMA: Final = _closed_schema(
    {
        "class": _NONEMPTY_TEXT_SCHEMA,
        "evidenceDigest": _DIGEST_SCHEMA,
        "reasonCode": _NONEMPTY_TEXT_SCHEMA,
    }
)

_BYTE_MEASUREMENTS_SCHEMA: Final = _closed_schema(
    {
        "payloadBytesRead": _UINT_SCHEMA,
        "payloadBytesReused": _UINT_SCHEMA,
        "payloadBytesWritten": _UINT_SCHEMA,
        "publicationBytesWritten": _UINT_SCHEMA,
    }
)
_PARTITION_POLICY_SCHEMA: Final = _closed_schema(
    {
        "algorithm": {"const": PARTITION_ALGORITHM},
        "bucketCount": {"const": PARTITION_BUCKET_COUNT},
        "identityEncoding": {"const": "utf-8"},
    }
)
_PAYLOAD_PARTITION_SCHEMA: Final = _closed_schema(
    {
        "blobRef": _DIGEST_SCHEMA,
        "byteSize": _UINT_SCHEMA,
        "partitionId": {"pattern": "^[0-9]{2}$", "type": "string"},
        "partitionKind": {"enum": list(PARTITION_KINDS)},
        "recordCount": _UINT_SCHEMA,
    }
)

_PAGE_SHAPE: Final = _ClosedObjectShape(
    "acquisition page",
    {
        "accepted": {"type": "boolean"},
        "discoveredRecords": {"type": "array"},
        "evidenceMediaType": {"minLength": 1, "type": "string"},
        "evidenceBlobRef": _DIGEST_SCHEMA,
        "pageIndex": _UINT_SCHEMA,
        "requestKey": {"type": "string"},
        "recordsIncluded": {"type": "boolean"},
        "responseDigest": _DIGEST_SCHEMA,
        "sourceCursor": _NULLABLE_TEXT_SCHEMA,
        "terminal": {"type": "boolean"},
        "traversalIndex": _UINT_SCHEMA,
        "windowIndex": _UINT_SCHEMA,
        "windowPageIndex": _UINT_SCHEMA,
    },
)

#: The receipt's failure-summary counts are new and absent from every
#: already-published receipt, so they must stay optional in the schema
#: below -- see ``_RECEIPT_OPTIONAL_FIELDS``. Reader code treats an absent
#: count as zero, which reproduces an all-success receipt's summary exactly.
_RECEIPT_OPTIONAL_FIELDS: Final = frozenset(
    {"deterministicFailureCount", "transientFailureCount", "unclassedFailureCount"}
)

_RECEIPT_PROPERTIES: Final = {
    "acquisitionEvidenceCount": _UINT_SCHEMA,
    "acquisitionLedgerDigest": _DIGEST_SCHEMA,
    "acquisitionPolicyDigest": _DIGEST_SCHEMA,
    "byteMeasurements": _BYTE_MEASUREMENTS_SCHEMA,
    "completedAt": {"type": "string"},
    "deterministicFailureCount": _UINT_SCHEMA,
    "discoveredRecordCount": _UINT_SCHEMA,
    "discardedObservationCount": _UINT_SCHEMA,
    "failedRecordCount": _UINT_SCHEMA,
    "format": {"type": "string"},
    "formatVersion": {"type": "string"},
    "inputObservationCount": _UINT_SCHEMA,
    "inputObservationDigest": _DIGEST_SCHEMA,
    "partitionPolicy": _PARTITION_POLICY_SCHEMA,
    "payloadPartitions": {
        "items": _PAYLOAD_PARTITION_SCHEMA,
        "maxItems": len(PARTITION_KINDS) * PARTITION_BUCKET_COUNT,
        "type": "array",
    },
    "publishedRecordCount": _UINT_SCHEMA,
    "reconciliationDigest": _DIGEST_SCHEMA,
    "reconciliationPassCount": _UINT_SCHEMA,
    "releaseSchemaDigest": _DIGEST_SCHEMA,
    "releaseSchemaId": {"type": "string"},
    "renditionIndexCount": _UINT_SCHEMA,
    "semanticVerdict": {"const": "pass"},
    "sourceNativeSchemaSetDigest": _DIGEST_SCHEMA,
    "sourceStateDigest": _DIGEST_SCHEMA,
    "sourceStateScope": {"type": "string"},
    "sourceSystemId": {"type": "string"},
    "startedAt": {"type": "string"},
    "transientFailureCount": _UINT_SCHEMA,
    "unclassedFailureCount": _UINT_SCHEMA,
    "verifierId": {"type": "string"},
    "verifierImplementationId": {"type": "string"},
    "verifierVersion": {"type": "string"},
    "warnings": {"type": "array"},
}

_RECEIPT_SHAPE: Final = _ClosedObjectShape(
    "publication receipt",
    _RECEIPT_PROPERTIES,
    required=tuple(name for name in _RECEIPT_PROPERTIES if name not in _RECEIPT_OPTIONAL_FIELDS),
)


def release_schema_bundle() -> dict[str, Mapping[str, Any]]:
    """Return the installed, closed product schema family used by the publisher."""

    nullable_text = _NULLABLE_TEXT_SCHEMA
    digest = _DIGEST_SCHEMA
    schemas: dict[str, Mapping[str, Any]] = {
        "source-native-record.schema.json": _closed_schema(
            {
                "fieldDiagnostics": {"type": "array"},
                "record": {"type": "object"},
                "schemaDigest": digest,
                "schemaName": {"type": "string"},
                "schemaVersion": {"type": "string"},
                "scopeId": {"type": "string"},
                "sourceRecordId": {"type": "string"},
            }
        ),
        "scope.schema.json": _closed_schema(
            {
                "fields": {"type": "object"},
                "scopeId": {"type": "string"},
                "scopeKind": {"type": "string"},
                "sourceSystemId": {"type": "string"},
            }
        ),
        "source-schema-declaration.schema.json": _closed_schema(
            {
                "schemaDigest": digest,
                "schemaName": {"type": "string"},
                "schemaVersion": {"type": "string"},
            }
        ),
        "rendition-index.schema.json": _closed_schema(
            {
                "expectedByteSize": {"type": ["integer", "null"]},
                "expectedSha256": {"type": ["string", "null"]},
                "locator": nullable_text,
                "mediaType": {"type": "string"},
                "renditionId": {"type": "string"},
                "sourceField": {"type": "string"},
                "sourceRecordId": {"type": "string"},
            }
        ),
        "acquisition-ledger.schema.json": _closed_schema(
            {
                "evidenceBlobRef": digest,
                "failure": {"oneOf": [{"type": "null"}, _LEDGER_FAILURE_SCHEMA]},
                "observationRef": {"type": "object"},
                "sourceRecordId": {"type": "string"},
            }
        ),
        "acquisition-page.schema.json": _PAGE_SHAPE.schema,
        "failure.schema.json": _closed_schema(
            {
                "code": {"type": "string"},
                "evidenceDigest": digest,
                "stage": {"type": "string"},
            }
        ),
        "publication-receipt.schema.json": _RECEIPT_SHAPE.schema,
        "release.schema.json": _closed_schema(
            {
                "acquisitionPolicyDigest": digest,
                "acquisitionPolicyId": {"type": "string"},
                "acquisitionPolicyVersion": {"type": "string"},
                "releaseSchemaDigest": digest,
                "sourceNativeSchemaSetDigest": digest,
                "sourceStateDigest": digest,
                "sourceStateScope": {"type": "string"},
                "sourceSystemId": {"type": "string"},
                "sourceSystemVersion": {"type": "string"},
            }
        ),
    }
    return schemas


#: Release schema bundles this project has published under, newest last, as
#: literal digests. A release embeds the bundle it was built with; admission
#: accepts any bundle named here, not only the one today's code generates.
#:
#: Without this, widening any schema makes every already-published release
#: inadmissible: the check below used to require byte-equality with
#: ``installed_release_schema_bundle()``. Measured when the acquisition-ledger
#: ``failure`` shape widened -- 668 published releases embed
#: ``sha256:a7e0dba5...`` and would all have been refused by the code that had
#: just been upgraded to read them.
#:
#: Every entry is a LITERAL, deliberately. An entry computed from the installed
#: schema files is not a historical record: it moves when those files move, so
#: the first release built under a widened schema would silently redefine the
#: version it was meant to preserve, and the releases the table exists to admit
#: would be refused again under the table's own error. The same trap was hit
#: twice in ``ACCEPTED_DOCUMENT_FIELD_SETS`` before that table was written this
#: way. Add an entry; never edit one a release was published under.
KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS: Final[Mapping[str, str]] = {
    # Pre-failure-shape. 668 releases published under this bundle.
    "1.0": "sha256:a7e0dba5e0b26f69ad3a41901a08eb158d21eb59b856f9faf83d48640a85abdb",
    # Acquisition-ledger ``failure`` widened to permit a recorded failure, and
    # the receipt gained the optional per-class failure counts.
    "1.1": "sha256:4c32416532f34a8bb7fbb4009c6324881495b9a6038c61931f8cf05694e1e164",
}


def installed_release_schema_bundle() -> dict[str, Mapping[str, Any]]:
    """Load the shipped schemas and refuse drift from their sole generator."""

    expected = release_schema_bundle()
    root = files("spicy_docs").joinpath("schemas/source_native_release/1.0")
    try:
        observed_names = {entry.name for entry in root.iterdir() if entry.is_file()}
    except FileNotFoundError as error:
        raise SourceNativeReleaseError("installed source-native schema bundle is missing") from error
    if observed_names != set(expected):
        raise SourceNativeReleaseError("installed source-native schema membership differs")
    installed: dict[str, Mapping[str, Any]] = {}
    for name, generated in expected.items():
        payload = root.joinpath(name).read_bytes()
        if payload != canonical_json_bytes(generated):
            raise SourceNativeReleaseError(f"installed source-native schema differs at {name}")
        value = parse_canonical_json(payload, path=f"installed/{name}")
        if not isinstance(value, Mapping):
            raise SourceNativeReleaseError(f"installed source-native schema is not an object at {name}")
        installed[name] = value
    return installed


#: Acquisition policy versions each policy has published under, as literals.
#: A release records the policy version it was acquired under; admission used to
#: require that to equal the version the running code declares, so bumping a
#: policy made every release published under the previous one inadmissible --
#: found when a rebuild could not admit the release holding the evidence it was
#: replaying. A release acquired under 1.0 IS a 1.0 release: that is a fact about
#: how it was acquired, not a defect to refuse.
#:
#: Third instance of one assumption, not a third bug: the stored-request field
#: list and the embedded schema bundle had the same defect and the same remedy.
#: Literal entries for the same reason those tables are literal -- an entry
#: computed from the live profile is not a history, because it moves when the
#: profile moves. A policy id absent here keeps the old exact-match behaviour.
#:
#: Which fields belong in a table like this, and which correctly do not: ask
#: whether the field says *which thing this is* or *how this one was made*.
#: sourceSystemId and acquisitionPolicyId are identifiers -- a release naming a
#: different source system is a different kind of release, and exact-match
#: against the live profile is the right check for them forever. Versions and
#: scope declarations describe how one release was produced, and those
#: legitimately change over time while every release made under the old value
#: stays valid; those are the ones that need an accepted history rather than a
#: comparison against today's value.
#:
#: KNOWINGLY LEFT IN PLACE: by that rule the same identity block still checks
#: two fields the wrong way -- sourceSystemVersion and sourceStateScope -- so
#: either one moving would repeat this. Fixing that surface once, rather than
#: adding a fourth table, is its own change with its own review; the decision to
#: defer it is recorded in this commit's message, not left as an oversight.
KNOWN_ACQUISITION_POLICY_VERSIONS: Final[Mapping[str, frozenset[str]]] = {
    # 1.0 published the Federal Register corpus on disk; 1.1 is composite
    # identity, (document_number, publication_date).
    "urn:spicy-regs:acquisition:federal-register-paginated": frozenset({"1.0", "1.1"}),
}
