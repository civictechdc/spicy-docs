"""Exact GAO product-page evidence for one source-native release.

GAO product pages expose one publisher-assigned topic as a literal topic slug and label; turning
that observation into a RefSpec concept or a search tag is not this product's job, so this module
captures the exact HTML, proves its product identity, and preserves the one literal publisher field
without importing either sibling product. GAO refuses its ordinary direct client, so the operator
path uses the bounded Zyte adapter in :mod:`spicy_docs.sources.zyte`; credentials remain in the
process environment and never enter a request key, record, evidence ZIP, error, or release.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from html.parser import HTMLParser
from io import BytesIO
from itertools import pairwise
from typing import Any, Final, cast
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from rulespec_artifacts import (
    FramedSection,
    canonical_json_bytes,
    framed_section_digest,
    schema_bundle_digest,
)

from spicy_docs.reading.evidence_zip import (
    deterministic_zip_entry,
    has_deterministic_zip_metadata,
)
from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response
from spicy_docs.sources.zyte import ZyteHttpResponse

SOURCE_SYSTEM_ID: Final = "https://www.gao.gov/products"
SOURCE_SYSTEM_VERSION: Final = "html-product-page-v1"
SCOPE_ID: Final = "gao-product-pages"
SCHEMA_NAME: Final = "gao-product-page-raw"
SCHEMA_VERSION: Final = "1.0"
SCHEMA_PATH: Final = "sources/gao-product-page-raw-1.0.schema.json"
SOURCE_SCHEMA_KEY: Final = "schemas/gao-product-page-raw-1.0.schema.json"
RECORD_STEM: Final = "gao-product-page"
ACQUISITION_POLICY_ID: Final = "urn:spicy-docs:acquisition:gao-product-page-zyte-enumeration"
ACQUISITION_POLICY_VERSION: Final = "1.1"
MAX_TRAVERSALS: Final = 1
MAX_PRODUCT_IDS: Final = 1_000
MAX_PRODUCT_ID_LENGTH: Final = 128
MAX_TOPIC_SLUG_LENGTH: Final = 128
MAX_TOPIC_LABEL_LENGTH: Final = 512
MAX_PAGE_BYTES: Final = 8 * 1024 * 1024
MAX_TOTAL_HTML_BYTES: Final = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES: Final = 64 * 1024
FETCH_TIMEOUT_SECONDS: Final = 90.0
EVIDENCE_TYPE: Final = "gao-product-page-evidence-v1"
EVIDENCE_MEDIA_TYPE: Final = "application/zip"
TRANSPORT_ID: Final = "zyte-raw-http-v1"

_ASCII_SLUG: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOPIC_FIELD_CLASS: Final = "views-field-field-topic"
_MANIFEST_FIELDS: Final = frozenset(
    {
        "byteLength",
        "contentType",
        "entry",
        "evidenceType",
        "productId",
        "requestedUrl",
        "resolvedUrl",
        "sha256",
        "targetStatus",
        "transport",
    }
)
_RECORD_FIELDS: Final = frozenset(
    {
        "canonicalUrl",
        "contentType",
        "htmlByteLength",
        "htmlSha256",
        "productId",
        "publisherTopic",
        "requestedUrl",
        "resolvedUrl",
        "targetStatus",
        "transport",
    }
)
_TOPIC_FIELDS: Final = frozenset({"href", "label", "slug"})
_HREF_ATTRIBUTE: Final = frozenset({"href"})


class GaoProductSourceError(ValueError):
    """GAO evidence cannot prove the requested product-page release."""


GaoProductFetch = Callable[[str], ZyteHttpResponse]


def _product_id(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_PRODUCT_ID_LENGTH or _ASCII_SLUG.fullmatch(value) is None:
        raise GaoProductSourceError("GAO product IDs must be bounded lowercase ASCII slugs")
    return value


def gao_product_url(product_id: str) -> str:
    return f"{SOURCE_SYSTEM_ID}/{_product_id(product_id)}"


def gao_product_query_scope(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an explicit closed product set in O(N) time and O(N) space."""

    if set(value) != {"productIds"}:
        raise GaoProductSourceError("GAO query scope fields differ")
    product_ids = value.get("productIds")
    if not isinstance(product_ids, list) or not product_ids or len(product_ids) > MAX_PRODUCT_IDS:
        raise GaoProductSourceError(f"GAO product IDs must contain between 1 and {MAX_PRODUCT_IDS} members")
    typed = [_product_id(value) for value in product_ids]
    if any(left >= right for left, right in pairwise(typed)):
        raise GaoProductSourceError("GAO product IDs must be ASCII-sorted and distinct")
    return {"productIds": typed}


@dataclass(frozen=True, slots=True)
class GaoProductPage:
    """One deterministic ZIP containing one exact, bounded GAO HTML page."""

    traversal_index: int
    page_index: int
    window_index: int
    window_page_index: int
    request_key: str
    source_cursor: str | None
    response_bytes: bytes

    @property
    def evidence_media_type(self) -> str:
        return EVIDENCE_MEDIA_TYPE

    def __post_init__(self) -> None:
        if min(self.traversal_index, self.page_index, self.window_index, self.window_page_index) < 0:
            raise GaoProductSourceError("GAO page indexes must be non-negative")
        if self.traversal_index != 0:
            raise GaoProductSourceError("GAO explicit enumeration has one traversal")
        if self.window_index != self.page_index or self.window_page_index != 0:
            raise GaoProductSourceError("GAO product pages must be explicit one-page windows")
        if self.source_cursor is not None:
            raise GaoProductSourceError("GAO explicit enumeration does not use cursors")
        parse_gao_product_request(self.request_key)
        if not self.response_bytes:
            raise GaoProductSourceError("GAO evidence ZIP must not be empty")


@dataclass(frozen=True, slots=True)
class GaoProductWindow:
    product_id: str


def parse_gao_product_request(value: str) -> GaoProductWindow:
    """Parse one canonical ``https://www.gao.gov/products/<slug>`` URL and refuse request drift."""
    parsed = urlsplit(value)
    path = parsed.path.split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.gao.gov"
        or len(path) != 3
        or path[:2] != ["", "products"]
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise GaoProductSourceError("GAO product request URL is invalid")
    product_id = _product_id(path[2])
    if gao_product_url(product_id) != value:
        raise GaoProductSourceError("GAO product request URL is not canonical")
    return GaoProductWindow(product_id=product_id)


def _capture_manifest(product_id: str, response: ZyteHttpResponse) -> dict[str, Any]:
    url = gao_product_url(product_id)
    if response.requested_url != url:
        raise GaoProductSourceError("GAO capture requested URL differs from its product ID")
    if response.resolved_url != url:
        raise GaoProductSourceError("GAO capture resolved URL differs from its product ID")
    if response.status_code != 200:
        raise GaoProductSourceError("GAO target status must be 200")
    content_type = response.content_type
    if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().casefold() != "text/html":
        raise GaoProductSourceError("GAO target Content-Type must be text/html")
    body = response.body
    if not isinstance(body, bytes) or not body or len(body) > MAX_PAGE_BYTES:
        raise GaoProductSourceError(f"GAO target HTML exceeds its {MAX_PAGE_BYTES}-byte bound or is empty")
    return {
        "byteLength": len(body),
        "contentType": content_type,
        "entry": "product.html",
        "evidenceType": EVIDENCE_TYPE,
        "productId": product_id,
        "requestedUrl": response.requested_url,
        "resolvedUrl": response.resolved_url,
        "sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "targetStatus": response.status_code,
        "transport": TRANSPORT_ID,
    }


def _evidence_zip(manifest: Mapping[str, Any], body: bytes) -> bytes:
    manifest_bytes = canonical_json_bytes(dict(manifest))
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise GaoProductSourceError("GAO evidence manifest exceeds its byte bound")
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(deterministic_zip_entry("manifest.json"), manifest_bytes)
        archive.writestr(deterministic_zip_entry("product.html"), body)
    return output.getvalue()


def _decode_manifest(raw: bytes) -> Mapping[str, Any]:
    def distinct_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise GaoProductSourceError(f"GAO evidence manifest repeats field {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=distinct_pairs)
    except GaoProductSourceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GaoProductSourceError("GAO evidence manifest is invalid JSON") from error
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_FIELDS:
        raise GaoProductSourceError("GAO evidence manifest fields differ")
    if canonical_json_bytes(dict(value)) != raw:
        raise GaoProductSourceError("GAO evidence manifest is not canonical JSON")
    return value


class _GaoHtmlFields(HTMLParser):
    """Read only source identity and the one publisher topic field."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_urls: list[str] = []
        self.topic_field_count = 0
        self.topics: list[dict[str, str]] = []
        self._div_depth = 0
        self._topic_field_depth: int | None = None
        self._active_topic: dict[str, Any] | None = None

    @staticmethod
    def _attrs(
        values: list[tuple[str, str | None]],
        *,
        relevant: frozenset[str],
    ) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for name, value in values:
            if name not in relevant:
                continue
            if name in result:
                raise GaoProductSourceError(f"GAO HTML repeats attribute {name!r}")
            result[name] = value
        return result

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "link":
            rels = [value for name, value in attrs if name == "rel"]
            if any(isinstance(rel, str) and "canonical" in rel.casefold().split() for rel in rels):
                hrefs = [value for name, value in attrs if name == "href"]
                if len(rels) != 1 or len(hrefs) != 1 or not isinstance(hrefs[0], str) or not hrefs[0]:
                    raise GaoProductSourceError("GAO canonical link lacks href")
                self.canonical_urls.append(hrefs[0])
        if tag == "div":
            self._div_depth += 1
            class_values = [value for name, value in attrs if name == "class"]
            marker_values = [
                value for value in class_values if isinstance(value, str) and _TOPIC_FIELD_CLASS in value.split()
            ]
            if marker_values:
                if len(class_values) != 1 or len(marker_values) != 1:
                    raise GaoProductSourceError("GAO publisher topic field repeats its class attribute")
                self.topic_field_count += 1
                if self._topic_field_depth is not None:
                    raise GaoProductSourceError("GAO topic fields are nested")
                self._topic_field_depth = self._div_depth
        if tag == "a" and self._topic_field_depth is not None:
            attributes = self._attrs(attrs, relevant=_HREF_ATTRIBUTE)
            if self._active_topic is not None:
                raise GaoProductSourceError("GAO topic anchors are nested")
            href = attributes.get("href")
            if not isinstance(href, str) or not href.startswith("/topics/"):
                raise GaoProductSourceError("GAO publisher topic field contains a non-topic anchor")
            slug = href.removeprefix("/topics/")
            if (
                not slug
                or len(slug) > MAX_TOPIC_SLUG_LENGTH
                or _ASCII_SLUG.fullmatch(slug) is None
                or href != f"/topics/{slug}"
            ):
                raise GaoProductSourceError("GAO publisher topic anchor has an unsafe slug")
            self._active_topic = {"href": href, "label": [], "slug": slug}
        elif self._active_topic is not None:
            raise GaoProductSourceError("GAO publisher topic label contains nested markup")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_topic is not None:
            raw_label = "".join(cast(list[str], self._active_topic["label"]))
            label = raw_label.strip()
            if not label or len(raw_label) > MAX_TOPIC_LABEL_LENGTH:
                raise GaoProductSourceError("GAO publisher topic label is empty or exceeds its bound")
            self.topics.append(
                {
                    "href": str(self._active_topic["href"]),
                    "label": label,
                    "slug": str(self._active_topic["slug"]),
                }
            )
            self._active_topic = None
        if tag == "div":
            if self._topic_field_depth == self._div_depth:
                if self._active_topic is not None:
                    raise GaoProductSourceError("GAO publisher topic anchor is unterminated")
                self._topic_field_depth = None
            self._div_depth -= 1
            if self._div_depth < 0:
                raise GaoProductSourceError("GAO HTML div structure is invalid")

    def handle_data(self, data: str) -> None:
        if self._active_topic is not None:
            cast(list[str], self._active_topic["label"]).append(data)


def _publisher_fields(body: bytes, *, expected_url: str) -> tuple[str, dict[str, str]]:
    """Extract fields in O(B) time and O(B + L) temporary space.

    ``B`` is capped at :data:`MAX_PAGE_BYTES`; ``L`` is the one literal topic
    label.  The full UTF-8 decode is intentional because HTML parsing is a
    bounded per-page operation, never a whole-corpus accumulator.
    """

    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise GaoProductSourceError("GAO target HTML is not valid UTF-8") from error
    parser = _GaoHtmlFields()
    try:
        parser.feed(text)
        parser.close()
    except GaoProductSourceError:
        raise
    except Exception as error:
        raise GaoProductSourceError("GAO target HTML could not be parsed") from error
    if parser._topic_field_depth is not None or parser._active_topic is not None:
        raise GaoProductSourceError("GAO publisher topic field is unterminated")
    if parser.canonical_urls != [expected_url]:
        raise GaoProductSourceError("GAO canonical URL differs from its requested product URL")
    if parser.topic_field_count != 1 or len(parser.topics) != 1:
        raise GaoProductSourceError("GAO page must contain exactly one publisher topic field with one topic anchor")
    return parser.canonical_urls[0], parser.topics[0]


def _manifest_value(manifest: Mapping[str, Any], name: str, expected_type: type) -> Any:
    value = manifest.get(name)
    if not isinstance(value, expected_type) or expected_type is int and isinstance(value, bool):
        raise GaoProductSourceError(f"GAO evidence manifest {name} has the wrong type")
    return value


def parse_gao_product_page_response(raw: bytes) -> Mapping[str, Any]:
    """Replay one bounded ZIP in O(B) time and O(B) working space."""

    try:
        archive = ZipFile(BytesIO(raw), "r")
    except BadZipFile as error:
        raise GaoProductSourceError("GAO evidence is not a ZIP file") from error
    with archive:
        infos = archive.infolist()
        if [info.filename for info in infos] != ["manifest.json", "product.html"]:
            raise GaoProductSourceError("GAO evidence ZIP membership or order differs")
        if any(info.is_dir() or info.flag_bits & 0x1 for info in infos):
            raise GaoProductSourceError("GAO evidence ZIP contains a directory or encrypted member")
        if any(
            not has_deterministic_zip_metadata(info, name=name)
            for info, name in zip(infos, ("manifest.json", "product.html"), strict=True)
        ):
            raise GaoProductSourceError("GAO evidence ZIP member metadata differs")
        manifest_info, html_info = infos
        if manifest_info.file_size > MAX_MANIFEST_BYTES or html_info.file_size > MAX_PAGE_BYTES:
            raise GaoProductSourceError("GAO evidence ZIP member exceeds its byte bound")
        try:
            manifest_bytes = archive.read(manifest_info)
            body = archive.read(html_info)
        except (BadZipFile, OSError) as error:
            raise GaoProductSourceError("GAO evidence ZIP member is invalid") from error
    manifest = _decode_manifest(manifest_bytes)
    product_id = _product_id(_manifest_value(manifest, "productId", str))
    expected_url = gao_product_url(product_id)
    byte_length = _manifest_value(manifest, "byteLength", int)
    sha256 = _manifest_value(manifest, "sha256", str)
    content_type = _manifest_value(manifest, "contentType", str)
    requested_url = _manifest_value(manifest, "requestedUrl", str)
    resolved_url = _manifest_value(manifest, "resolvedUrl", str)
    target_status = _manifest_value(manifest, "targetStatus", int)
    if (
        manifest.get("entry") != "product.html"
        or manifest.get("evidenceType") != EVIDENCE_TYPE
        or manifest.get("transport") != TRANSPORT_ID
        or requested_url != expected_url
        or resolved_url != expected_url
        or target_status != 200
        or content_type.split(";", 1)[0].strip().casefold() != "text/html"
        or byte_length != len(body)
        or sha256 != "sha256:" + hashlib.sha256(body).hexdigest()
    ):
        raise GaoProductSourceError("GAO evidence metadata differs from its exact HTML")
    canonical_url, topic = _publisher_fields(body, expected_url=expected_url)
    record = {
        "canonicalUrl": canonical_url,
        "contentType": content_type,
        "htmlByteLength": byte_length,
        "htmlSha256": sha256,
        "productId": product_id,
        "publisherTopic": topic,
        "requestedUrl": requested_url,
        "resolvedUrl": resolved_url,
        "targetStatus": target_status,
        "transport": TRANSPORT_ID,
    }
    return {
        "_evidenceType": EVIDENCE_TYPE,
        "_productId": product_id,
        "count": 1,
        "next_page_url": None,
        "results": [record],
        "total_pages": 1,
    }


def classify_gao_product_page(value: object) -> dict[str, Any]:
    """Return one faithful, closed product-page record and reject schema drift."""
    if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS:
        raise GaoProductSourceError("GAO product-page record fields differ")
    product_id = _product_id(value.get("productId"))
    expected_url = gao_product_url(product_id)
    for name in ("canonicalUrl", "requestedUrl", "resolvedUrl"):
        if value.get(name) != expected_url:
            raise GaoProductSourceError(f"GAO product-page {name} differs")
    if value.get("targetStatus") != 200 or value.get("transport") != TRANSPORT_ID:
        raise GaoProductSourceError("GAO product-page transport metadata differs")
    content_type = value.get("contentType")
    if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().casefold() != "text/html":
        raise GaoProductSourceError("GAO product-page Content-Type differs")
    byte_length = value.get("htmlByteLength")
    if isinstance(byte_length, bool) or not isinstance(byte_length, int) or not 0 < byte_length <= MAX_PAGE_BYTES:
        raise GaoProductSourceError("GAO product-page byte length is invalid")
    digest = value.get("htmlSha256")
    if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise GaoProductSourceError("GAO product-page digest is invalid")
    topic = value.get("publisherTopic")
    if not isinstance(topic, Mapping) or set(topic) != _TOPIC_FIELDS:
        raise GaoProductSourceError("GAO publisher topic fields differ")
    slug = topic.get("slug")
    label = topic.get("label")
    if (
        not isinstance(slug, str)
        or len(slug) > MAX_TOPIC_SLUG_LENGTH
        or _ASCII_SLUG.fullmatch(slug) is None
        or topic.get("href") != f"/topics/{slug}"
        or not isinstance(label, str)
        or not label
        or len(label) > MAX_TOPIC_LABEL_LENGTH
    ):
        raise GaoProductSourceError("GAO publisher topic value is invalid")
    canonical_json_bytes(dict(value))
    return dict(value)


def source_record_id(record: Mapping[str, Any]) -> str:
    """The product ID is the source record identity."""
    return _product_id(record.get("productId"))


def source_record(record: Mapping[str, Any], *, schema_digest: str) -> dict[str, Any]:
    return {
        "fieldDiagnostics": [],
        "record": dict(record),
        "schemaDigest": schema_digest,
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "scopeId": SCOPE_ID,
        "sourceRecordId": source_record_id(record),
    }


def rendition_rows(record: Mapping[str, Any]) -> tuple[()]:
    """GAO product pages state no renditions."""
    del record
    return ()


def source_record_digest(record: Mapping[str, Any]) -> str:
    return framed_section_digest(
        "spicydocs-gao-product-page-record/1",
        (FramedSection("record", 1, (dict(record),)),),
    )


def gao_product_next_page_url(response: Mapping[str, Any], *, seen_urls: set[str]) -> None:
    """Refuse pagination: explicit product-page evidence is one page per product."""
    del seen_urls
    if response.get("next_page_url") is not None:
        raise GaoProductSourceError("GAO explicit product-page evidence cannot paginate")


@dataclass(slots=True)
class GaoProductTraversalCheck:
    observed_pages: int = 0

    def add(self, response: Mapping[str, Any], *, page_index: int) -> None:
        results = response.get("results")
        if page_index != 0 or not isinstance(results, list) or len(results) != 1 or response.get("count") != 1:
            raise GaoProductSourceError("GAO product-page inventory differs")
        self.observed_pages += 1

    def finish(self) -> None:
        if self.observed_pages != 1:
            raise GaoProductSourceError("GAO product-page window is incomplete")


def gao_product_records_included(
    response: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> bool:
    """Profile hook: one requested product must yield exactly its own one-record page."""
    del query_scope
    if not isinstance(page_window, GaoProductWindow):
        raise GaoProductSourceError("GAO page lacks a validated product request")
    results = response.get("results")
    if (
        response.get("_evidenceType") != EVIDENCE_TYPE
        or response.get("_productId") != page_window.product_id
        or not isinstance(results, list)
        or len(results) != 1
    ):
        raise GaoProductSourceError("GAO request and exact page evidence differ")
    return True


def validate_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    """Refuse a record whose product ID differs from the page window's requested product."""
    del query_scope
    if not isinstance(page_window, GaoProductWindow) or source_record_id(record) != page_window.product_id:
        raise GaoProductSourceError("GAO product-page record falls outside its explicit scope")


@dataclass(slots=True)
class GaoProductAcquisitionCheck:
    """Prove that the one traversal covers the requested IDs exactly once."""

    observed_product_ids: list[str] = field(default_factory=list)

    def add_window(
        self,
        response: Mapping[str, Any],
        *,
        page_window: object | None,
        records_included: bool,
        response_bytes: bytes,
    ) -> None:
        del response_bytes
        if (
            not isinstance(page_window, GaoProductWindow)
            or response.get("_productId") != page_window.product_id
            or records_included is not True
        ):
            raise GaoProductSourceError("GAO product request and evidence identity differ")
        if self.observed_product_ids and page_window.product_id <= self.observed_product_ids[-1]:
            raise GaoProductSourceError("GAO product pages are repeated or unordered")
        self.observed_product_ids.append(page_window.product_id)

    def finish(self, *, query_scope: Mapping[str, Any]) -> None:
        if self.observed_product_ids != query_scope.get("productIds"):
            raise GaoProductSourceError("GAO acquisition does not cover the exact requested products")


def gao_product_acquisition_policy(query_scope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "coverageLimits": [
            "Only the explicitly requested product IDs are covered; other product IDs are unrequested.",
            "Each requested page is captured separately; no single publisher-wide version is established.",
        ],
        "evidence": "one-deterministic-bounded-zip-per-exact-html-page",
        "initialQueryScope": gao_product_query_scope(query_scope),
        "maxHtmlBytesPerProduct": MAX_PAGE_BYTES,
        "maxTotalHtmlBytes": MAX_TOTAL_HTML_BYTES,
        "maxProductIds": MAX_PRODUCT_IDS,
        "maxTraversals": MAX_TRAVERSALS,
        "publisherField": "exactly-one-/topics/<slug>-anchor-in-views-field-field-topic",
        "strategy": "complete-explicit-product-id-enumeration",
        "transport": TRANSPORT_ID,
    }


def _refused_gao_response(request_key: str, response: ZyteHttpResponse, *, total_html_bytes: int) -> RefusedResponse:
    """Describe exact diagnostic bytes without exceeding acquisition bounds."""

    body = response.body
    byte_size = len(body) if isinstance(body, bytes) else None
    unavailable_reason = None
    if byte_size is None:
        unavailable_reason = "unsupported-response"
    elif byte_size > MAX_PAGE_BYTES:
        unavailable_reason = "response-byte-limit"
    elif total_html_bytes + byte_size > MAX_TOTAL_HTML_BYTES:
        unavailable_reason = "acquisition-byte-limit"
    content_type = response.content_type
    is_html = isinstance(content_type, str) and content_type.split(";", 1)[0].strip().casefold() == "text/html"
    return RefusedResponse(
        request_key=request_key,
        stage="source-validation",
        response_bytes=body if unavailable_reason is None else None,
        media_type="text/html" if is_html and unavailable_reason is None else "application/octet-stream",
        unavailable_reason=unavailable_reason,
        observed_byte_size=byte_size,
    )


def iter_gao_product_pages(
    fetch: GaoProductFetch,
    *,
    query_scope: Mapping[str, Any],
) -> Generator[GaoProductPage, None, None]:
    """Acquire ``N`` products in O(N + H) time and O(N + B) space.

    ``H`` is total HTML bytes and ``B`` is the largest page, capped at 8 MiB.
    The generator retains the validated ID list plus one response/ZIP at a
    time; it never accumulates the corpus.  Network latency remains O(N)
    sequential requests so the source is not burst-loaded.
    """

    scope = gao_product_query_scope(query_scope)
    total_html_bytes = 0
    for page_index, product_id in enumerate(cast(Sequence[str], scope["productIds"])):
        url = gao_product_url(product_id)
        try:
            response = fetch(url)
        except Exception as error:
            attach_refused_response(
                error,
                RefusedResponse(
                    request_key=url,
                    stage="transport",
                    response_bytes=None,
                    media_type="application/octet-stream",
                    unavailable_reason="transport-unavailable",
                ),
            )
            raise
        if not isinstance(response, ZyteHttpResponse):
            error = GaoProductSourceError("GAO fetcher returned an unsupported response")
            attach_refused_response(
                error,
                RefusedResponse(
                    request_key=url,
                    stage="source-validation",
                    response_bytes=None,
                    media_type="application/octet-stream",
                    unavailable_reason="unsupported-response",
                ),
            )
            raise error
        try:
            manifest = _capture_manifest(product_id, response)
            if total_html_bytes + len(response.body) > MAX_TOTAL_HTML_BYTES:
                raise GaoProductSourceError("GAO acquisition exceeds its total HTML byte bound")
            # Refused target bytes travel with the error for diagnostic retention;
            # they never become a successful page or an admitted source record.
            _publisher_fields(response.body, expected_url=url)
            evidence_bytes = _evidence_zip(manifest, response.body)
        except GaoProductSourceError as error:
            attach_refused_response(error, _refused_gao_response(url, response, total_html_bytes=total_html_bytes))
            raise
        total_html_bytes += len(response.body)
        yield GaoProductPage(
            traversal_index=0,
            page_index=page_index,
            window_index=page_index,
            window_page_index=0,
            request_key=url,
            source_cursor=None,
            response_bytes=evidence_bytes,
        )


GAO_PRODUCT_PAGE_SCHEMA: Final = {
    "$id": "urn:spicy-docs:schema:gao-product-page-raw:1.0",
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "additionalProperties": False,
    "properties": {
        "canonicalUrl": {"format": "uri", "type": "string"},
        "contentType": {"minLength": 1, "type": "string"},
        "htmlByteLength": {"maximum": MAX_PAGE_BYTES, "minimum": 1, "type": "integer"},
        "htmlSha256": {"pattern": "^sha256:[0-9a-f]{64}$", "type": "string"},
        "productId": {
            "maxLength": MAX_PRODUCT_ID_LENGTH,
            "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
            "type": "string",
        },
        "publisherTopic": {
            "additionalProperties": False,
            "properties": {
                "href": {"pattern": "^/topics/[a-z0-9]+(?:-[a-z0-9]+)*$", "type": "string"},
                "label": {"maxLength": MAX_TOPIC_LABEL_LENGTH, "minLength": 1, "type": "string"},
                "slug": {
                    "maxLength": MAX_TOPIC_SLUG_LENGTH,
                    "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                    "type": "string",
                },
            },
            "required": ["href", "label", "slug"],
            "type": "object",
        },
        "requestedUrl": {"format": "uri", "type": "string"},
        "resolvedUrl": {"format": "uri", "type": "string"},
        "targetStatus": {"const": 200},
        "transport": {"const": TRANSPORT_ID},
    },
    "required": sorted(_RECORD_FIELDS),
    "type": "object",
    "x-spicy-record-order": [
        {
            "fieldPath": "/productId",
            "nullOrder": "forbidden",
            "tupleComparison": "utf16-code-unit",
            "valueType": "string",
        }
    ],
}


#: The schema is constant; cache its digest once per process across publish/replay.
@cache
def source_schema_digest() -> str:
    return schema_bundle_digest({SCHEMA_PATH: GAO_PRODUCT_PAGE_SCHEMA})


def source_schema_declaration() -> dict[str, str]:
    return {
        "schemaDigest": source_schema_digest(),
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
    }


__all__ = [
    "ACQUISITION_POLICY_ID",
    "ACQUISITION_POLICY_VERSION",
    "FETCH_TIMEOUT_SECONDS",
    "GAO_PRODUCT_PAGE_SCHEMA",
    "MAX_PAGE_BYTES",
    "MAX_PRODUCT_IDS",
    "MAX_TOTAL_HTML_BYTES",
    "MAX_TRAVERSALS",
    "RECORD_STEM",
    "SCOPE_ID",
    "SOURCE_SCHEMA_KEY",
    "SOURCE_SYSTEM_ID",
    "SOURCE_SYSTEM_VERSION",
    "GaoProductAcquisitionCheck",
    "GaoProductFetch",
    "GaoProductPage",
    "GaoProductSourceError",
    "GaoProductTraversalCheck",
    "classify_gao_product_page",
    "gao_product_acquisition_policy",
    "gao_product_next_page_url",
    "gao_product_query_scope",
    "gao_product_records_included",
    "gao_product_url",
    "iter_gao_product_pages",
    "parse_gao_product_page_response",
    "parse_gao_product_request",
    "rendition_rows",
    "source_record",
    "source_record_digest",
    "source_schema_declaration",
    "source_schema_digest",
    "validate_record_scope",
]
