"""Qualified source heading/date reading does not infer days or accept wrong identities."""

from pathlib import Path
from zipfile import ZipFile

import pytest

from spicy_docs.sources.gao.native import iter_gao_product_pages
from spicy_docs.sources.gao.product_metadata import product_page_metadata
from spicy_docs.sources.zyte import ZyteHttpResponse

PRODUCT = "gao-17-317"
FIXTURE = Path(__file__).parent / "fixtures/gao_metadata/product-page.zip"


def test_retained_product_page_heading_and_published_date():
    metadata = product_page_metadata(FIXTURE.read_bytes(), PRODUCT)
    assert (
        metadata.title
        == "High-Risk Series: Progress on Many High-Risk Areas, While Substantial Efforts Needed on Others"
    )
    assert metadata.published_date == "2017-02-15"
    with pytest.raises(ValueError, match="different product"):
        product_page_metadata(FIXTURE.read_bytes(), "gao-17-999")


def changed_page(old, new):
    with ZipFile(FIXTURE) as archive:
        body = archive.read("product.html").replace(old, new)
    url = "https://www.gao.gov/products/" + PRODUCT
    return next(
        iter_gao_product_pages(
            lambda _: ZyteHttpResponse(url, url, 200, "text/html", body), query_scope={"productIds": [PRODUCT]}
        )
    ).response_bytes


def test_month_only_date_does_not_infer_day_or_use_public_release():
    raw = changed_page(b"Published: Feb 15, 2017.", b"Published: February 2017.")
    assert product_page_metadata(raw, PRODUCT).published_date is None


def test_conflicting_dates_refuse():
    raw = changed_page(b"Published: Feb 15, 2017.", b"Published: Feb 15, 2017. Published: Feb 16, 2017.")
    with pytest.raises(ValueError, match="conflicting"):
        product_page_metadata(raw, PRODUCT)


def test_missing_heading_and_invalid_evidence_refuse():
    raw = changed_page(b'<h1 class="split-headings">', b'<h2 class="split-headings">')
    with pytest.raises(ValueError, match="heading"):
        product_page_metadata(raw, PRODUCT)
    with pytest.raises(ValueError):
        product_page_metadata(b"<h1>Unqualified HTML</h1>", PRODUCT)
