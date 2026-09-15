"""HTTP admission for one CourtListener object and its conditional resumes."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass

from loguru import logger

from spicy_docs.transport.credentials import CredentialRefusedError

USER_AGENT = "spicy-regs/0.1 (+https://spicy-regs.dev) courtlistener-bulk-ingest"
MAX_ATTEMPTS = 5
_TIMEOUT = 180.0
_STRONG_ETAG = re.compile(r'"[\x21\x23-\x7e\x80-\xff]*"')
_RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)")


class BulkTransferError(RuntimeError):
    """Object identity or response framing is unsuitable; do not retry it."""


def close_response(response) -> None:
    """Cleanup must not hide the original transport or admission failure."""
    with suppress(Exception):
        response.close()


def raise_terminal(error: Exception) -> None:
    """Keep access and object-precondition refusals terminal through every retry layer."""
    if isinstance(error, (CredentialRefusedError, BulkTransferError)):
        raise error
    if isinstance(error, urllib.error.HTTPError) and error.code in {401, 403, 412}:
        close_response(error)
        if error.code in {401, 403}:
            raise CredentialRefusedError(f"CourtListener bulk: HTTP {error.code} access refused") from error
        raise BulkTransferError("CourtListener bulk: HTTP 412 object precondition failed") from error


def open_response(url: str, *, extra_headers: dict[str, str] | None = None, attempts: int = MAX_ATTEMPTS):
    """Retry initial connection errors; stream recovery passes attempts=1."""
    headers = {"User-Agent": USER_AGENT, **(extra_headers or {}), "Accept-Encoding": "identity"}
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=_TIMEOUT)
        except Exception as exc:
            raise_terminal(exc)
            if isinstance(exc, urllib.error.HTTPError):
                close_response(exc)
            if attempt == attempts:
                raise RuntimeError(f"CourtListener bulk: giving up on {url}") from exc
            logger.warning("CourtListener bulk: connection attempt {}/{} failed; retrying", attempt, attempts)
            time.sleep(min(2**attempt, 60))
    raise ValueError("CourtListener bulk: attempts must be positive")


def _header(response, name: str) -> str | None:
    headers = response.headers
    values = headers.get_all(name) if hasattr(headers, "get_all") else None
    if values is not None:
        if len(values) != 1:
            raise BulkTransferError(f"CourtListener bulk: repeated {name} header")
        value = values[0]
    else:
        value = headers.get(name)
    return value.strip(" \t") if value is not None else None


def _length(response) -> int | None:
    raw = _header(response, "Content-Length")
    if raw is None:
        return None
    if not re.fullmatch(r"[0-9]+", raw):
        raise BulkTransferError("CourtListener bulk: invalid Content-Length")
    try:
        return int(raw)
    except ValueError as exc:
        raise BulkTransferError("CourtListener bulk: invalid Content-Length") from exc


def _admit_encoding(response) -> None:
    encoding = _header(response, "Content-Encoding")
    if encoding is not None and encoding.lower() != "identity":
        raise BulkTransferError("CourtListener bulk: Content-Encoding must be identity")


def _admit_status(response, expected: int) -> None:
    status = response.status
    if status in {401, 403}:
        raise CredentialRefusedError(f"CourtListener bulk: HTTP {status} access refused")
    if status == 412:
        raise BulkTransferError("CourtListener bulk: HTTP 412 object precondition failed")
    if status != expected:
        raise BulkTransferError(f"CourtListener bulk: response answered {status}, not {expected}")


@dataclass
class BulkIdentity:
    """Original response identity; a validated range may supply a missing total."""

    resolved_url: str
    etag: str | None
    total: int | None

    @classmethod
    def initial(cls, response) -> BulkIdentity:
        _admit_status(response, 200)
        _admit_encoding(response)
        if _header(response, "Content-Range") is not None:
            raise BulkTransferError("CourtListener bulk: initial response must not contain Content-Range")
        etag = _header(response, "ETag")
        strong = etag is not None and _STRONG_ETAG.fullmatch(etag) is not None
        if etag is not None and not strong and not (etag.startswith("W/") and _STRONG_ETAG.fullmatch(etag[2:])):
            raise BulkTransferError("CourtListener bulk: malformed initial ETag")
        return cls(response.geturl(), etag if strong else None, _length(response))

    def resume_headers(self, offset: int) -> dict[str, str]:
        if self.etag is None:
            raise BulkTransferError("CourtListener bulk: safe resume requires a strong original ETag")
        return {"Range": f"bytes={offset}-", "If-Match": self.etag}

    def admit_resume(self, response, offset: int) -> None:
        _admit_status(response, 206)
        _admit_encoding(response)
        if response.geturl() != self.resolved_url:
            raise BulkTransferError("CourtListener bulk: resume resolved URL differs from the original object")
        if self.etag is None or _header(response, "ETag") != self.etag:
            raise BulkTransferError("CourtListener bulk: resume ETag differs from the original object")
        value = _header(response, "Content-Range")
        match = _RANGE.fullmatch(value or "")
        if match is None:
            raise BulkTransferError("CourtListener bulk: resume requires a complete numeric Content-Range")
        try:
            start, end, total = map(int, match.groups())
        except ValueError as exc:
            raise BulkTransferError("CourtListener bulk: invalid Content-Range") from exc
        if start != offset or end != total - 1 or total <= offset:
            raise BulkTransferError("CourtListener bulk: Content-Range does not cover the exact remaining bytes")
        if self.total is not None and total != self.total:
            raise BulkTransferError("CourtListener bulk: Content-Range total differs from the original object")
        length = _length(response)
        if length is not None and length != total - offset:
            raise BulkTransferError("CourtListener bulk: resumed Content-Length differs from Content-Range")
        self.total = total

    def check_length(self, observed: int, *, eof: bool = False) -> None:
        if self.total is not None and (observed > self.total or (eof and observed != self.total)):
            raise BulkTransferError("CourtListener bulk: received bytes differ from the advertised object length")
