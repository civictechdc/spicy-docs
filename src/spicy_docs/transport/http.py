"""HTTPX acquisition and retry rules, loaded only for HTTP-backed operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import httpx

from spicy_docs.sources.federal_register.native import FederalRegisterSourceError
from spicy_docs.sources.public_comments.native import MAX_PARTITION_BYTES, PublicTableCapture, PublicTableSourceError
from spicy_docs.transport.acquisition import capture_instant
from spicy_docs.transport.retry import retry_http


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
