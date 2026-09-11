"""Independent sealed fixtures for failure provenance and bounded admission.

Build through Rulespec primitives rather than the SpicyDocs publisher: the
verifier must reject false claims even when all hashes and counts agree.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from rulespec_artifacts import (
    ROOT_OBJECT_KEY,
    FramedSection,
    LocalBlobSource,
    LocalMemberSource,
    MemberManifestReference,
    Producer,
    admit_artifact,
    build_artifact_root,
    canonical_json_bytes,
    describe_member_from_receipt,
    framed_section_digest,
    schema_bundle_digest,
)

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.source_native import (
    FAILURE_CLASS_DETERMINISTIC,
    FAILURE_CLASS_TRANSIENT,
    FORMAT,
    FORMAT_VERSION,
    KIND,
    MANIFEST_KEY,
    PARTITION_BUCKET_COUNT,
    PARTITION_LEDGER,
    PARTITION_PAGES,
    PARTITION_RECORDS,
    PARTITION_ROLES,
    RECEIPT_KEY,
    RELEASE_SCHEMA_ID,
    RELEASE_SCHEMA_KEY,
    ROLE_EVIDENCE,
    ROLE_RECEIPT,
    ROLE_RELEASE_SCHEMA,
    ROLE_SCHEMA,
    ROLE_SCOPES,
    SCOPES_KEY,
    VERIFIER_ID,
    VERIFIER_VERSION,
    SourceNativeReleaseError,
    release_schema_bundle,
    verify_source_native_admission,
    verify_source_native_release,
)

IMPLEMENTATION_ID: Final = "git+https://example.test/spicy-docs@" + "b" * 40
_SOURCE_SCHEMA_KEY: Final = "schemas/fixture-source.json"
_SOURCE_SCHEMA: Final = {"$id": "urn:spicy-docs-test:fixture-source:1", "type": "object"}


def _source_schema_digest() -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(_SOURCE_SCHEMA)).hexdigest()


def _source_schema_declaration() -> dict[str, str]:
    return {
        "schemaDigest": _source_schema_digest(),
        "schemaName": "fixture-source",
        "schemaVersion": "1",
    }


def _acquisition_policy(query_scope: Mapping[str, Any]) -> dict[str, Any]:
    return {"scope": dict(query_scope)}


def _validate_query_scope(fields: Mapping[str, Any]) -> Mapping[str, Any]:
    return dict(fields)


def _parse_page_response(data: bytes) -> Mapping[str, Any]:
    return json.loads(data)


def _next_page(response: Mapping[str, Any], *, seen_urls: set[str]) -> str | None:
    del response, seen_urls
    return None


def _records_included(
    response: Mapping[str, Any], *, query_scope: Mapping[str, Any], page_window: object | None
) -> bool:
    del response, query_scope, page_window
    return True


def _classify_record(record: object) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        raise TypeError("fixture record must be an object")
    if "id" not in record:
        raise ValueError("fixture record lacks id")
    return record


def _wrap_record(record: Mapping[str, Any], *, schema_digest: str) -> Mapping[str, Any]:
    return {
        "fieldDiagnostics": [],
        "record": dict(record),
        "schemaDigest": schema_digest,
        "schemaName": "fixture-source",
        "schemaVersion": "1",
        "scopeId": "fixture-scope",
        "sourceRecordId": record["id"],
    }


def _record_digest(record: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def _rendition_rows(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    del record
    return ()


def _validate_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    del record, query_scope, page_window


class _NoOpTraversalCheck:
    def add(self, response: Mapping[str, Any], *, page_index: int) -> None:
        del response, page_index

    def finish(self) -> None:
        pass


class _NoOpAcquisitionCheck:
    def add_window(
        self,
        response: Mapping[str, Any],
        *,
        page_window: object | None,
        records_included: bool,
        response_bytes: bytes,
    ) -> None:
        del response, page_window, records_included, response_bytes

    def finish(self, *, query_scope: Mapping[str, Any]) -> None:
        del query_scope


#: A minimal, test-local profile: one traversal, trivial classify/wrap, no
#: renditions. It exists only so the verifier's full acquisition replay has
#: something to replay; records without identities fail classification.
FIXTURE_PROFILE: Final = SourceNativeProfile(
    name="fixture",
    source_system_id="fixture-system",
    source_system_version="1",
    acquisition_policy_id="fixture-policy",
    acquisition_policy_version="1",
    scope_id="fixture-scope",
    source_schema_key=_SOURCE_SCHEMA_KEY,
    source_schema=_SOURCE_SCHEMA,
    record_stem="record",
    max_traversals=1,
    source_state_scope="observed-crawl",
    traversal_acceptance="single-observed-traversal",
    acquisition_policy=_acquisition_policy,
    validate_query_scope=_validate_query_scope,
    parse_page_response=_parse_page_response,
    next_page=_next_page,
    traversal_check=_NoOpTraversalCheck,
    classify_record=_classify_record,
    wrap_record=_wrap_record,
    record_digest=_record_digest,
    rendition_rows=_rendition_rows,
    source_schema_declaration=_source_schema_declaration,
    source_schema_digest=_source_schema_digest,
    validate_record_scope=_validate_record_scope,
    records_included=_records_included,
    acquisition_check=_NoOpAcquisitionCheck,
)


def _record_bucket(identity: str) -> str:
    """The same sha256-utf8-modulo bucketing the partition policy declares."""

    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return f"{int.from_bytes(digest, 'big') % PARTITION_BUCKET_COUNT:02d}"


def _page_bucket(traversal: int, page: int) -> str:
    return _record_bucket(f"{traversal}:{page}")


def _write_blob(blobs_root: Path, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    directory = blobs_root / "sha256"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / digest
    if not path.exists():
        path.write_bytes(payload)
    return f"sha256:{digest}"


def _jsonl_bytes(rows: list[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _write_partition(
    blobs_root: Path,
    rows: list[Mapping[str, Any]],
    *,
    bucket_of: Any,
    sort_key: Any,
) -> list[tuple[str, str, int, int]]:
    """Bucket rows the way the partition policy requires and write one blob
    per used bucket. Returns (partitionId, blobRef, byteSize, recordCount).
    """

    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(bucket_of(row), []).append(row)
    entries: list[tuple[str, str, int, int]] = []
    for partition_id in sorted(buckets):
        ordered = sorted(buckets[partition_id], key=sort_key)
        payload = _jsonl_bytes(ordered)
        blob_ref = _write_blob(blobs_root, payload)
        entries.append((partition_id, blob_ref, len(payload), len(ordered)))
    return entries


def _failure(class_: str, reason_code: str) -> dict[str, str]:
    return {
        "class": class_,
        "evidenceDigest": "sha256:" + hashlib.sha256(f"evidence:{reason_code}".encode()).hexdigest(),
        "reasonCode": reason_code,
    }


def _failure_row(source_record_id: str, class_: str, reason_code: str) -> dict[str, Any]:
    return {
        "evidenceBlobRef": "sha256:" + hashlib.sha256(f"attempt:{source_record_id}".encode()).hexdigest(),
        "failure": _failure(class_, reason_code),
        "observationRef": {"sourceRecordId": source_record_id},
        "sourceRecordId": source_record_id,
    }


def _build_release(
    tmp_path: Path,
    *,
    published_id: str | None = None,
    failure_rows: Sequence[Mapping[str, Any]] | None = None,
    rejected_records: int = 0,
    mutate_failures: Callable[[list[Mapping[str, Any]]], list[Mapping[str, Any]]] | None = None,
    failed_record_count: int | None = None,
    deterministic_failure_count: int | None = None,
    transient_failure_count: int | None = None,
    unclassed_failure_count: int | None = None,
    mutate_receipt: Callable[[dict[str, Any]], None] | None = None,
    mutate_spec: Callable[[dict[str, Any]], None] | None = None,
    release_schemas: Mapping[str, Any] | None = None,
    producer: Producer | None = None,
) -> tuple[Path, Path]:
    """Hand-assemble one source-native release: at most one published
    record plus whatever ``failure_rows`` the caller wants recorded in the
    acquisition ledger. The four count overrides let a test make the
    receipt's own summary lie about what the ledger actually holds.
    """

    release_root = tmp_path / "release"
    blobs_root = tmp_path / "blobs"
    release_root.mkdir(parents=True)

    results = [{"id": published_id}] if published_id is not None else []
    results.extend({"invalid": index} for index in range(rejected_records))
    response_bytes = json.dumps({"results": results}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    evidence_ref = _write_blob(blobs_root, response_bytes)

    discovered: list[dict[str, Any]] = []
    record_rows: list[Mapping[str, Any]] = []
    success_ledger_rows: list[Mapping[str, Any]] = []
    rejected_rows: list[Mapping[str, Any]] = []
    for index, raw in enumerate(results):
        if "id" not in raw:
            identity = f"unclassified:0:0:{index}"
            rejected_rows.append(
                {
                    "evidenceBlobRef": evidence_ref,
                    "failure": {
                        "class": "deterministic",
                        "reasonCode": "source.record-unclassifiable",
                        "evidenceDigest": evidence_ref,
                    },
                    "observationRef": {"sourceRecordId": identity},
                    "sourceRecordId": identity,
                }
            )
            continue
        classified = _classify_record(raw)
        digest = _record_digest(classified)
        discovered.append({"recordDigest": digest, "sourceRecordId": raw["id"]})
        record_rows.append(_wrap_record(classified, schema_digest=_source_schema_digest()))
        success_ledger_rows.append(
            {
                "evidenceBlobRef": evidence_ref,
                "failure": None,
                "observationRef": {"sourceRecordId": raw["id"]},
                "sourceRecordId": raw["id"],
            }
        )

    page_row = {
        "accepted": True,
        "discoveredRecords": discovered,
        "evidenceMediaType": "application/json",
        "evidenceBlobRef": evidence_ref,
        "pageIndex": 0,
        "requestKey": "fixture://page-0",
        "recordsIncluded": True,
        "responseDigest": evidence_ref,
        "sourceCursor": None,
        "terminal": True,
        "traversalIndex": 0,
        "windowIndex": 0,
        "windowPageIndex": 0,
    }

    pages_entries = _write_partition(
        blobs_root,
        [page_row],
        bucket_of=lambda row: _page_bucket(row["traversalIndex"], row["pageIndex"]),
        sort_key=lambda row: (row["traversalIndex"], row["pageIndex"]),
    )
    failure_rows = list(rejected_rows if failure_rows is None else failure_rows)
    if mutate_failures is not None:
        failure_rows = mutate_failures(failure_rows)
    all_ledger_rows = [*success_ledger_rows, *failure_rows]
    ledger_entries = _write_partition(
        blobs_root,
        all_ledger_rows,
        bucket_of=lambda row: _record_bucket(row["sourceRecordId"]),
        sort_key=lambda row: row["sourceRecordId"],
    )
    records_entries = (
        _write_partition(
            blobs_root,
            record_rows,
            bucket_of=lambda row: _record_bucket(row["sourceRecordId"]),
            sort_key=lambda row: row["sourceRecordId"],
        )
        if record_rows
        else []
    )

    def _partition_members(
        entries: list[tuple[str, str, int, int]],
        *,
        kind: str,
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        members = []
        receipt_entries = []
        for partition_id, blob_ref, byte_size, record_count in entries:
            members.append(
                describe_member_from_receipt(
                    blob_ref=blob_ref,
                    role=PARTITION_ROLES[kind],
                    media_type="application/x-ndjson",
                    byte_size=byte_size,
                    record_count=record_count,
                )
            )
            receipt_entries.append(
                {
                    "blobRef": blob_ref,
                    "byteSize": byte_size,
                    "partitionId": partition_id,
                    "partitionKind": kind,
                    "recordCount": record_count,
                }
            )
        return members, receipt_entries

    pages_members, pages_receipt_entries = _partition_members(pages_entries, kind=PARTITION_PAGES)
    ledger_members, ledger_receipt_entries = _partition_members(ledger_entries, kind=PARTITION_LEDGER)
    records_members, records_receipt_entries = _partition_members(records_entries, kind=PARTITION_RECORDS)

    evidence_member = describe_member_from_receipt(
        blob_ref=evidence_ref,
        role=ROLE_EVIDENCE,
        media_type="application/json",
        byte_size=len(response_bytes),
    )
    external_members = (*pages_members, *ledger_members, *records_members, evidence_member)

    scope_row = {
        "fields": {},
        "scopeId": "fixture-scope",
        "scopeKind": "source-collection",
        "sourceSystemId": "fixture-system",
    }
    scopes_bytes = canonical_json_bytes(scope_row) + b"\n"
    source_schema_bytes = canonical_json_bytes(_SOURCE_SCHEMA)
    release_schemas = release_schema_bundle() if release_schemas is None else release_schemas
    release_schema_bytes = canonical_json_bytes(release_schemas)

    scopes_member = describe_member_from_receipt(
        object_key=SCOPES_KEY,
        sha256="sha256:" + hashlib.sha256(scopes_bytes).hexdigest(),
        role=ROLE_SCOPES,
        media_type="application/x-ndjson",
        byte_size=len(scopes_bytes),
        record_count=1,
    )
    source_schema_member = describe_member_from_receipt(
        object_key=_SOURCE_SCHEMA_KEY,
        sha256="sha256:" + hashlib.sha256(source_schema_bytes).hexdigest(),
        role=ROLE_SCHEMA,
        media_type="application/schema+json",
        byte_size=len(source_schema_bytes),
        schema_id=str(_SOURCE_SCHEMA["$id"]),
    )
    release_schema_member = describe_member_from_receipt(
        object_key=RELEASE_SCHEMA_KEY,
        sha256="sha256:" + hashlib.sha256(release_schema_bytes).hexdigest(),
        role=ROLE_RELEASE_SCHEMA,
        media_type="application/schema+json",
        byte_size=len(release_schema_bytes),
        schema_id=RELEASE_SCHEMA_ID,
    )

    policy = _acquisition_policy({})
    policy_digest = framed_section_digest("spicyregs-acquisition-policy/1", (FramedSection("policy", 1, (policy,)),))
    schema_declaration = _source_schema_declaration()
    schema_set_digest = framed_section_digest(
        "spicyregs-source-schema-set/1",
        (FramedSection("schemas", 1, (schema_declaration,)),),
    )
    sorted_records = sorted(record_rows, key=lambda row: row["sourceRecordId"])
    state_digest = framed_section_digest(
        "spicyregs-source-state/1",
        (
            FramedSection("scopes", 1, (scope_row,)),
            FramedSection("schemas", 1, (schema_declaration,)),
            FramedSection("records", len(sorted_records), sorted_records),
            FramedSection("renditions", 0, ()),
        ),
    )
    input_digest = framed_section_digest(
        "spicyregs-input-observations/1",
        (FramedSection("observations", len(sorted_records), sorted_records),),
    )
    sorted_ledger_rows = sorted(all_ledger_rows, key=lambda row: row["sourceRecordId"])
    ledger_digest = framed_section_digest(
        "spicyregs-acquisition-ledger/1",
        (FramedSection("entries", len(sorted_ledger_rows), sorted_ledger_rows),),
    )
    reconciliation_digest = framed_section_digest(
        "spicyregs-source-reconciliation/1",
        (FramedSection("pages", 1, (page_row,)),),
    )

    published_count = len(record_rows)
    total_failed = len(failure_rows)
    resolved_failed = total_failed if failed_record_count is None else failed_record_count
    resolved_deterministic = (
        sum(1 for row in failure_rows if row["failure"]["class"] == FAILURE_CLASS_DETERMINISTIC)
        if deterministic_failure_count is None
        else deterministic_failure_count
    )
    resolved_transient = (
        sum(1 for row in failure_rows if row["failure"]["class"] == FAILURE_CLASS_TRANSIENT)
        if transient_failure_count is None
        else transient_failure_count
    )
    resolved_unclassed = (
        sum(
            1
            for row in failure_rows
            if row["failure"]["class"] not in {FAILURE_CLASS_DETERMINISTIC, FAILURE_CLASS_TRANSIENT}
        )
        if unclassed_failure_count is None
        else unclassed_failure_count
    )

    receipt: dict[str, Any] = {
        "acquisitionEvidenceCount": 1,
        "acquisitionLedgerDigest": ledger_digest,
        "acquisitionPolicyDigest": policy_digest,
        "completedAt": "2026-09-01T00:00:01Z",
        "deterministicFailureCount": resolved_deterministic,
        "discardedObservationCount": 0,
        "discoveredRecordCount": published_count + resolved_failed,
        "failedRecordCount": resolved_failed,
        "format": FORMAT,
        "formatVersion": FORMAT_VERSION,
        "inputObservationCount": published_count,
        "inputObservationDigest": input_digest,
        "partitionPolicy": {
            "algorithm": "sha256-utf8-modulo",
            "bucketCount": PARTITION_BUCKET_COUNT,
            "identityEncoding": "utf-8",
        },
        "payloadPartitions": [*pages_receipt_entries, *ledger_receipt_entries, *records_receipt_entries],
        "publishedRecordCount": published_count,
        "reconciliationDigest": reconciliation_digest,
        "reconciliationPassCount": 1,
        "releaseSchemaDigest": schema_bundle_digest(release_schemas),
        "releaseSchemaId": RELEASE_SCHEMA_ID,
        "renditionIndexCount": 0,
        "semanticVerdict": "pass",
        "sourceNativeSchemaSetDigest": schema_set_digest,
        "sourceStateDigest": state_digest,
        "sourceStateScope": "observed-crawl",
        "sourceSystemId": "fixture-system",
        "startedAt": "2026-09-01T00:00:00Z",
        "transientFailureCount": resolved_transient,
        "unclassedFailureCount": resolved_unclassed,
        "verifierId": VERIFIER_ID,
        "verifierImplementationId": IMPLEMENTATION_ID,
        "verifierVersion": VERIFIER_VERSION,
        "warnings": [],
    }
    spec = {
        "acquisitionPolicyDigest": policy_digest,
        "acquisitionPolicyId": "fixture-policy",
        "acquisitionPolicyVersion": "1",
        "releaseSchemaDigest": schema_bundle_digest(release_schemas),
        "sourceNativeSchemaSetDigest": schema_set_digest,
        "sourceStateDigest": state_digest,
        "sourceStateScope": "observed-crawl",
        "sourceSystemId": "fixture-system",
        "sourceSystemVersion": "1",
    }
    producer = producer or Producer(
        product="spicy-docs",
        implementation_id=IMPLEMENTATION_ID,
        verifier_id=VERIFIER_ID,
        verifier_version=VERIFIER_VERSION,
        verifier_implementation_id=IMPLEMENTATION_ID,
    )

    if mutate_receipt is not None:
        mutate_receipt(receipt)
    if mutate_spec is not None:
        mutate_spec(spec)
    receipt_bytes = canonical_json_bytes(receipt)
    receipt_member = describe_member_from_receipt(
        object_key=RECEIPT_KEY,
        sha256="sha256:" + hashlib.sha256(receipt_bytes).hexdigest(),
        role=ROLE_RECEIPT,
        media_type="application/json",
        byte_size=len(receipt_bytes),
    )
    local_members = (scopes_member, receipt_member, release_schema_member, source_schema_member)
    manifest, manifest_bytes = MemberManifestReference.for_members(
        scope_kind="global",
        scope_id="source-native",
        object_key=MANIFEST_KEY,
        members=(*local_members, *external_members),
    )
    root = build_artifact_root(kind=KIND, spec=spec, producer=producer, manifests=(manifest,))
    root_bytes = canonical_json_bytes(root)

    def _write_local(relative_key: str, payload: bytes) -> None:
        path = release_root / relative_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    _write_local(SCOPES_KEY, scopes_bytes)
    _write_local(_SOURCE_SCHEMA_KEY, source_schema_bytes)
    _write_local(RELEASE_SCHEMA_KEY, release_schema_bytes)
    _write_local(RECEIPT_KEY, receipt_bytes)
    _write_local(MANIFEST_KEY, manifest_bytes)
    _write_local(ROOT_OBJECT_KEY, root_bytes)
    return release_root, blobs_root


def _admit(
    release_root: Path, blobs_root: Path, verifier: Any, *, profile: SourceNativeProfile = FIXTURE_PROFILE
) -> Any:
    blob_source = LocalBlobSource(blobs_root)
    return admit_artifact(
        LocalMemberSource(release_root),
        blob_source=blob_source,
        semantic_verifier=lambda artifact, source: verifier(
            artifact,
            source,
            profile=profile,
            blob_source=blob_source,
        ),
    )


@pytest.mark.parametrize("published_id", [None, "fixture-ok"])
def test_replayed_deterministic_failures_are_accepted(tmp_path: Path, published_id: str | None) -> None:
    release_root, blobs_root = _build_release(tmp_path, published_id=published_id, rejected_records=2)
    _admit(release_root, blobs_root, verify_source_native_admission)
    _admit(release_root, blobs_root, verify_source_native_release)


def test_fabricated_deterministic_failure_is_refused_by_replay(tmp_path: Path) -> None:
    release_root, blobs_root = _build_release(
        tmp_path, failure_rows=[_failure_row("fixture-not-fetched", FAILURE_CLASS_DETERMINISTIC, "not-found")]
    )
    _admit(release_root, blobs_root, verify_source_native_admission)
    with pytest.raises(SourceNativeReleaseError, match="ledger differs from replayed evidence"):
        _admit(release_root, blobs_root, verify_source_native_release)


def test_transient_failure_is_refused(tmp_path: Path) -> None:
    failures = [
        _failure_row("fixture-det-1", FAILURE_CLASS_DETERMINISTIC, "not-found"),
        _failure_row("fixture-transient-1", FAILURE_CLASS_TRANSIENT, "timeout"),
    ]
    release_root, blobs_root = _build_release(tmp_path, failure_rows=failures)

    with pytest.raises(SourceNativeReleaseError, match="transient"):
        _admit(release_root, blobs_root, verify_source_native_admission)
    with pytest.raises(SourceNativeReleaseError, match="transient"):
        _admit(release_root, blobs_root, verify_source_native_release)


def test_unclassed_failure_is_refused(tmp_path: Path) -> None:
    failures = [
        _failure_row("fixture-det-1", FAILURE_CLASS_DETERMINISTIC, "not-found"),
        _failure_row("fixture-unclassed-1", "quantum-interference", "unexplained"),
    ]
    release_root, blobs_root = _build_release(tmp_path, failure_rows=failures)

    with pytest.raises(SourceNativeReleaseError, match="unclassed"):
        _admit(release_root, blobs_root, verify_source_native_admission)
    with pytest.raises(SourceNativeReleaseError, match="unclassed"):
        _admit(release_root, blobs_root, verify_source_native_release)


def test_transient_and_unclassed_refusals_are_distinguishable(tmp_path: Path) -> None:
    transient_root, transient_blobs = _build_release(
        tmp_path / "transient",
        failure_rows=[_failure_row("fixture-transient-1", FAILURE_CLASS_TRANSIENT, "timeout")],
    )
    unclassed_root, unclassed_blobs = _build_release(
        tmp_path / "unclassed",
        failure_rows=[_failure_row("fixture-unclassed-1", "quantum-interference", "unexplained")],
    )

    with pytest.raises(SourceNativeReleaseError) as transient_error:
        _admit(transient_root, transient_blobs, verify_source_native_admission)
    with pytest.raises(SourceNativeReleaseError) as unclassed_error:
        _admit(unclassed_root, unclassed_blobs, verify_source_native_admission)

    assert str(transient_error.value) != str(unclassed_error.value)
    assert "transient" in str(transient_error.value)
    assert "unclassed" in str(unclassed_error.value)


def test_receipt_summary_not_summing_to_failed_record_count_is_refused(tmp_path: Path) -> None:
    """Even before touching the ledger, admission checks the receipt's own
    three counts sum to its own ``failedRecordCount`` -- a cheap, purely
    arithmetic self-consistency check distinct from the verifier's proof
    that the summary matches the real ledger contents.
    """

    failures = [
        _failure_row("fixture-det-1", FAILURE_CLASS_DETERMINISTIC, "not-found"),
        _failure_row("fixture-det-2", FAILURE_CLASS_DETERMINISTIC, "not-found"),
    ]
    release_root, blobs_root = _build_release(
        tmp_path,
        failure_rows=failures,
        failed_record_count=2,
        deterministic_failure_count=1,
        transient_failure_count=0,
        unclassed_failure_count=0,
    )

    with pytest.raises(SourceNativeReleaseError, match="does not reconcile with failedRecordCount"):
        _admit(release_root, blobs_root, verify_source_native_admission)


def test_zero_count_null_failure_release_reads_unchanged(tmp_path: Path) -> None:
    """A successful release still passes both admission and full replay."""

    release_root, blobs_root = _build_release(tmp_path, published_id="fixture-ok-only")

    _admit(release_root, blobs_root, verify_source_native_admission)
    _admit(release_root, blobs_root, verify_source_native_release)


@pytest.mark.parametrize(
    "change", ["omit", "inject", "duplicate", "identity", "observation", "reason", "evidence", "page-link", "class"]
)
def test_consistently_sealed_failure_tampering_is_refused(tmp_path: Path, change: str) -> None:
    def mutate(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        rows = json.loads(json.dumps(rows))
        if change == "omit":
            return rows[1:]
        if change in {"inject", "duplicate"}:
            extra = json.loads(json.dumps(rows[0]))
            if change == "inject":
                extra["sourceRecordId"] = "unclassified:0:0:99"
                extra["observationRef"]["sourceRecordId"] = extra["sourceRecordId"]
            return [*rows, extra]
        row = rows[0]
        if change == "identity":
            row["sourceRecordId"] = "unclassified:0:0:99"
            row["observationRef"]["sourceRecordId"] = row["sourceRecordId"]
        elif change == "observation":
            row["observationRef"]["sourceRecordId"] = "unclassified:0:0:99"
        elif change == "reason":
            row["failure"]["reasonCode"] = "not-found"
        elif change == "evidence":
            row["failure"]["evidenceDigest"] = "sha256:" + "a" * 64
        elif change == "page-link":
            row["evidenceBlobRef"] = "sha256:" + "a" * 64
        elif change == "class":
            row["failure"]["class"] = "transient"
        return rows

    release_root, blobs_root = _build_release(
        tmp_path,
        published_id="fixture-ok",
        rejected_records=2,
        mutate_failures=mutate,
        # A lying class must pass the arithmetic admission gate so replay has
        # to establish its meaning. All remaining counters/hashes are rebuilt.
        deterministic_failure_count=2 if change == "class" else None,
        transient_failure_count=0 if change == "class" else None,
    )
    _admit(release_root, blobs_root, verify_source_native_admission)
    with pytest.raises(SourceNativeReleaseError, match="ledger differs from replayed evidence|partition is unordered"):
        _admit(release_root, blobs_root, verify_source_native_release)


@pytest.mark.parametrize("field", ["deterministicFailureCount", "transientFailureCount", "unclassedFailureCount"])
def test_missing_failure_summary_count_is_refused_even_with_zero_failures(tmp_path: Path, field: str) -> None:
    def omit(receipt: dict[str, Any]) -> None:
        del receipt[field]

    release_root, blobs_root = _build_release(tmp_path, mutate_receipt=omit)
    with pytest.raises(SourceNativeReleaseError, match=f"'{field}' is a required property"):
        _admit(release_root, blobs_root, verify_source_native_admission)


@pytest.mark.parametrize("field", ["deterministicFailureCount", "transientFailureCount", "unclassedFailureCount"])
@pytest.mark.parametrize("value", [-1, True, "0"])
def test_failure_summary_counts_require_nonnegative_integers(tmp_path: Path, field: str, value: Any) -> None:
    def change(receipt: dict[str, Any]) -> None:
        receipt[field] = value

    release_root, blobs_root = _build_release(tmp_path, mutate_receipt=change)
    with pytest.raises(SourceNativeReleaseError, match="publication receipt structure differs"):
        _admit(release_root, blobs_root, verify_source_native_admission)


@pytest.mark.parametrize("field", ["deterministicFailureCount", "transientFailureCount", "unclassedFailureCount"])
def test_nonzero_class_count_cannot_hide_behind_zero_total(tmp_path: Path, field: str) -> None:
    def change(receipt: dict[str, Any]) -> None:
        receipt[field] = 1

    release_root, blobs_root = _build_release(tmp_path, mutate_receipt=change)
    with pytest.raises(SourceNativeReleaseError, match="does not reconcile with failedRecordCount"):
        _admit(release_root, blobs_root, verify_source_native_admission)


@pytest.mark.parametrize(
    ("field", "value"),
    [("formatVersion", "1.0"), ("releaseSchemaId", "urn:spicy-regs:schema:source-native-release:1.0")],
)
def test_historical_receipt_identity_is_refused(tmp_path: Path, field: str, value: str) -> None:
    def change(receipt: dict[str, Any]) -> None:
        receipt[field] = value

    release_root, blobs_root = _build_release(tmp_path, mutate_receipt=change)
    with pytest.raises(SourceNativeReleaseError, match="receipt format is unsupported"):
        _admit(release_root, blobs_root, verify_source_native_admission)


@pytest.mark.parametrize(("product", "version"), [("spicy-regs", "2.0"), ("spicy-docs", "1.0")])
def test_historical_producer_or_verifier_is_refused(tmp_path: Path, product: str, version: str) -> None:
    producer = Producer(
        product=product,
        implementation_id=IMPLEMENTATION_ID,
        verifier_id=VERIFIER_ID,
        verifier_version=version,
        verifier_implementation_id=IMPLEMENTATION_ID,
    )
    release_root, blobs_root = _build_release(tmp_path, producer=producer)
    with pytest.raises(SourceNativeReleaseError, match="producer names an unsupported verifier"):
        _admit(release_root, blobs_root, verify_source_native_admission)


def test_admission_preserves_root_byte_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from spicy_docs.releases import admission

    release_root, blobs_root = _build_release(tmp_path)
    root_size = (release_root / ROOT_OBJECT_KEY).stat().st_size
    monkeypatch.setattr(admission, "MAX_ROW_BYTES", root_size)
    _admit(release_root, blobs_root, verify_source_native_admission)
    monkeypatch.setattr(admission, "MAX_ROW_BYTES", root_size - 1)
    with pytest.raises(SourceNativeReleaseError, match="root exceeds its product limit"):
        _admit(release_root, blobs_root, verify_source_native_admission)
