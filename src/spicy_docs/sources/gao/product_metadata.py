"""Metadata from an already-qualified GAO product page, without widening the raw profile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin
from zipfile import ZipFile

#: The label the product page gives its report PDF inside the full-reports group. All 47 product pages retained on
#: 2026-08-22 (``_salvage-2026-08-28/spicysearch-output/gao-native-import-2026-08-22/pages/``) and the retained
#: gao-17-317 page label exactly one link so, each ``/assets/{product-id}.pdf``; the group's other labels are
#: ``Highlights Page``, ``Accessible PDF`` and ``View Full Report Online``.
FULL_REPORT_LABEL = "Full Report"


@dataclass(frozen=True)
class GaoTargetMetadata:
    """``pdf_url`` is the page's own Full Report link, resolved against ``product_url``.

    That link is on ``www.gao.gov``, which refuses plain clients; ``sources.gao.files`` fetches the same asset path
    keyless from ``files.gao.gov`` (``docs/sources/gao-files.md``).
    """

    product_id: str
    title: str
    product_url: str
    pdf_url: str
    published_date: str | None


class _PageMetadata(HTMLParser):
    """Read only the product heading, its labeled publication block and its full-reports links."""

    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_dates = False
        self.in_reports = False
        self.in_label = False
        self.titles: list[list[str]] = []
        self.dates: list[str] = []
        #: ``[href, label parts]`` for each link in the full-reports group, in page order.
        self.report_links: list[tuple[str, list[str]]] = []
        self._link: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "h1":
            self.in_title = True
            self.titles.append([])
        if tag == "section" and attributes.get("id") == "block--post-title-info":
            self.in_dates = True
        if tag == "section" and "full-reports-group" in classes:
            self.in_reports = True
        if self.in_reports and tag == "a" and attributes.get("href"):
            self._link = (attributes["href"], [])
            self.report_links.append(self._link)
        if self._link is not None and tag == "div" and "field--name-field-link-label" in classes:
            self.in_label = True

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_title = False
        if tag == "section":
            self.in_dates = False
            self.in_reports = False
        if tag == "div":
            self.in_label = False
        if tag == "a":
            self._link = None

    def handle_data(self, data):
        if self.in_title:
            self.titles[-1].append(data)
        if self.in_dates:
            self.dates.append(data)
        if self.in_label and self._link is not None:
            self._link[1].append(data)


def product_page_metadata(raw: bytes, product_id: str) -> GaoTargetMetadata:
    """Replay the provider-qualified product page, retaining its exact title and explicit date only."""
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
    reports = {href for href, label in fields.report_links if " ".join("".join(label).split()) == FULL_REPORT_LABEL}
    if len(reports) != 1:
        raise ValueError(f"GAO product page must link exactly one {FULL_REPORT_LABEL} PDF, not {len(reports)}")
    product_url = parsed["results"][0]["canonicalUrl"]
    return GaoTargetMetadata(product_id, title, product_url, urljoin(product_url, reports.pop()), day)
