"""Granule locators and body identity rules, offline (B2: granule bodies for the Record).

The three CREC-2026-09-18-pt1-PgS4837-4 fixtures are exact publisher
responses (fixture README, "Granule bodies for the daily Record"); the
synthetic cases cover the refusal shapes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.sources.govinfo.bodies import (
    GovInfoBodySourceError,
    granule_body_locator,
    granule_mods_locator,
    granule_summary_locator,
    parse_granule_identity,
    validate_granule_body,
    validate_granule_mods,
    validate_granule_summary,
)

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bodies"
PACKAGE = "CREC-2026-09-18"
GRANULE = "CREC-2026-09-18-pt1-PgS4837-4"
SUMMARY = (FIXTURES / f"granule-summary-{GRANULE}.json").read_bytes()
MODS = (FIXTURES / f"granule-mods-{GRANULE}.xml").read_bytes()
BODY = (FIXTURES / f"granule-body-{GRANULE}.htm").read_bytes()
SUMMARY_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/granules/{GRANULE}/summary"
MODS_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/granules/{GRANULE}/mods"
BODY_URL = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/html/{GRANULE}.htm"
ERROR_PAGE = b'<html><a href="https://www.govinfo.gov/error">Page Not Found</a></html>'


def granule_mods_xml(*, granule_access_id: str = GRANULE, host_access_id: str = PACKAGE, urls: str = "") -> bytes:
    """A minimal but shape-correct granule MODS: own accessId, host relatedItem, offered renditions."""
    pdf_url = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{GRANULE}.pdf"
    renditions = urls or (
        f'<url displayLabel="PDF rendition" access="raw object">{pdf_url}</url>'
        f'<url displayLabel="HTML rendition" access="raw object">{BODY_URL}</url>'
    )
    return (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{granule_access_id}</accessId></extension>"
        f'<relatedItem type="host"><extension><accessId>{host_access_id}</accessId></extension></relatedItem>'
        f"<location>{renditions}</location>"
        "</mods>"
    ).encode()


def test_parse_granule_identity_keeps_both_ids() -> None:
    """Granule identity keeps both the package id and the granule id."""
    identity = parse_granule_identity(PACKAGE, GRANULE)
    assert identity.package.package_id == PACKAGE
    assert identity.package.collection == "CREC"
    assert identity.granule_id == GRANULE


@pytest.mark.parametrize(
    "granule_id",
    ["", "a" * 129, "has a space", "has/a/slash"],
)
def test_an_unsupported_granule_id_refuses_by_name(granule_id: str) -> None:
    """An unsupported granule id is refused by name."""
    with pytest.raises(GovInfoBodySourceError, match="granule id"):
        parse_granule_identity(PACKAGE, granule_id)


def test_locators_address_the_package_folder_and_the_granule_file_stem() -> None:
    """Locators address the package folder and the granule file stem, including the PDF suffix."""
    assert granule_summary_locator(PACKAGE, GRANULE) == SUMMARY_URL
    assert granule_mods_locator(PACKAGE, GRANULE) == MODS_URL
    assert granule_body_locator(PACKAGE, GRANULE, "htm") == BODY_URL
    assert granule_body_locator(PACKAGE, GRANULE, "pdf") == (
        f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{GRANULE}.pdf"
    )


def test_real_summary_states_the_granule_and_its_host_package() -> None:
    """The real granule summary states its granule, host package, date, title and download links."""
    summary = validate_granule_summary(
        SUMMARY, package=PACKAGE, granule_id=GRANULE, final_url=SUMMARY_URL, max_bytes=200_000
    )
    assert summary.identity.package.package_id == PACKAGE
    assert summary.identity.granule_id == GRANULE
    assert summary.collection_code == "CREC"
    assert summary.date_issued == "2026-09-18"
    assert summary.title == "APPOINTMENT OF ACTING PRESIDENT PRO TEMPORE"
    # The granule summary names its own MODS/PDF/txt links, keyed under the
    # granule route, plus the package-level premis and zip; nothing is
    # derived from these, the same evidence-only rule the package summary
    # follows.
    assert [name for name, _url in summary.download_links] == [
        "modsLink",
        "pdfLink",
        "premisLink",
        "txtLink",
        "zipLink",
    ]


@pytest.mark.parametrize(
    ("body", "final_url", "message"),
    [
        (
            json.dumps({"packageId": "CREC-2026-09-17", "granuleId": GRANULE, "collectionCode": "CREC"}).encode(),
            SUMMARY_URL,
            "packageId",
        ),
        (
            json.dumps(
                {"packageId": PACKAGE, "granuleId": "CREC-2026-09-18-pt1-PgS4837-5", "collectionCode": "CREC"}
            ).encode(),
            SUMMARY_URL,
            "granuleId",
        ),
        (
            json.dumps({"packageId": PACKAGE, "granuleId": GRANULE, "collectionCode": "CRPT"}).encode(),
            SUMMARY_URL,
            "collectionCode",
        ),
        (json.dumps({"packageId": PACKAGE, "granuleId": GRANULE}).encode(), SUMMARY_URL, "collectionCode"),
        # Measured 2026-09-19: a granule that does not belong to the package
        # answers 400 with neither field at all, not a summary shape.
        (b'{"message":"invalid granuleId"}', SUMMARY_URL, "packageId"),
        (b"", SUMMARY_URL, "empty"),
        (SUMMARY, MODS_URL, "final URL"),
    ],
)
def test_summary_refusals(body: bytes, final_url: str, message: str) -> None:
    """Summary refusals name the failed check."""
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_granule_summary(body, package=PACKAGE, granule_id=GRANULE, final_url=final_url, max_bytes=200_000)


def test_real_mods_states_its_own_accessid_its_hosts_and_the_offered_renditions() -> None:
    """The real granule MODS states its own access id, host package and offered renditions in document order."""
    mods = validate_granule_mods(MODS, package=PACKAGE, granule_id=GRANULE, final_url=MODS_URL, max_bytes=200_000)
    assert mods.access_ids == (GRANULE,)
    assert mods.collection_code == "CREC"
    assert mods.host_package_ids == (PACKAGE,)
    # Document order in the real MODS is PDF then HTML; GRANULE_BODY_PREFERENCE
    # still picks htm first regardless (test_govinfo_granule_body_acquisition.py).
    assert mods.offered_formats == ("pdf", "htm")
    assert mods.moved_renditions == ()
    assert mods.other_renditions == ()


def test_this_granules_rendition_at_another_address_reads_as_disagreement() -> None:
    """A rendition of this granule at another address reads as a moved rendition, not an offer."""
    # Mirrors test_govinfo_package_bodies.py's package-level version: a
    # supported file type at this granule's own package address, but a
    # folder this module does not derive for a granule rendition.
    moved = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/alt/{GRANULE}.pdf"
    body = granule_mods_xml(
        urls=(
            f'<url displayLabel="HTML rendition" access="raw object">{BODY_URL}</url>'
            f'<url displayLabel="PDF rendition" access="raw object">{moved}</url>'
        )
    )
    mods = validate_granule_mods(body, package=PACKAGE, granule_id=GRANULE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.offered_formats == ("htm",)
    assert mods.moved_renditions == (("pdf", moved),)
    assert mods.other_renditions == ()


def test_a_granule_mods_states_no_relatedItem_host_refuses() -> None:
    """A granule MODS with no relatedItem host refuses."""
    body = (
        f'<mods xmlns="http://www.loc.gov/mods/v3"><extension><accessId>{GRANULE}</accessId></extension></mods>'
    ).encode()
    with pytest.raises(GovInfoBodySourceError, match="no host package"):
        validate_granule_mods(body, package=PACKAGE, granule_id=GRANULE, final_url=MODS_URL, max_bytes=10_000)


def test_a_granule_mods_whose_host_names_a_different_package_refuses() -> None:
    """A granule MODS whose host names a different package refuses."""
    body = granule_mods_xml(host_access_id="CREC-2026-09-17")
    with pytest.raises(GovInfoBodySourceError, match="host package differs"):
        validate_granule_mods(body, package=PACKAGE, granule_id=GRANULE, final_url=MODS_URL, max_bytes=10_000)


@pytest.mark.parametrize(
    ("body", "final_url", "message"),
    [
        (granule_mods_xml(granule_access_id=f"{GRANULE}-x"), MODS_URL, "accessId differs"),
        (b'<mods xmlns="http://www.loc.gov/mods/v3"><location/></mods>', MODS_URL, "states no accessId"),
        (b"<notmods/>", MODS_URL, "unreadable"),
        (MODS, SUMMARY_URL, "final URL"),
        (b"", MODS_URL, "empty"),
    ],
)
def test_mods_refusals(body: bytes, final_url: str, message: str) -> None:
    """MODS refusals name the failed check."""
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_granule_mods(body, package=PACKAGE, granule_id=GRANULE, final_url=final_url, max_bytes=200_000)


def test_real_body_is_proved_by_its_locator_and_media_type() -> None:
    """The real body is proved by its locator and media type, carrying no package id of its own."""
    identity = validate_granule_body(
        BODY,
        package=PACKAGE,
        granule_id=GRANULE,
        format="htm",
        content_type="text/html",
        final_url=BODY_URL,
        max_bytes=200_000,
    )
    assert identity.format == "htm"
    assert identity.media_type == "text/html"
    assert identity.byte_size == len(BODY) == 1_333
    # Like a package body, a granule body carries no machine-readable id of
    # its own package -- identity rests on the locator, the MODS statement
    # and the error-page exclusion.
    assert PACKAGE.encode() not in BODY


@pytest.mark.parametrize(
    ("body", "format", "content_type", "final_url", "message"),
    [
        (b"", "htm", "text/html", BODY_URL, "empty"),
        (ERROR_PAGE, "htm", "text/html", BODY_URL, "error page"),
        (BODY, "htm", "application/pdf", BODY_URL, "Content-Type"),
        (BODY, "htm", "text/html", MODS_URL, "final URL"),
        (
            b"not a pdf",
            "pdf",
            "application/pdf",
            f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{GRANULE}.pdf",
            "%PDF-",
        ),
    ],
)
def test_body_refusals(body: bytes, format: str, content_type: str | None, final_url: str, message: str) -> None:
    """Body refusals name the failed check."""
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_granule_body(
            body,
            package=PACKAGE,
            granule_id=GRANULE,
            format=format,
            content_type=content_type,
            final_url=final_url,
            max_bytes=200_000,
        )
