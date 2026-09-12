"""Bounded HTTP capture and streamed assets over the shared Rulespec writer.

Metadata responses have a separate, small byte bound. Asset bytes stream to
content-addressed storage without becoming metadata-page bytes. This client
owns requests, not dataset selection, run recovery or publication.
"""

from __future__ import annotations

import hashlib
import math
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from urllib.parse import urljoin

import httpx
from rulespec_artifacts import LocalBlobWriter

from spicy_docs.sources.refusals import RefusedResponse, attach_refused_response
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.retry import retry_http


class AcquisitionError(ValueError):
    """A request or response did not satisfy the selected acquisition."""


class HttpRefusal(CredentialRefusedError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"source answered HTTP {status}; stopping acquisition")


class _Retryable(AcquisitionError):
    pass


@dataclass(frozen=True)
class ResponseCapture:
    url: str
    resolved_url: str
    media_type: str
    observed_at: str
    body: bytes = field(repr=False)
    via: str = "direct"

    @property
    def sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.body).hexdigest()


class BoundedAcquirer:
    """Sequential, injected HTTP transport with caller-selected bounds.

    The URL validator runs before each request, including redirects. The header
    callback can restrict credentials to one host; requests never forward them
    implicitly. No HTTPX exception text or request headers enter diagnostics.
    """

    def __init__(
        self,
        *,
        validate_url: Callable[[str], str],
        headers: Callable[[str], dict[str, str]] | None = None,
        max_requests: int = 1000,
        min_interval: float = 0.25,
        timeout: float = 60,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if type(max_requests) is not int or max_requests <= 0:
            raise ValueError("max_requests must be a positive integer")
        if not math.isfinite(min_interval) or min_interval < 0 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("request interval and timeout must be finite and within bounds")
        self.validate_url = validate_url
        self.headers = headers or (lambda _: {})
        self.max_requests = max_requests
        self.min_interval = min_interval
        self.request_count = 0
        self._last_start = 0.0
        self._client = httpx.Client(transport=transport, timeout=timeout, trust_env=False, follow_redirects=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_error: object) -> None:
        self._client.close()

    def _start(self) -> None:
        if self.request_count >= self.max_requests:
            raise AcquisitionError("acquisition request budget exhausted")
        delay = self.min_interval - (time.monotonic() - self._last_start)
        if delay > 0:
            time.sleep(delay)
        self._last_start = time.monotonic()
        self.request_count += 1

    def _chunks(
        self, url: str, *, facts: dict, extra_headers: dict | None = None, require_identity: bool = False
    ) -> Iterator[bytes]:
        current = self.validate_url(url)
        for _ in range(4):
            self._start()
            request_headers = {"User-Agent": "spicy-docs/0.2 FEC acquisition", "Accept-Encoding": "identity"}
            request_headers.update(self.headers(current))
            request_headers.update(extra_headers or {})
            try:
                # Do not carry response cookies into a different source request.
                self._client.cookies.clear()
                with self._client.stream("GET", current, headers=request_headers) as response:
                    status = response.status_code
                    if status in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise AcquisitionError("redirect omitted Location")
                        current = self.validate_url(urljoin(current, location))
                        continue
                    if status in (401, 403):
                        raise HttpRefusal(status)
                    if status == 429 or status >= 500:
                        raise _Retryable(f"source answered retryable HTTP {status}")
                    if status != 200:
                        raise AcquisitionError(f"source answered HTTP {status}")
                    facts.update(
                        via="direct",
                        resolved_url=current,
                        media_type=response.headers.get("content-type", "application/octet-stream").split(";", 1)[0],
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        content_encoding=response.headers.get("content-encoding", "identity"),
                        content_length=response.headers.get("content-length"),
                        observed_at=datetime.now(UTC).isoformat(),
                    )
                    secrets = tuple(v.encode() for v in self.headers(current).values() if v)
                    if any(secret.decode() in str(value) for secret in secrets for value in facts.values()):
                        raise CredentialRefusedError("source metadata echoed the API credential")
                    if require_identity and facts["content_encoding"].lower() != "identity":
                        raise AcquisitionError("asset ignored the requested identity Content-Encoding")
                    tail = b""
                    tail_size = max((len(secret) for secret in secrets), default=1) - 1
                    observed = 0
                    for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        if any(secret in tail + chunk for secret in secrets):
                            raise CredentialRefusedError("source response echoed the API credential")
                        tail = chunk[-tail_size:] if tail_size else b""
                        observed += len(chunk)
                        yield chunk
                    length = facts["content_length"]
                    if (
                        facts["content_encoding"] == "identity"
                        and length is not None
                        and (not length.isascii() or not length.isdecimal() or int(length) != observed)
                    ):
                        raise AcquisitionError("response length disagrees with Content-Length")
                    return
            except httpx.HTTPError:
                raise _Retryable("source transport failed") from None
        raise AcquisitionError("source exceeded redirect bound")

    def capture(self, url: str, *, max_bytes: int) -> ResponseCapture:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.validate_url(url)

        def attempt() -> ResponseCapture:
            facts = {}
            body = bytearray()
            try:
                for chunk in self._chunks(url, facts=facts):
                    if len(body) + len(chunk) > max_bytes:
                        raise AcquisitionError("metadata response exceeds its byte bound")
                    body.extend(chunk)
            except Exception as error:
                attach_refused_response(error, RefusedResponse(url, "transport", None, "application/octet-stream"))
                raise
            return ResponseCapture(url, facts["resolved_url"], facts["media_type"], facts["observed_at"], bytes(body))

        return retry_http(attempt, retryable=(_Retryable,), max_attempts=3)

    def download(
        self,
        url: str,
        *,
        store: Path,
        max_bytes: int,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
        etag: str | None = None,
        allow_html: bool = False,
        validate_prefix: Callable[[bytes], None] | None = None,
    ) -> dict:
        """Stream one explicit asset, or verify and reuse a known local digest.

        Interrupted attempts are cleaned up by the writer and restarted, never
        appended to another version. A source ETag binds the request with
        If-Match; it is not a content digest. Range resume belongs to the caller
        until a retained version and partial-file receipt are supplied.
        """
        self.validate_url(url)
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        writer = LocalBlobWriter(store)

        def attempt() -> dict:
            facts = {}

            def chunks() -> Iterator[bytes]:
                first = True
                extra = {"If-Match": etag} if etag else None
                for chunk in self._chunks(url, facts=facts, extra_headers=extra, require_identity=True):
                    if first:
                        first = False
                        validate_body_prefix(chunk, media_type=facts["media_type"], allow_html=allow_html)
                        if etag and facts["etag"] != etag:
                            raise AcquisitionError("asset ETag does not match its selected version")
                        if validate_prefix is not None:
                            validate_prefix(chunk)
                    yield chunk
                if first:
                    raise AcquisitionError("asset response is empty")

            result = writer.put(
                chunks(), max_bytes=max_bytes, expected_digest=expected_sha256, expected_size=expected_size
            )
            return {
                "url": url,
                "sha256": result.digest,
                "bytes": result.byte_size,
                "blob_path": result.object_key,
                "reused": result.reused,
                "downloaded": bool(facts),
                "response": facts,
            }

        return retry_http(attempt, retryable=(_Retryable,), max_attempts=3)


def validate_body_prefix(chunk: bytes, *, media_type: str, allow_html: bool) -> None:
    """Reject accidental HTML captures; XHTML must declare its XML namespace.

    This is a representation check, not full document/archive validation.
    """
    kind = media_type.lower().split(";", 1)[0]
    prefix = chunk.lstrip().lower()
    if kind == "application/xhtml+xml":
        parser = ET.XMLPullParser(events=("start",))
        try:
            parser.feed(chunk)
            first = next(parser.read_events(), None)
            if first is None or first[1].tag != "{http://www.w3.org/1999/xhtml}html":
                raise AcquisitionError("XHTML asset omitted its namespaced html root")
        except ET.ParseError:
            raise AcquisitionError("XHTML asset has an invalid XML prefix") from None
    elif not allow_html and (kind == "text/html" or prefix.startswith((b"<!doctype html", b"<html"))):
        raise AcquisitionError("asset returned HTML; select an HTML body explicitly if intended")
