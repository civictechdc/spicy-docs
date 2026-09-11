"""Live acquisition adapters with injected alternatives for offline commands."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import httpx

from spicy_docs.releases.format import (
    SourceNativeReleaseError,
)
from spicy_docs.schemas import COMMENT, DOCKET, DOCUMENT
from spicy_docs.sources import mirrulations
from spicy_docs.sources.federal_register.native import (
    FederalRegisterFetch,
    FederalRegisterSourceError,
)
from spicy_docs.sources.gao.native import (
    FETCH_TIMEOUT_SECONDS as GAO_FETCH_TIMEOUT_SECONDS,
)
from spicy_docs.sources.gao.native import (
    MAX_PAGE_BYTES as GAO_MAX_PAGE_BYTES,
)
from spicy_docs.sources.gao.native import (
    GaoProductFetch,
)
from spicy_docs.sources.public_comments.native import (
    MAX_PARTITION_BYTES,
    PublicTableCapture,
    PublicTableFetch,
    PublicTableSourceError,
)
from spicy_docs.sources.regulations_gov.definitions import (
    COMMENT_COLLECTION,
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    MirrulationsObjectReader,
    RegulationsGovSourceError,
)
from spicy_docs.sources.zyte import ZyteHttpFetcher
from spicy_docs.transport.retry import retry_http

_USER_AGENT = "spicy-docs-source-native/1.0 (https://github.com/civictechdc/spicy-docs)"


def capture_instant(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise SourceNativeReleaseError("CLI clock must return a timezone-aware instant")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RetryableHTTPStatusError(httpx.HTTPStatusError):
    """A 429 or 5xx response -- worth retrying, unlike any other 4xx.

    A distinct subclass (rather than the plain ``httpx.HTTPStatusError`` that
    ``response.raise_for_status()`` raises) lets ``retry_http`` tell "the
    server asked us to back off or is failing" apart from "this request is
    simply wrong" without inspecting exception messages. Both still satisfy
    ``isinstance(error, httpx.HTTPError)``, so a persistent 429/5xx that
    outlasts every attempt is still classified as ``transport-failed`` same
    as before.
    """


def fetch_federal_register(client: httpx.Client, url: str) -> bytes:
    def _attempt() -> bytes:
        response = client.get(url)
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableHTTPStatusError(
                "retryable Federal Register response",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        if not response.content:
            raise FederalRegisterSourceError("Federal Register returned an empty response")
        return response.content

    return retry_http(
        _attempt,
        retryable=(httpx.RequestError, RetryableHTTPStatusError, FederalRegisterSourceError),
    )


@contextmanager
def federal_register_fetcher(injected: FederalRegisterFetch | None) -> Iterator[FederalRegisterFetch]:
    if injected is not None:
        yield injected
        return
    with httpx.Client(
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        timeout=httpx.Timeout(60.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        yield lambda url: fetch_federal_register(client, url)


def fetch_public_table(
    client: httpx.Client,
    locator: str,
    *,
    clock: Callable[[], datetime],
) -> PublicTableCapture | None:
    """Fetch one whole partition object, or report that the mirror has none."""

    def _attempt() -> PublicTableCapture | None:
        response = client.get(locator)
        if response.status_code == 404:
            return None
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableHTTPStatusError(
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
            fetched_at=capture_instant(clock),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )

    return retry_http(
        _attempt,
        retryable=(httpx.RequestError, RetryableHTTPStatusError, PublicTableSourceError),
    )


@contextmanager
def gao_fetcher(injected: GaoProductFetch | None) -> Iterator[GaoProductFetch]:
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
def public_table_fetcher(
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
        yield lambda locator: fetch_public_table(client, locator, clock=clock)


def default_regulations_reader(agency: str, collection: str) -> MirrulationsObjectReader:
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
