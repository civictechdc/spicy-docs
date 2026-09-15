"""Read retained Oversight.gov report fields; originals and body text stay separate."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

_DOCUMENT_SUFFIXES = (".pdf", ".zip", ".xlsx", ".xls", ".csv", ".xml", ".txt", ".docx")
_FILE_FIELDS = {"field-report-file", "field-report-link"}


class OversightReportError(ValueError):
    """The input does not contain the supported public report page structure."""


class _DepthBound(HTMLParser):
    """Bound markup nesting before the selector library builds/traverses its tree."""

    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.stack: list[str] = []

    def handle_starttag(self, tag, _attrs):
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(tag)
            if len(self.stack) > self.limit:
                raise OversightReportError("Oversight HTML exceeds max_depth")

    def handle_endtag(self, tag):
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            if any(t in {"main", "article"} for t in self.stack[index + 1 :]):
                raise OversightReportError("Oversight report article or main content is unclosed")
            del self.stack[index:]

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def _position(tag) -> dict:
    return {"line": tag.sourceline, "column": tag.sourcepos}


def _link(tag, url: str) -> dict:
    return {
        "label": tag.get_text(" ", strip=True),
        "href": tag["href"],
        "url": urljoin(url, tag["href"]),
        "source_position": _position(tag),
    }


def _content(node, url: str) -> dict:
    return {
        "text": node.get_text(" ", strip=True),
        "source_position": _position(node),
        "links": [_link(a, url) for a in node.select("a[href]")],
        "times": [dict(t.attrs) for t in node.select("time")],
        "numeric_content": [v["content"] for v in node.select("[content]")],
    }


def _outermost(nodes):
    selected = {id(node) for node in nodes}
    return [node for node in nodes if not any(id(parent) in selected for parent in node.parents)]


def _disjoint(nodes, label: str) -> None:
    if len(_outermost(nodes)) != len(nodes):
        raise OversightReportError(f"Oversight {label} must not nest")


def _recommendations(main, url: str) -> list[dict]:
    views = main.select(".view-report-recommendations")
    _disjoint(views, "recommendation sections")
    result = []
    for view in views:
        tables = view.select("table")
        _disjoint(tables, "recommendation tables")
        mapped = []
        for table in tables:
            rows = []
            source_rows = table.select("tr")
            _disjoint(source_rows, "recommendation rows")
            for row in source_rows:
                cells = [
                    {"tag": cell.name, "attributes": dict(cell.attrs), **_content(cell, url)}
                    for cell in row.find_all(["th", "td"], recursive=False)
                ]
                rows.append({"attributes": dict(row.attrs), "source_position": _position(row), "cells": cells})
            mapped.append({"attributes": dict(table.attrs), "source_position": _position(table), "rows": rows})
        result.append({"kind": "recommendations", **_content(view, url), "tables": mapped})
    return result


def parse_oversight_report(
    body: bytes, *, url: str, max_bytes: int = 8 * 1024**2, max_fields: int = 1000, max_depth: int = 128
) -> dict:
    """Map one retained UTF-8 report page using the optional ``html`` extra.

    Fields preserve source names, repeated values, dates, numeric attributes and
    links. The declared ``body`` field and recommendation sections move into
    ``bodies``; metadata retains their indices. Recommendation table rows and
    spans remain uninterpreted. Unknown fields remain visible. Text uses BeautifulSoup's
    whitespace-normalized display extraction; exact markup stays in caller-retained
    input bytes. Source positions are one-based lines and zero-based character
    columns in decoded HTML, not byte offsets. No linked originals are fetched.
    """
    if any(type(v) is not int or v <= 0 for v in (max_bytes, max_fields, max_depth)):
        raise OversightReportError("max_bytes, max_fields and max_depth must be positive integers")
    if not isinstance(body, bytes) or not body or len(body) > max_bytes:
        raise OversightReportError("Oversight report must be nonempty bytes within max_bytes")
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or p.hostname != "www.oversight.gov"
        or not p.path.startswith("/reports/")
        or p.username is not None
        or p.password is not None
        or p.port not in (None, 443)
        or p.query
        or p.fragment
    ):
        raise OversightReportError("Oversight report needs an explicit public report URL")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OversightReportError("Oversight report is not UTF-8") from error
    try:
        from bs4 import BeautifulSoup
    except ImportError as error:
        raise ImportError("Oversight parsing requires spicy-docs[html]") from error

    def duplicate_attribute(_attributes, _key, _value):
        raise OversightReportError("Oversight HTML repeats an attribute")

    guard = _DepthBound(max_depth)
    guard.feed(text)
    guard.close()
    if any(tag in guard.stack for tag in ("main", "article")):
        raise OversightReportError("Oversight report article or main content is unclosed")
    soup = BeautifulSoup(text, "html.parser", on_duplicate_attribute=duplicate_attribute)
    mains = soup.select("main")
    articles = soup.select("main article.node--type-report")
    titles = soup.select("h1")
    if len(mains) != 1 or len(articles) != 1 or len(titles) != 1 or not titles[0].get_text(strip=True):
        raise OversightReportError("Expected one public report article and title")
    report_title = titles[0]
    nodes = articles[0].select(".field-values-list__content > .field")
    if not nodes or len(nodes) > max_fields:
        raise OversightReportError("Oversight report has no fields or exceeds max_fields")
    _disjoint(nodes, "report fields")
    fields, bodies, assets = [], [], []
    for index, node in enumerate(nodes):
        names = [c.removeprefix("field--name-") for c in node.get("class", []) if c.startswith("field--name-")]
        if len(names) != 1 or not names[0]:
            raise OversightReportError("Oversight field lacks an unambiguous native name")
        titles = node.find_all("div", class_="title", recursive=False)
        if len(titles) > 1:
            raise OversightReportError("Oversight field repeats its label")
        label = titles[0].get_text(" ", strip=True) if titles else None
        content = _content(node, url)
        value = content.pop("text")
        if label and value.startswith(label):
            value = value[len(label) :].strip()
        field = {"native_field": names[0], "label": label, **content}
        items = [
            {"text": item.get_text(" ", strip=True), "attributes": dict(item.attrs), "source_position": _position(item)}
            for item in _outermost(node.select(".field__item"))
        ]
        if names[0] == "body":
            field["body_index"] = len(bodies)
            bodies.append(
                {
                    "kind": "report_description",
                    "field_index": index,
                    "text": value,
                    "items": items,
                    "source_position": _position(node),
                }
            )
        else:
            field["value"] = value
            field["items"] = items
        fields.append(field)
        for link in field["links"]:
            target = urlsplit(link["url"])
            native_file = names[0] in _FILE_FIELDS
            if native_file or target.path.lower().endswith(_DOCUMENT_SUFFIXES):
                assets.append(
                    {
                        **link,
                        "field_index": index,
                        "native_field": names[0],
                        "role": "declared_report_link" if native_file else "document_candidate",
                        "decoded_wrapper_targets": parse_qs(target.query).get("url", [])
                        if (target.hostname or "").endswith(".safelinks.protection.outlook.com")
                        else [],
                    }
                )
    recommendations = _recommendations(mains[0], url)
    recommendation_indices = list(range(len(bodies), len(bodies) + len(recommendations)))
    bodies.extend(recommendations)
    return {
        "source": {"url": url, "sha256": "sha256:" + hashlib.sha256(body).hexdigest(), "bytes": len(body)},
        "metadata": {
            "title": report_title.get_text(" ", strip=True),
            "title_position": _position(report_title),
            "recommendation_body_indices": recommendation_indices,
            "fields": fields,
            "links": [_link(a, url) for a in mains[0].select("a[href]")],
        },
        "bodies": bodies,
        "assets": assets,
    }
