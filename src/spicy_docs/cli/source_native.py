"""Publish, verify, or inspect source-native releases and public Parquet tables.

Public-table handlers import their publisher lazily: PyArrow is supplied by
this package's ``public-table`` extra, while source acquisition and verification
remain usable without it. A missing extra produces ``dependency-missing``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import httpx
from rulespec_artifacts import (
    ArtifactPin,
    LocalMemberSource,
    Producer,
    admit_artifact,
    canonical_json_bytes,
)

from spicy_docs.cli.arguments import parser
from spicy_docs.cli.sources import (
    ACQUISITION_ERRORS,
    AcquisitionInputs,
    RegulationsReaderFactory,
    public_table_profile,
    source_registration,
)
from spicy_docs.releases.format import (
    CURRENT_PRODUCER_PRODUCT,
    VERIFIER_ID,
    VERIFIER_VERSION,
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
)
from spicy_docs.releases.paths import require_separate_paths
from spicy_docs.releases.publish import (
    SourceNativeReleasePublisher,
)
from spicy_docs.releases.reader import (
    SourceNativeReleaseReader,
    _collection_outcome,
)
from spicy_docs.releases.verify import (
    verify_source_native_release,
)
from spicy_docs.sources.federal_register.native import (
    FederalRegisterFetch,
)
from spicy_docs.sources.gao.native import (
    GaoProductFetch,
)
from spicy_docs.sources.public_comments.native import (
    PublicTableFetch,
)
from spicy_docs.sources.zyte import ZyteTransportError
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from spicy_docs.storage.publication import ImmutablePublicationError
from spicy_docs.transport.acquisition import capture_instant


def _now() -> datetime:
    return datetime.now(UTC)


def _success(
    command: str,
    source_name: str,
    release: Path,
    *,
    pin: ArtifactPin,
    spec: Mapping[str, Any],
    outcome: Mapping[str, Any],
) -> dict[str, object]:
    return {
        "artifactDigest": pin.artifact_digest,
        "command": command,
        "collectionOutcome": outcome,
        "logicalId": pin.logical_id,
        "ok": True,
        "release": str(release.resolve()),
        "source": source_name,
        "sourceNativeSchemaSetDigest": spec["sourceNativeSchemaSetDigest"],
        "sourceStateDigest": spec["sourceStateDigest"],
        "sourceStateScope": spec["sourceStateScope"],
        "sourceSystemId": spec["sourceSystemId"],
        "sourceSystemVersion": spec["sourceSystemVersion"],
    }


def _success_public_table(
    command: str,
    table: str,
    release: Path,
    *,
    pin: ArtifactPin,
    spec: Mapping[str, Any],
) -> dict[str, object]:
    """Mirror ``_success`` for the public-table spec shape, which carries no
    ``sourceNativeSchemaSetDigest``/``sourceSystemVersion`` -- those describe
    the source-native release this table was built from, not the table
    itself."""

    return {
        "artifactDigest": pin.artifact_digest,
        "command": command,
        "logicalId": pin.logical_id,
        "maxRowsPerMember": spec["maxRowsPerMember"],
        "ok": True,
        "release": str(Path(release).resolve()),
        "sourceStateDigest": spec["sourceStateDigest"],
        "sourceStateScope": spec["sourceStateScope"],
        "sourceSystemId": spec["sourceSystemId"],
        "table": table,
        "tableName": spec["tableName"],
    }


def _emit(stream: TextIO, value: Mapping[str, object]) -> None:
    stream.write(canonical_json_bytes(value).decode("utf-8") + "\n")


def _publish(
    args: argparse.Namespace,
    *,
    fetch: FederalRegisterFetch | None,
    fetch_gao: GaoProductFetch | None,
    fetch_public_table: PublicTableFetch | None,
    read_regulations: RegulationsReaderFactory | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    profile = source_registration(args.source).profile
    query_scope = source_registration(args.source).query_scope(args)
    require_separate_paths(
        args.destination,
        args.blob_store,
        labels=("--destination", "--blob-store"),
    )
    if args.destination.exists() or args.destination.is_symlink():
        raise FileExistsError(f"refusing to replace immutable release: {args.destination}")
    started_at = capture_instant(clock)
    producer = Producer(
        product=CURRENT_PRODUCER_PRODUCT,
        implementation_id=args.implementation_id,
        verifier_id=VERIFIER_ID,
        verifier_version=VERIFIER_VERSION,
        verifier_implementation_id=args.implementation_id,
    )
    build = SourceNativeReleaseBuild(
        query_scope=query_scope,
        producer=producer,
        started_at=started_at,
    )
    blob_store = LocalSourceNativeBlobStore(args.blob_store)
    inputs = AcquisitionInputs(clock, fetch, fetch_gao, fetch_public_table, read_regulations)
    # Keep the selected transport context open while the publisher consumes
    # the lazy iterator, including when iteration fails.
    with source_registration(args.source).acquire(inputs, query_scope) as pages, closing(pages):
        published = SourceNativeReleasePublisher(profile, blob_store=blob_store, clock=clock).publish(
            pages,
            build=build,
            destination=args.destination,
        )
    result = _success(
        "publish",
        args.source,
        published.root,
        pin=published.artifact.pin,
        spec=published.artifact.root["spec"],
        outcome=_collection_outcome(LocalMemberSource(published.root)),
    )
    result["byteMeasurements"] = dict(published.byte_measurements)
    return result


def _verify(args: argparse.Namespace) -> dict[str, object]:
    profile = source_registration(args.source).profile
    require_separate_paths(
        args.release,
        args.blob_store,
        labels=("--release", "--blob-store"),
    )
    expected_pin = ArtifactPin(args.logical_id, args.artifact_digest)
    source = LocalMemberSource(args.release)
    blob_source = LocalSourceNativeBlobStore(args.blob_store, create=False)
    artifact = admit_artifact(
        source,
        blob_source=blob_source,
        expected_pin=expected_pin,
        semantic_verifier=lambda artifact, source: verify_source_native_release(
            artifact,
            source,
            profile=profile,
            blob_source=blob_source,
        ),
    )
    accepted = frozenset(args.accepted_verifier_implementation_id)
    producer = artifact.root["producer"]
    if producer["verifierImplementationId"] not in accepted:
        raise SourceNativeReleaseError("source-native verifier implementation is not accepted")
    return _success(
        "verify",
        args.source,
        args.release,
        pin=artifact.pin,
        spec=artifact.root["spec"],
        outcome=_collection_outcome(source),
    )


def _inspect(args: argparse.Namespace) -> dict[str, object]:
    require_separate_paths(args.release, args.blob_store, labels=("--release", "--blob-store"))
    reader = SourceNativeReleaseReader(
        LocalMemberSource(args.release),
        blob_source=LocalSourceNativeBlobStore(args.blob_store, create=False),
        profile=source_registration(args.source).profile,
        accepted_verifier_implementation_ids=frozenset(args.accepted_verifier_implementation_id),
        expected_pin=ArtifactPin(args.logical_id, args.artifact_digest),
    )
    outcome = reader.collection_outcome
    failures = list(reader.iter_failures(limit=args.failure_limit))
    return {
        **_success(
            "inspect",
            args.source,
            args.release,
            pin=reader.pin,
            spec={
                "sourceNativeSchemaSetDigest": reader.source_native_schema_set_digest,
                "sourceStateDigest": reader.source_state_digest,
                "sourceStateScope": reader.source_state_scope,
                "sourceSystemId": reader.source_system_id,
                "sourceSystemVersion": reader.source_system_version,
            },
            outcome=outcome,
        ),
        "failureLimit": args.failure_limit,
        "failures": failures,
        "failuresTruncated": len(failures) < outcome["failedRecordCount"],
    }


def _publish_public_table(args: argparse.Namespace) -> dict[str, object]:
    """Project an admitted source release using the optional PyArrow dependency.

    Import here so commands that do not produce tables work without the
    ``public-table`` extra. Missing dependencies produce ``dependency-missing``.
    """

    from spicy_docs.public_tables.api import (
        VERIFIER_ID as PUBLIC_TABLE_VERIFIER_ID,
    )
    from spicy_docs.public_tables.api import (
        VERIFIER_VERSION as PUBLIC_TABLE_VERIFIER_VERSION,
    )
    from spicy_docs.public_tables.api import (
        PublicTableBuild,
        PublicTablePublisher,
    )

    source_profile = source_registration(args.table).profile
    public_profile = public_table_profile(args.table)
    require_separate_paths(
        args.source_release,
        args.source_blob_store,
        labels=("--source-release", "--source-blob-store"),
    )
    require_separate_paths(
        args.destination,
        args.source_release,
        labels=("--destination", "--source-release"),
    )
    if args.destination.exists() or args.destination.is_symlink():
        raise FileExistsError(f"refusing to replace immutable public table: {args.destination}")
    source = SourceNativeReleaseReader(
        LocalMemberSource(args.source_release),
        blob_source=LocalSourceNativeBlobStore(args.source_blob_store, create=False),
        profile=source_profile,
        accepted_verifier_implementation_ids=frozenset(args.source_accepted_verifier_implementation_id),
    )
    producer = Producer(
        product=CURRENT_PRODUCER_PRODUCT,
        implementation_id=args.implementation_id,
        verifier_id=PUBLIC_TABLE_VERIFIER_ID,
        verifier_version=PUBLIC_TABLE_VERIFIER_VERSION,
        verifier_implementation_id=args.implementation_id,
    )
    published = PublicTablePublisher(public_profile).publish(
        source,
        build=PublicTableBuild(producer),
        destination=args.destination,
    )
    return _success_public_table(
        "publish-public-table",
        args.table,
        published.root,
        pin=published.artifact.pin,
        spec=published.artifact.root["spec"],
    )


def _verify_public_table(args: argparse.Namespace) -> dict[str, object]:
    """Check public-table admission under an accepted producer identity.

    See the pyarrow note on ``_publish_public_table`` -- the same lazy import
    applies here.
    """

    from spicy_docs.public_tables.api import verify_public_table_admission

    profile = public_table_profile(args.table)
    expected_pin = ArtifactPin(args.logical_id, args.artifact_digest)
    source = LocalMemberSource(args.release)
    artifact = admit_artifact(
        source,
        expected_pin=expected_pin,
        semantic_verifier=lambda artifact, source: verify_public_table_admission(
            artifact,
            source,
            profile=profile,
        ),
    )
    accepted = frozenset(args.accepted_verifier_implementation_id)
    producer = artifact.root["producer"]
    if producer["verifierImplementationId"] not in accepted:
        raise SourceNativeReleaseError("public-table verifier implementation is not accepted")
    return _success_public_table(
        "verify-public-table",
        args.table,
        args.release,
        pin=artifact.pin,
        spec=artifact.root["spec"],
    )


def _error_code(error: Exception) -> str:
    if isinstance(error, (FileExistsError, ImmutablePublicationError)):
        return "destination-exists"
    if isinstance(error, ACQUISITION_ERRORS):
        return "acquisition-failed"
    if isinstance(error, SourceNativeReleaseError):
        return "release-invalid"
    if isinstance(error, (httpx.HTTPError, ZyteTransportError)):
        return "transport-failed"
    if isinstance(error, ImportError):
        return "dependency-missing"
    return "operation-failed"


def main(
    argv: list[str] | None = None,
    *,
    fetch: FederalRegisterFetch | None = None,
    fetch_gao: GaoProductFetch | None = None,
    fetch_public_table: PublicTableFetch | None = None,
    read_regulations: RegulationsReaderFactory | None = None,
    clock: Callable[[], datetime] = _now,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the one source-native operator command through injected adapters."""

    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    args = parser().parse_args(argv)
    try:
        if args.command == "publish":
            result = _publish(
                args,
                fetch=fetch,
                fetch_gao=fetch_gao,
                fetch_public_table=fetch_public_table,
                read_regulations=read_regulations,
                clock=clock,
            )
        elif args.command == "verify":
            result = _verify(args)
        elif args.command == "inspect":
            result = _inspect(args)
        elif args.command == "publish-public-table":
            result = _publish_public_table(args)
        else:
            result = _verify_public_table(args)
    except (
        FileExistsError,
        ImmutablePublicationError,
        *ACQUISITION_ERRORS,
        SourceNativeReleaseError,
        ZyteTransportError,
        httpx.HTTPError,
        ImportError,
        OSError,
        ValueError,
    ) as error:
        _emit(
            errors,
            {
                "command": args.command,
                "error": {"code": _error_code(error), "message": str(error)},
                "ok": False,
            },
        )
        return 1
    _emit(output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
