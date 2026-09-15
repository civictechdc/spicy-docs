"""Official FEC raw metadata readers and independently selected asset transfers."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Self
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from rulespec_artifacts import LocalBlobWriter

from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response
from spicy_docs.reading.s3_listing import parse_s3_listing
from spicy_docs.sources.fec.assets import validate_original_prefix
from spicy_docs.sources.fec.catalog import (
    API_ROOT,
    BUCKET,
    BUCKET_URL,
    MAX_METADATA_BYTES,
    PREFIXES,
    api_operations,
    official_url,
)
from spicy_docs.sources.fec.metadata import api_page, parse_api, parse_page_links, parse_sitemap, split_record
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.download import (
    AcquisitionError,
    BoundedAcquirer,
    ResponseCapture,
)


def _url(url: str, changes: Mapping) -> str:
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in changes]
    query.extend((k, str(v).lower() if isinstance(v, bool) else v) for k, v in changes.items() if v is not None)
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query, doseq=True), ""))


def _positive(value: int, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


class FecClient:
    """Metadata requests never download linked documents, archives or media.

    Every yielded page points to its retained exact response. Iterators are
    bounded by max_pages and fail if a continuation remains at that bound.
    Previously yielded pages remain partial observations when iteration fails;
    only normal iterator exhaustion completes the selected traversal.
    """

    def __init__(self, *, store: Path, api_key: str | None = None, zyte_on_denial=None, **transport_options) -> None:
        if api_key is not None and (not api_key.strip() or api_key != api_key.strip()):
            raise ValueError("FEC API key must be nonempty without surrounding whitespace")
        self.store = Path(store)
        self._writer = LocalBlobWriter(self.store)
        self._key = api_key
        self.http = BoundedAcquirer(
            validate_url=official_url,
            zyte_on_denial=zyte_on_denial,
            public_fallback_url=lambda url: urlsplit(url).hostname != "api.open.fec.gov",
            headers=lambda url: (
                {"X-Api-Key": self._key} if self._key and urlsplit(url).hostname == "api.open.fec.gov" else {}
            ),
            **transport_options,
        )

    def __enter__(self) -> Self:
        self.http.__enter__()
        return self

    def __exit__(self, *error: object) -> None:
        self.http.__exit__(*error)

    def _capture(self, url: str) -> ResponseCapture:
        result = self.http.capture(url, max_bytes=MAX_METADATA_BYTES)
        if self._key and self._key.encode() in result.body:
            raise CredentialRefusedError("source response echoed the API credential; capture was not retained")
        return result

    def _page(
        self, capture: ResponseCapture, *, records: list[tuple[str, object]], continuation: str | None, **context
    ) -> dict:
        stored = self._writer.put([capture.body], max_bytes=MAX_METADATA_BYTES, expected_digest=capture.sha256)
        return {
            "source": "fec",
            "request_url": capture.url,
            "resolved_url": capture.resolved_url,
            "observed_at": capture.observed_at,
            "media_type": capture.media_type,
            "via": capture.via,
            "evidence": {"sha256": stored.digest, "bytes": stored.byte_size, "blob_path": stored.object_key},
            "records": [split_record(value, source_pointer=path) for path, value in records],
            "next_url": continuation,
            "scope": "observed source traversal; no frozen publisher snapshot",
            **context,
        }

    def _parsed(self, capture: ResponseCapture, parser, **kwargs):
        try:
            return parser(capture.body, **kwargs)
        except (ValueError, SyntaxError) as error:
            attach_refused_response(
                error, RefusedResponse(capture.url, "source-validation", capture.body, capture.media_type)
            )
            raise

    def api(self, path: str, *, params: Mapping | None = None, max_pages: int = 100) -> Iterator[dict]:
        """Read documented GET operations; use bulk for transaction backfills.

        API credentials use X-Api-Key and never enter request URLs. Pass all
        source filters explicitly: this reader does not silently select current
        reports or exclude amendments. API numeric decimals remain Decimal.
        """
        _positive(max_pages, "max_pages")
        if not self._key:
            raise ValueError("OpenFEC acquisition requires an explicit API key")
        operations = api_operations()
        modes = (
            [operations[path]]
            if path in operations
            else [
                mode
                for template, mode in operations.items()
                if re.fullmatch(re.sub(r"\\\{[^}]+\\\}", r"[^/?]+", re.escape(template)), path)
            ]
        )
        if len(modes) != 1:
            raise ValueError("path is not a supported official OpenFEC GET operation")
        mode = modes[0]
        if mode == "asset":
            raise ValueError("calendar export returns CSV/ICS; use download with an explicit byte bound")
        url = official_url(_url(API_ROOT + path, params or {}))
        seen = set()
        for _ in range(max_pages):
            if url in seen:
                raise AcquisitionError("FEC API repeated its continuation")
            seen.add(url)
            capture = self._capture(url)
            value = self._parsed(capture, parse_api)
            try:
                records, changes, context = api_page(value, url=url, mode=mode)
                if "api_version" in value:
                    context["api_version"] = value["api_version"]
            except ValueError as error:
                attach_refused_response(
                    error, RefusedResponse(url, "source-validation", capture.body, capture.media_type)
                )
                raise
            next_url = _url(url, changes) if changes is not None else None
            if next_url is not None:
                official_url(next_url)
            yield self._page(capture, records=records, continuation=next_url, **context)
            if next_url is None:
                return
            url = next_url
        raise AcquisitionError("FEC API page bound reached before a terminal response")

    def objects(self, prefix: str, *, max_pages: int = 1000, page_size: int = 1000) -> Iterator[dict]:
        """Enumerate metadata only under a published bulk/legal/export prefix."""
        _positive(max_pages, "max_pages")
        if not isinstance(prefix, str) or not prefix.startswith(PREFIXES):
            raise ValueError("FEC prefix must be under bulk-downloads/, legal/ or user-downloads/")
        if type(page_size) is not int or not 1 <= page_size <= 1000:
            raise ValueError("S3 page_size must be between 1 and 1000")
        token = None
        seen_tokens = set()
        previous_key = None
        for _ in range(max_pages):
            url = _url(
                BUCKET_URL, {"list-type": 2, "prefix": prefix, "max-keys": page_size, "continuation-token": token}
            )
            capture = self._capture(url)
            objects, token = self._parsed(capture, parse_s3_listing, bucket=BUCKET, prefix=prefix)
            rows = []
            for obj in objects:
                if previous_key is not None and obj.key <= previous_key:
                    raise AcquisitionError("FEC S3 listing keys repeated or ceased increasing")
                previous_key = obj.key
                rows.append(
                    (
                        None,
                        {
                            **asdict(obj),
                            "url": official_url(BUCKET_URL + quote(obj.key, safe="/")),
                            "fec_url": "https://www.fec.gov/files/" + quote(obj.key, safe="/"),
                        },
                    )
                )
            if token is not None and (not objects or token in seen_tokens):
                raise AcquisitionError("FEC S3 listing did not advance")
            seen_tokens.add(token)
            next_url = _url(url, {"continuation-token": token}) if token else None
            yield self._page(
                capture, records=rows, continuation=next_url, prefix=prefix, record_coordinates="S3 Key in retained XML"
            )
            if token is None:
                return
        raise AcquisitionError("FEC S3 page bound reached before IsTruncated=false")

    def sitemap(self, url: str, *, max_pages: int = 100) -> Iterator[dict]:
        """Follow only XML child indexes; leaf pages and documents stay unrequested."""
        _positive(max_pages, "max_pages")
        pending, seen = [official_url(url)], set()
        scheduled = set(pending)
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            if len(seen) >= max_pages:
                raise AcquisitionError("FEC sitemap page bound exhausted")
            seen.add(current)
            capture = self._capture(current)
            kind, rows = self._parsed(capture, parse_sitemap)
            if kind == "sitemapindex":
                for row in reversed(rows):
                    child = official_url(row["url"])
                    if child not in scheduled:
                        scheduled.add(child)
                        pending.append(child)
            yield self._page(
                capture,
                records=[(None, x) for x in rows],
                continuation=pending[-1] if pending else None,
                kind=kind,
                record_coordinates="loc in retained sitemap XML",
            )

    def page_links(self, url: str) -> dict:
        """Explicit HTML/XHTML discovery fallback for official collection pages."""
        if urlsplit(url).hostname not in {"www.fec.gov", "fec.gov", "transition.fec.gov"}:
            raise ValueError("collection page discovery requires an FEC website URL")
        capture = self._capture(url)
        value = self._parsed(capture, parse_page_links, url=capture.resolved_url)
        return self._page(
            capture,
            records=[(None, value)],
            continuation=None,
            record_coordinates="link labels/hrefs in retained page",
            discovery_only=True,
        )

    def download(self, url: str, *, max_bytes: int, **options) -> dict:
        """Download one caller-selected original; never infer alternate URLs."""
        if urlsplit(url).hostname == "api.open.fec.gov" and not self._key:
            raise ValueError("OpenFEC acquisition requires an explicit API key")
        options.setdefault("validate_prefix", lambda chunk: validate_original_prefix(chunk, url=url))
        return self.http.download(url, store=self.store, max_bytes=max_bytes, **options)
