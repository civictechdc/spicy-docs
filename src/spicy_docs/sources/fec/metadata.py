"""Pure FEC metadata parsing; linked bodies are never fetched by these functions."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit

from spicy_docs.sources.json_input import load_decimal_json
from spicy_docs.sources.media_types import media_type

BODY_FIELDS = frozenset({"text", "body", "html", "document_text", "extracted_text", "full_text"})
ASSET_SUFFIXES = (
    ".xml",
    ".json",
    ".xhtml",
    ".csv",
    ".txt",
    ".fec",
    ".zip",
    ".gz",
    ".bz2",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".mp3",
    ".mp4",
)


def pointer(parent: str, key: str | int) -> str:
    return parent + "/" + str(key).replace("~", "~0").replace("/", "~1")


def split_record(record: object, *, source_pointer: str | None = "") -> dict:
    """Lift embedded text into source pointers while preserving other fields.

    The exact response capture retains every removed value. These pointers are
    coordinates in that source JSON, not synthesized document URLs. Decimal
    values remain Decimal objects until the caller selects a serialization.
    """
    bodies, links = [], []

    def visit(value: object, path: str, key: str = "") -> object:
        if isinstance(value, dict):
            return {k: visit(v, pointer(path, k), k) for k, v in value.items() if not lift(k, v, pointer(path, k))}
        if isinstance(value, list):
            return [visit(v, pointer(path, i), key) for i, v in enumerate(value)]
        if isinstance(value, str) and value.startswith(("http://", "https://", "/")):
            suffix = urlsplit(value).path.lower()
            if suffix.endswith(ASSET_SUFFIXES) or key in {"pdf_url", "fec_url", "document_url", "file_url"}:
                links.append(
                    {
                        "url": resolve_link(value, base="https://www.fec.gov/"),
                        "source_pointer": path if source_pointer is not None else None,
                        "media_type": media_type(None, value),
                    }
                )
        return value

    def lift(key: str, value: object, path: str) -> bool:
        if (
            source_pointer is not None
            and key in BODY_FIELDS
            and isinstance(value, str)
            and not (key == "text" and {"subject", "citations"}.intersection(path.split("/")))
        ):
            bodies.append({"source_pointer": path, "characters": len(value), "field": key})
            return True
        return False

    metadata = visit(record, source_pointer or "")
    return {"metadata": metadata, "embedded_bodies": bodies, "assets": links, "source_pointer": source_pointer}


def parse_api(payload: bytes) -> dict:
    value = load_decimal_json(payload, source="FEC")
    if not isinstance(value, dict) or value.get("error") or value.get("errors"):
        raise ValueError("FEC API did not return a successful JSON object")
    return value


def parse_sitemap(payload: bytes) -> tuple[str, list[dict]]:
    root = ET.fromstring(payload)
    kind = root.tag.rsplit("}", 1)[-1]
    if root.tag not in {name for name in ("urlset", "sitemapindex")} | {
        f"{{http://www.sitemaps.org/schemas/sitemap/0.9}}{name}" for name in ("urlset", "sitemapindex")
    }:
        raise ValueError("FEC index is not a sitemap XML document")
    expected = "url" if kind == "urlset" else "sitemap"
    rows = []
    for child in root:
        if child.tag.rsplit("}", 1)[-1] != expected:
            raise ValueError("FEC sitemap contains an unexpected entry")
        locations = [x.text for x in child if x.tag.rsplit("}", 1)[-1] == "loc"]
        if len(locations) != 1 or not locations[0]:
            raise ValueError("FEC sitemap entry needs one loc")
        rows.append(
            {
                "url": locations[0],
                "fields": [{"name": x.tag, "text": x.text, "attributes": dict(x.attrib)} for x in child],
            }
        )
    return kind, rows


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self.title: list[str] = []
        self._title = False
        self._anchor: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self._title = not self.title  # Later SVG icon titles are not the document title.
        if tag == "a" and values.get("href"):
            self._anchor = {"href": values["href"], "label": "", "type": values.get("type")}
            self.links.append(self._anchor)
        elif tag == "link" and values.get("href") and "alternate" in (values.get("rel") or "").split():
            self.links.append({"href": values["href"], "label": values.get("title", ""), "type": values.get("type")})

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._title = False
        if tag == "a":
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self._title:
            self.title.append(data)
        if self._anchor is not None:
            self._anchor["label"] += data


def parse_page_links(payload: bytes, *, url: str) -> dict:
    """Fallback link discovery for FEC collections without a structured index.

    Keep each anchor association, including repeated URLs. The page capture
    retains content, cards and dates not expressible as link labels. HTML never
    becomes a claimed JSON/XML feed, and linked originals remain unrequested.
    """
    text = payload.decode("utf-8-sig")
    parser = _Links()
    parser.feed(text)
    title = "".join(parser.title).strip()
    if not re.search(r"\bFEC\b|Federal Election Commission", title, re.IGNORECASE):
        raise ValueError("FEC collection page is missing its publisher title")
    if re.search(r"request rejected|access denied|verify you are human|just a moment", title, re.IGNORECASE):
        raise ValueError("FEC collection returned a challenge page")
    links = []
    for link in parser.links:
        target = resolve_link(link["href"], base=url)
        if urlsplit(target).scheme not in {"http", "https"}:
            continue
        links.append({"url": target, "label": link["label"].strip(), "media_type": media_type(link["type"], target)})
    return {"title": title, "links": links}


def resolve_link(value: str, *, base: str) -> str:
    """Resolve source-relative links and encode literal path spaces, preserving metadata."""
    p = urlsplit(urljoin(base, value))
    return urlunsplit((p.scheme, p.netloc, quote(p.path, safe="/%:@!$&'()*+,;="), p.query, p.fragment))


def api_page(value: dict, *, url: str, mode: str | list[str]) -> tuple[list[tuple[str, object]], dict | None, dict]:
    """Apply the response shape declared by the retained official Swagger."""
    query = dict(parse_qsl(urlsplit(url).query))
    if isinstance(mode, list):
        if not all(field in value for field in mode):
            raise ValueError("FEC reference response omitted its declared fields")
        return [("", value)], None, {}
    if mode == "docs":
        if not isinstance(value.get("docs"), list):
            raise ValueError("FEC legal detail omitted docs")
        return [(f"/docs/{i}", x) for i, x in enumerate(value["docs"])], None, {}
    if mode in {"page", "keyset", "list"}:
        rows = value.get("results")
        if not isinstance(rows, list):
            raise ValueError("FEC response omitted its results list")
        if mode == "list":
            if "pagination" in value:
                raise ValueError("FEC finite reference unexpectedly declared pagination")
            return [(f"/results/{i}", x) for i, x in enumerate(rows)], None, {}
        pagination = value.get("pagination")
        if not isinstance(pagination, dict):
            raise ValueError("FEC response omitted pagination")
        changes = None
        if mode == "keyset":
            if rows:
                indexes = pagination.get("last_indexes")
                if not isinstance(indexes, dict) or not indexes or not any(v is not None for v in indexes.values()):
                    raise ValueError("nonempty FEC keyset page omitted continuation indexes")
                if any(
                    not (k.startswith("last_") or k == "sort_null_only") or isinstance(v, (dict, list))
                    for k, v in indexes.items()
                ):
                    raise ValueError("FEC keyset contains unexpected continuation controls")
                changes = indexes
        else:
            page, pages = pagination.get("page"), pagination.get("pages")
            if type(page) is not int or type(pages) is not int or page < 1 or pages < 0:
                raise ValueError("FEC page controls must be nonnegative integers")
            if page != int(query.get("page", 1)):
                raise ValueError("FEC returned a different page than requested")
            if not rows and pagination.get("is_count_exact") is True and page < pages:
                raise ValueError("FEC returned an empty page before its declared end")
            if rows and (pagination.get("is_count_exact") is not True or page < pages):
                changes = {"page": page + 1}
        return [(f"/results/{i}", x) for i, x in enumerate(rows)], changes, {"pagination": pagination}
    if mode == "legal":
        groups = [
            name
            for name in ("murs", "advisory_opinions", "admin_fines", "adrs", "statutes", "rulemakings")
            if name in value
        ]
        if not groups:
            raise ValueError("FEC legal search omitted its result groups")
        size = int(query.get("hits_returned", 30 if "rulemakings" in groups else 20))
        offset = int(query.get("from_hit", 0))
        if not 1 <= size <= 200 or offset < 0:
            raise ValueError("FEC legal offsets or page size are invalid")
        rows, more = [], False
        for group in groups:
            items, total = value[group], value.get("total_" + group)
            if not isinstance(items, list) or type(total) is not int or total < 0 or len(items) > size:
                raise ValueError("FEC legal search count/record shape is unsupported")
            if len(items) < min(size, max(0, total - offset)):
                raise ValueError("FEC legal search is short before its declared end")
            rows.extend((f"/{group}/{i}", x) for i, x in enumerate(items))
            more = more or offset + len(items) < total
        controls = {k: v for k, v in value.items() if k not in groups}
        return rows, {"from_hit": offset + size} if more else None, {"pagination": controls}
    raise ValueError("FEC API response mode is unsupported")
