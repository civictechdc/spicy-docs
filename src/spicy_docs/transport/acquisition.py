"""Live acquisition adapters with injected alternatives for offline commands."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from spicy_docs.releases.format import (
    SourceNativeReleaseError,
)
from spicy_docs.schemas import COMMENT, DOCKET, DOCUMENT
from spicy_docs.sources.federal_register.native import (
    FederalRegisterFetch,
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
    PublicTableFetch,
)
from spicy_docs.sources.regulations_gov.definitions import (
    COMMENT_COLLECTION,
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    MirrulationsObjectReader,
    RegulationsGovSourceError,
)
from spicy_docs.sources.zyte import ZyteHttpFetcher

_USER_AGENT = "spicy-docs-source-native/1.0 (https://github.com/civictechdc/spicy-docs)"


def capture_instant(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise SourceNativeReleaseError("CLI clock must return a timezone-aware instant")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def federal_register_fetcher(injected: FederalRegisterFetch | None) -> Iterator[FederalRegisterFetch]:
    if injected is not None:
        yield injected
        return
    import httpx

    from spicy_docs.transport.http import fetch_federal_register

    with httpx.Client(
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        timeout=httpx.Timeout(60.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        yield lambda url: fetch_federal_register(client, url)


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
    import httpx

    from spicy_docs.transport.http import fetch_public_table

    with httpx.Client(
        headers={"Accept": "application/octet-stream", "User-Agent": _USER_AGENT},
        timeout=httpx.Timeout(120.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        yield lambda locator: fetch_public_table(client, locator, clock=clock)


def default_regulations_reader(agency: str, collection: str) -> MirrulationsObjectReader:
    from spicy_docs.sources import mirrulations

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
