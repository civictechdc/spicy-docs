"""Metadata from an already-qualified GAO product page, without widening the raw profile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO
from zipfile import ZipFile


@dataclass(frozen=True)
class GaoTargetMetadata:
    product_id: str
    title: str
    product_url: str
    pdf_url: str
    published_date: str | None


class _PageMetadata(HTMLParser):
    """Read only the product heading and its labeled publication block."""

    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_dates = False
        self.titles: list[list[str]] = []
        self.dates: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.in_title = True
            self.titles.append([])
        if tag == "section" and dict(attrs).get("id") == "block--post-title-info":
            self.in_dates = True

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_title = False
        if tag == "section":
            self.in_dates = False

    def handle_data(self, data):
        if self.in_title:
            self.titles[-1].append(data)
        if self.in_dates:
            self.dates.append(data)


def product_page_metadata(raw: bytes, product_id: str) -> GaoTargetMetadata:
    """Replay the provider-qualified product page, retaining its exact title and explicit date only."""
    from spicy_docs.sources.gao.files import gao_report_pdf_locator
    from spicy_docs.sources.gao.native import parse_gao_product_page_response

    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("GAO retained page ZIP exceeds its byte bound")
    parsed = parse_gao_product_page_response(raw)
    if parsed["_productId"] != product_id:
        raise ValueError("Retained GAO page names a different product")
    with ZipFile(BytesIO(raw)) as archive:
        body = archive.read("product.html")
    fields = _PageMetadata()
    fields.feed(body.decode("utf-8"))
    fields.close()
    if len(fields.titles) != 1 or not (title := " ".join("".join(fields.titles[0]).split())):
        raise ValueError("GAO product page must state exactly one nonempty heading")
    # The explicit Published label avoids dates belonging to linked videos or
    # Publicly Released. Month-only text never supplies a day.
    dates = re.findall(r"(?<!\w)Published: ([A-Z][a-z]{2} [0-9]{1,2}, [0-9]{4})\.", "".join(fields.dates))
    if len(set(dates)) > 1:
        raise ValueError("GAO product page states conflicting publication dates")
    day = datetime.strptime(dates[0], "%b %d, %Y").replace(tzinfo=UTC).date().isoformat() if dates else None
    return GaoTargetMetadata(
        product_id, title, parsed["results"][0]["canonicalUrl"], gao_report_pdf_locator(product_id), day
    )
