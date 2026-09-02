"""Publish or independently verify one SpicyRegs source-native release."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final, TextIO

import httpx
from rulespec_artifacts import (
    ArtifactPin,
    LocalMemberSource,
    Producer,
    admit_artifact,
    canonical_json_bytes,
)

from spicy_docs.federal_register_source_native import (
    FederalRegisterFetch,
    FederalRegisterSourceError,
    iter_federal_register_pages,
)
from spicy_docs.gao_product_pages_source_native import (
    FETCH_TIMEOUT_SECONDS as GAO_FETCH_TIMEOUT_SECONDS,
)
from spicy_docs.gao_product_pages_source_native import (
    MAX_PAGE_BYTES as GAO_MAX_PAGE_BYTES,
)
from spicy_docs.gao_product_pages_source_native import (
    GaoProductFetch,
    GaoProductSourceError,
    gao_product_query_scope,
    iter_gao_product_pages,
)
from spicy_docs.publication import ImmutablePublicationError
from spicy_docs.regulations_gov_source_native import (
    COMMENT_COLLECTION,
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    MirrulationsObjectReader,
    RegulationsGovSourceError,
    iter_regulations_gov_comment_pages,
    iter_regulations_gov_docket_pages,
    iter_regulations_gov_document_pages,
)
from spicy_docs.schemas import COMMENT, DOCKET, DOCUMENT
from spicy_docs.source_native import (
    CURRENT_PRODUCER_PRODUCT,
    VERIFIER_ID,
    VERIFIER_VERSION,
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
    verify_source_native_release,
)
from spicy_docs.source_native_profile import SourceNativePage, SourceNativeProfile
from spicy_docs.source_native_profiles import (
    FEDERAL_REGISTER_PROFILE,
    GAO_PRODUCT_PAGE_PROFILE,
    REGULATIONS_GOV_COMMENT_PROFILE,
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
    SPICY_REGS_PUBLIC_COMMENT_PROFILE,
)
from spicy_docs.source_native_store import LocalSourceNativeBlobStore
from spicy_docs.sources import mirrulations
from spicy_docs.sources.zyte import ZyteHttpFetcher, ZyteTransportError
from spicy_docs.spicy_regs_public_tables_source_native import (
    COMMENT_TABLE,
    MAX_PARTITION_BYTES,
    PublicTableCapture,
    PublicTableFetch,
    PublicTableSourceError,
    iter_spicy_regs_public_comment_pages,
)

SOURCE_FEDERAL_REGISTER: Final = "federal-register"
SOURCE_GAO_PRODUCT_PAGES: Final = "gao-product-pages"
SOURCE_REGULATIONS_DOCUMENTS: Final = "regulations-documents"
SOURCE_REGULATIONS_DOCKETS: Final = "regulations-dockets"
SOURCE_REGULATIONS_COMMENTS: Final = "regulations-comments"
SOURCE_SPICY_REGS_PUBLIC_COMMENTS: Final = "spicy-regs-public-comments"
SOURCE_CHOICES: Final = (
    SOURCE_FEDERAL_REGISTER,
    SOURCE_GAO_PRODUCT_PAGES,
    SOURCE_REGULATIONS_DOCUMENTS,
    SOURCE_REGULATIONS_DOCKETS,
    SOURCE_REGULATIONS_COMMENTS,
    SOURCE_SPICY_REGS_PUBLIC_COMMENTS,
)
# The community mirror is the default supply rung; the origin-API sources
# above are the fallback for what its tables cannot carry.
DATED_SOURCES: Final = (
    SOURCE_FEDERAL_REGISTER,
    SOURCE_REGULATIONS_DOCUMENTS,
    SOURCE_REGULATIONS_DOCKETS,
    SOURCE_REGULATIONS_COMMENTS,
)

_USER_AGENT = "spicy-docs-source-native/1.0 (https://github.com/civictechdc/spicy-docs)"
_MAX_HTTP_ATTEMPTS = 5

RegulationsReaderFactory = Callable[[str, str], MirrulationsObjectReader]


def _date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser(
        "publish",
        help="Acquire, publish, and producer-verify one release",
    )
    publish.add_argument("--source", choices=SOURCE_CHOICES, required=True)
    publish.add_argument(
        "--since",
        type=_date,
        help="Start of the source date window; required by every dated source",
    )
    publish.add_argument(
        "--until",
        type=_date,
        help="End of the source date window; required by every dated source",
    )
    publish.add_argument(
        "--agency",
        action="append",
        help="Agency code; repeat for multiple agencies",
    )
    publish.add_argument(
        "--product-id",
        action="append",
        help="Closed GAO product ID; repeat for multiple product pages",
    )
    publish.add_argument("--destination", type=Path, required=True)
    publish.add_argument(
        "--blob-store",
        type=Path,
        required=True,
        help="Explicit persistent content-addressed payload store",
    )
    publish.add_argument("--implementation-id", required=True)

    verify = subparsers.add_parser(
        "verify",
        help="Independently replay and verify one immutable release",
    )
    verify.add_argument("--source", choices=SOURCE_CHOICES, required=True)
    verify.add_argument("--release", type=Path, required=True)
    verify.add_argument(
        "--blob-store",
        type=Path,
        required=True,
        help="Explicit persistent content-addressed payload store",
    )
    verify.add_argument("--logical-id", required=True)
    verify.add_argument("--artifact-digest", required=True)
    verify.add_argument(
        "--accepted-verifier-implementation-id",
        action="append",
        required=True,
    )
    return parser


def _profile(source: str) -> SourceNativeProfile:
    if source == SOURCE_FEDERAL_REGISTER:
        return FEDERAL_REGISTER_PROFILE
    if source == SOURCE_GAO_PRODUCT_PAGES:
        return GAO_PRODUCT_PAGE_PROFILE
    if source == SOURCE_REGULATIONS_DOCUMENTS:
        return REGULATIONS_GOV_DOCUMENT_PROFILE
    if source == SOURCE_REGULATIONS_DOCKETS:
        return REGULATIONS_GOV_DOCKET_PROFILE
    if source == SOURCE_REGULATIONS_COMMENTS:
        return REGULATIONS_GOV_COMMENT_PROFILE
    if source == SOURCE_SPICY_REGS_PUBLIC_COMMENTS:
        return SPICY_REGS_PUBLIC_COMMENT_PROFILE
    raise SourceNativeReleaseError(f"unsupported source {source!r}")


def _now() -> datetime:
    return datetime.now(UTC)


def _instant(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise SourceNativeReleaseError("CLI clock must return a timezone-aware instant")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fetch_with_retries(client: httpx.Client, url: str) -> bytes:
    for attempt in range(1, _MAX_HTTP_ATTEMPTS + 1):
        try:
            response = client.get(url)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    "retryable Federal Register response",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            if not response.content:
                raise FederalRegisterSourceError("Federal Register returned an empty response")
            return response.content
        except (httpx.HTTPError, FederalRegisterSourceError):
            if attempt == _MAX_HTTP_ATTEMPTS:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


@contextmanager
def _fetcher(injected: FederalRegisterFetch | None) -> Iterator[FederalRegisterFetch]:
    if injected is not None:
        yield injected
        return
    with httpx.Client(
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        timeout=httpx.Timeout(60.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        yield lambda url: _fetch_with_retries(client, url)


def _fetch_public_table(
    client: httpx.Client,
    locator: str,
    *,
    clock: Callable[[], datetime],
) -> PublicTableCapture | None:
    """Fetch one whole partition object, or report that the mirror has none."""

    for attempt in range(1, _MAX_HTTP_ATTEMPTS + 1):
        try:
            response = client.get(locator)
            if response.status_code == 404:
                return None
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    "retryable spicy-regs public-table response",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            if not response.content:
                raise PublicTableSourceError("the spicy-regs public tables returned an empty partition")
            if len(response.content) > MAX_PARTITION_BYTES:
                raise PublicTableSourceError("public-table partition exceeds its capture byte bound")
            return PublicTableCapture(
                locator=locator,
                content=response.content,
                fetched_at=_instant(clock),
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
        except (httpx.HTTPError, PublicTableSourceError):
            if attempt == _MAX_HTTP_ATTEMPTS:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


@contextmanager
def _gao_fetcher(injected: GaoProductFetch | None) -> Iterator[GaoProductFetch]:
    """Use an injected fixture or the secret-safe SpicyDocs Zyte adapter."""

    if injected is not None:
        yield injected
        return
    fetcher = ZyteHttpFetcher.from_environment()
    yield lambda url: fetcher.fetch(
        url,
        timeout_seconds=GAO_FETCH_TIMEOUT_SECONDS,
        max_bytes=GAO_MAX_PAGE_BYTES,
    )


@contextmanager
def _public_table_fetcher(
    injected: PublicTableFetch | None,
    clock: Callable[[], datetime],
) -> Iterator[PublicTableFetch]:
    if injected is not None:
        yield injected
        return
    with httpx.Client(
        headers={"Accept": "application/octet-stream", "User-Agent": _USER_AGENT},
        timeout=httpx.Timeout(120.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        yield lambda locator: _fetch_public_table(client, locator, clock=clock)


def _default_regulations_reader(agency: str, collection: str) -> MirrulationsObjectReader:
    if collection == DOCUMENT_COLLECTION:
        record_type = DOCUMENT
    elif collection == DOCKET_COLLECTION:
        record_type = DOCKET
    elif collection == COMMENT_COLLECTION:
        record_type = COMMENT
    else:
        raise RegulationsGovSourceError(f"unsupported Mirrulations collection {collection!r}")
    return mirrulations.MirrulationsReader(
        mirrulations.s3_resource(),
        mirrulations.BUCKET,
        mirrulations.PREFIX,
        agency,
        record_type,
        processed_keys=None,
        since_year=None,
        retain_keys=False,
        fail_fast=True,
    )


def _success(
    command: str,
    source_name: str,
    release: Path,
    *,
    pin: ArtifactPin,
    spec: Mapping[str, Any],
) -> dict[str, object]:
    return {
        "artifactDigest": pin.artifact_digest,
        "command": command,
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


def _emit(stream: TextIO, value: Mapping[str, object]) -> None:
    stream.write(canonical_json_bytes(value).decode("utf-8") + "\n")


def _require_separate_paths(left: Path, right: Path, *, labels: tuple[str, str]) -> None:
    selected_left = Path(left).absolute().resolve(strict=False)
    selected_right = Path(right).absolute().resolve(strict=False)
    if (
        selected_left == selected_right
        or selected_left.is_relative_to(selected_right)
        or selected_right.is_relative_to(selected_left)
    ):
        raise SourceNativeReleaseError(f"{labels[0]} and {labels[1]} must not overlap")


def _query_scope(args: argparse.Namespace) -> dict[str, Any]:
    dated = args.source in DATED_SOURCES
    if dated and (args.since is None or args.until is None):
        raise SourceNativeReleaseError(f"--since and --until are required for {args.source}")
    if not dated and (args.since is not None or args.until is not None):
        raise SourceNativeReleaseError(
            f"--since and --until are not valid for {args.source}; its scope names partitions, not dates"
        )
    if args.source != SOURCE_GAO_PRODUCT_PAGES and args.product_id:
        raise SourceNativeReleaseError("--product-id is only valid for GAO product pages")
    if args.source == SOURCE_GAO_PRODUCT_PAGES:
        if args.agency:
            raise SourceNativeReleaseError("--agency is not valid for GAO product pages")
        product_ids = args.product_id or []
        if not product_ids:
            raise SourceNativeReleaseError("at least one --product-id is required for GAO product pages")
        if len(set(product_ids)) != len(product_ids):
            raise SourceNativeReleaseError("GAO --product-id values must be distinct")
        return gao_product_query_scope({"productIds": sorted(product_ids)})
    if args.source == SOURCE_SPICY_REGS_PUBLIC_COMMENTS:
        agencies = sorted(set(args.agency or []))
        if not agencies:
            raise SourceNativeReleaseError("at least one --agency is required for the spicy-regs public tables")
        return {"agencies": agencies, "table": COMMENT_TABLE}
    if args.source == SOURCE_FEDERAL_REGISTER:
        if args.agency:
            raise SourceNativeReleaseError("--agency is only valid for Regulations.gov")
        return {
            "publishedFrom": args.since.isoformat(),
            "publishedThrough": args.until.isoformat(),
        }
    agencies = sorted(set(args.agency or []))
    if not agencies:
        raise SourceNativeReleaseError("at least one --agency is required for Regulations.gov")
    if args.source == SOURCE_REGULATIONS_DOCUMENTS:
        return {
            "agencies": agencies,
            "publishedFrom": args.since.isoformat(),
            "publishedThrough": args.until.isoformat(),
        }
    if args.source == SOURCE_REGULATIONS_COMMENTS:
        return {
            "agencies": agencies,
            "postedFrom": args.since.isoformat(),
            "postedThrough": args.until.isoformat(),
        }
    return {
        "agencies": agencies,
        "modifiedFrom": args.since.isoformat(),
        "modifiedThrough": args.until.isoformat(),
    }


def _regulations_pages(
    args: argparse.Namespace,
    query_scope: Mapping[str, Any],
    read_regulations: RegulationsReaderFactory,
) -> Iterator[SourceNativePage]:
    if args.source == SOURCE_REGULATIONS_DOCUMENTS:
        return iter_regulations_gov_document_pages(
            lambda agency: read_regulations(agency, DOCUMENT_COLLECTION),
            query_scope=query_scope,
        )
    if args.source == SOURCE_REGULATIONS_COMMENTS:
        return iter_regulations_gov_comment_pages(
            lambda agency: read_regulations(agency, COMMENT_COLLECTION),
            query_scope=query_scope,
        )
    return iter_regulations_gov_docket_pages(
        lambda agency: read_regulations(agency, DOCKET_COLLECTION),
        query_scope=query_scope,
    )


def _publish(
    args: argparse.Namespace,
    *,
    fetch: FederalRegisterFetch | None,
    fetch_gao: GaoProductFetch | None,
    fetch_public_table: PublicTableFetch | None,
    read_regulations: RegulationsReaderFactory | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    profile = _profile(args.source)
    query_scope = _query_scope(args)
    _require_separate_paths(
        args.destination,
        args.blob_store,
        labels=("--destination", "--blob-store"),
    )
    if args.destination.exists() or args.destination.is_symlink():
        raise FileExistsError(f"refusing to replace immutable release: {args.destination}")
    started_at = _instant(clock)
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
    if args.source == SOURCE_FEDERAL_REGISTER:
        with _fetcher(fetch) as active_fetch:
            published = SourceNativeReleasePublisher(
                profile,
                blob_store=blob_store,
                clock=clock,
            ).publish(
                iter_federal_register_pages(active_fetch, query_scope=query_scope),
                build=build,
                destination=args.destination,
            )
    elif args.source == SOURCE_GAO_PRODUCT_PAGES:
        with _gao_fetcher(fetch_gao) as active_fetch:
            published = SourceNativeReleasePublisher(
                profile,
                blob_store=blob_store,
                clock=clock,
            ).publish(
                iter_gao_product_pages(active_fetch, query_scope=query_scope),
                build=build,
                destination=args.destination,
            )
    elif args.source == SOURCE_SPICY_REGS_PUBLIC_COMMENTS:
        with _public_table_fetcher(fetch_public_table, clock) as active_table_fetch:
            published = SourceNativeReleasePublisher(
                profile,
                blob_store=blob_store,
                clock=clock,
            ).publish(
                iter_spicy_regs_public_comment_pages(active_table_fetch, query_scope=query_scope),
                build=build,
                destination=args.destination,
            )
    else:
        active_reader = read_regulations or _default_regulations_reader
        published = SourceNativeReleasePublisher(
            profile,
            blob_store=blob_store,
            clock=clock,
        ).publish(
            _regulations_pages(args, query_scope, active_reader),
            build=build,
            destination=args.destination,
        )
    return _success(
        "publish",
        args.source,
        published.root,
        pin=published.artifact.pin,
        spec=published.artifact.root["spec"],
    )


def _verify(args: argparse.Namespace) -> dict[str, object]:
    profile = _profile(args.source)
    _require_separate_paths(
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
    )


def _error_code(error: Exception) -> str:
    if isinstance(error, (FileExistsError, ImmutablePublicationError)):
        return "destination-exists"
    if isinstance(
        error,
        (
            FederalRegisterSourceError,
            GaoProductSourceError,
            RegulationsGovSourceError,
            PublicTableSourceError,
        ),
    ):
        return "acquisition-failed"
    if isinstance(error, SourceNativeReleaseError):
        return "release-invalid"
    if isinstance(error, (httpx.HTTPError, ZyteTransportError)):
        return "transport-failed"
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
    args = _parser().parse_args(argv)
    try:
        result = (
            _publish(
                args,
                fetch=fetch,
                fetch_gao=fetch_gao,
                fetch_public_table=fetch_public_table,
                read_regulations=read_regulations,
                clock=clock,
            )
            if args.command == "publish"
            else _verify(args)
        )
    except (
        FileExistsError,
        ImmutablePublicationError,
        FederalRegisterSourceError,
        GaoProductSourceError,
        RegulationsGovSourceError,
        PublicTableSourceError,
        SourceNativeReleaseError,
        ZyteTransportError,
        httpx.HTTPError,
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
