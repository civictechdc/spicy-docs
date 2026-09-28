"""Qualified source heading/date reading does not infer days or accept wrong identities."""

from pathlib import Path
from zipfile import ZipFile

import pytest

from spicy_docs.sources.gao.files import gao_report_pdf_locator
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
    # The page's own Full Report link path, on the file host that serves it keyless.
    assert metadata.pdf_url == "https://files.gao.gov/assets/gao-17-317.pdf"
    assert metadata.pdf_url == gao_report_pdf_locator(PRODUCT)
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


@pytest.mark.parametrize(
    "href",
    [
        "/assets/690/683460.pdf",
        "https://www.gao.gov/assets/690/683460.pdf",
        "https://files.gao.gov/assets/690/683460.pdf",
    ],
)
def test_pdf_url_is_the_path_the_page_labels_full_report(href):
    """Synthetic: a Full Report link to another asset path keeps the page's path, not one built from the id."""
    raw = changed_page(b'<a href="/assets/gao-17-317.pdf">', f'<a href="{href}">'.encode())
    assert product_page_metadata(raw, PRODUCT).pdf_url == "https://files.gao.gov/assets/690/683460.pdf"


@pytest.mark.parametrize(
    "href",
    ["https://example.com/assets/gao-17-317.pdf", "/products/gao-17-317", "/assets/gao-17-317.pdf?download=1"],
)
def test_a_full_report_link_off_the_gao_asset_paths_refuses(href):
    raw = changed_page(b'<a href="/assets/gao-17-317.pdf">', f'<a href="{href}">'.encode())
    with pytest.raises(ValueError, match="not an asset path"):
        product_page_metadata(raw, PRODUCT)


@pytest.mark.parametrize(
    "old, new",
    [
        (b">Full Report</div>", b">Report</div>"),  # no link labelled Full Report
        (b">Highlights Page</div>", b">Full Report</div>"),  # two different Full Report links
    ],
    ids=["none", "two"],
)
def test_a_page_without_exactly_one_full_report_link_refuses(old, new):
    raw = changed_page(old, new)
    with pytest.raises(ValueError, match="exactly one Full Report"):
        product_page_metadata(raw, PRODUCT)
