"""Package-id grammar, locators and body identity rules, offline.

The three CRPT-119hrpt1 fixtures are exact publisher responses; the synthetic
cases cover shapes the publisher answered on other packages (a BILLS download
block, a USLM rendition) and the refusals themselves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.sources.federal_register.body_sources import (
    FederalRegisterBodySourceError,
    validate_govinfo_granule,
)
from spicy_docs.sources.govinfo.bodies import (
    PACKAGE_BODY_FORMATS,
    GovInfoBodySourceError,
    package_body_locator,
    package_mods_locator,
    package_summary_locator,
    parse_package_id,
    validate_package_body,
    validate_package_mods,
    validate_package_summary,
)

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bodies"
PACKAGE = "CRPT-119hrpt1"
SUMMARY = (FIXTURES / f"summary-{PACKAGE}.json").read_bytes()
MODS = (FIXTURES / f"mods-{PACKAGE}.xml").read_bytes()
BODY = (FIXTURES / f"body-{PACKAGE}.htm").read_bytes()
SUMMARY_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/summary"
MODS_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/mods"
BODY_URL = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/html/{PACKAGE}.htm"
ERROR_PAGE = b'<html><a href="https://www.govinfo.gov/error">Page Not Found</a></html>'


def mods_xml(*, access_id: str = PACKAGE, collection: str = "CRPT", urls: str = "") -> bytes:
    renditions = urls or (
        f'<url displayLabel="HTML rendition" access="raw object">{BODY_URL}</url>'
        f'<url displayLabel="PDF rendition" access="raw object">'
        f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{PACKAGE}.pdf</url>"
    )
    return (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><collectionCode>{collection}</collectionCode>"
        f"<accessId>{access_id}</accessId></extension>"
        f"<location>{renditions}</location></mods>"
    ).encode()


@pytest.mark.parametrize(
    ("package_id", "fields"),
    [
        ("CRPT-119hrpt1", {"congress": 119, "document_type": "hrpt", "number": "1"}),
        ("CRPT-118erpt5", {"congress": 118, "document_type": "erpt", "number": "5"}),
        ("CHRG-119hhrg64242", {"congress": 119, "document_type": "hhrg", "number": "64242"}),
        ("CHRG-116jhrg43189", {"congress": 116, "document_type": "jhrg", "number": "43189"}),
        ("CDOC-119tdoc2", {"congress": 119, "document_type": "tdoc", "number": "2"}),
        ("CDOC-113hdoc132", {"congress": 113, "document_type": "hdoc", "number": "132"}),
        ("CREC-2026-01-02", {"issue_date": "2026-01-02", "issue_suffix": None}),
        ("CREC-2019-01-03-v164", {"issue_date": "2019-01-03", "issue_suffix": "v164"}),
        ("CREC-2009-12-18-i194", {"issue_date": "2009-12-18", "issue_suffix": "i194"}),
        ("CDIR-2026-02-20", {"issue_date": "2026-02-20"}),
        ("BILLS-119hr1enr", {"congress": 119, "document_type": "hr", "number": "1", "version": "enr"}),
        ("BILLS-119hjres25enr", {"congress": 119, "document_type": "hjres", "number": "25", "version": "enr"}),
    ],
)
def test_each_collection_grammar_keeps_the_publishers_own_parts(package_id: str, fields: dict[str, object]) -> None:
    identity = parse_package_id(package_id)
    assert identity.package_id == package_id
    assert identity.collection == package_id.split("-", 1)[0]
    for name, value in fields.items():
        assert getattr(identity, name) == value


@pytest.mark.parametrize(
    ("package_id", "message"),
    [
        # Real ids a collection-scoped published walk returns from neighboring
        # collections: ERP-2009 states collectionCode ERP and GPO-J6-REPORT
        # states GPO, so neither is a CDOC or CRPT address.
        ("ERP-2009", "collection is unsupported"),
        ("GPO-J6-REPORT", "collection is unsupported"),
        ("GPO-CRPT-116hrpt562", "collection is unsupported"),
        ("CHRG-119xhrg64242", "grammar"),
        ("CRPT-119hrpt0", "grammar"),
        ("BILLS-119hr1", "grammar"),
        ("CREC-2026-01-02-p3", "grammar"),
        ("CREC-2026-02-30", "calendar date"),
        ("CDIR-2026-2-20", "grammar"),
        ("FR-2026-01-02", "collection is unsupported"),
        ("CRPT119hrpt1", "collection is unsupported"),
        ("", "nonempty string"),
        ("CRPT-" + "1" * 200, "128 characters"),
    ],
)
def test_unsupported_package_ids_refuse_by_name(package_id: str, message: str) -> None:
    with pytest.raises(GovInfoBodySourceError, match=message):
        parse_package_id(package_id)


def test_package_id_must_be_a_string() -> None:
    with pytest.raises(GovInfoBodySourceError, match="nonempty string"):
        parse_package_id(None)


@pytest.mark.parametrize(
    ("format", "expected"),
    [
        ("htm", f"https://www.govinfo.gov/content/pkg/{PACKAGE}/html/{PACKAGE}.htm"),
        ("xml", f"https://www.govinfo.gov/content/pkg/{PACKAGE}/xml/{PACKAGE}.xml"),
        # The publisher's text folder is "text", not the format name.
        ("txt", f"https://www.govinfo.gov/content/pkg/{PACKAGE}/text/{PACKAGE}.txt"),
        ("pdf", f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{PACKAGE}.pdf"),
    ],
)
def test_body_locators_follow_the_publishers_folders(format: str, expected: str) -> None:
    assert package_body_locator(PACKAGE, format) == expected
    assert package_body_locator(parse_package_id(PACKAGE), format) == expected


def test_keyed_locators_carry_no_credential() -> None:
    assert package_summary_locator(PACKAGE) == SUMMARY_URL
    assert package_mods_locator(PACKAGE) == MODS_URL
    assert "api_key" not in SUMMARY_URL + MODS_URL


def test_unsupported_format_refuses() -> None:
    with pytest.raises(GovInfoBodySourceError, match="body format must be"):
        package_body_locator(PACKAGE, "uslm")


def test_real_summary_states_the_package_and_no_body_rendition() -> None:
    summary = validate_package_summary(SUMMARY, package=PACKAGE, final_url=SUMMARY_URL, max_bytes=200_000)
    assert summary.identity.package_id == PACKAGE
    assert summary.collection_code == "CRPT"
    assert summary.date_issued == "2025-01-21"
    assert summary.last_modified == "2025-05-16T15:44:06Z"
    assert summary.title is not None and summary.title.startswith("PROVIDING FOR CONSIDERATION")
    # Measured 2026-09-19: the CRPT summary names only premis, zip and mods,
    # while the package does serve HTML and PDF. The links are kept as the
    # publisher spelled them; the offered set comes from the MODS instead.
    assert [name for name, _url in summary.download_links] == ["modsLink", "premisLink", "zipLink"]


def test_download_links_are_kept_as_evidence_including_a_repeated_name() -> None:
    # GPO-J6-REPORT states five jpegLink entries as one list.
    document = {
        "packageId": PACKAGE,
        "collectionCode": "CRPT",
        "download": {
            "txtLink": f"https://api.govinfo.gov/packages/{PACKAGE}/htm",
            "jpegLink": [f"https://api.govinfo.gov/packages/{PACKAGE}/jpeg"] * 2,
        },
    }
    summary = validate_package_summary(
        json.dumps(document).encode(), package=PACKAGE, final_url=SUMMARY_URL, max_bytes=10_000
    )
    assert summary.download_links == (
        ("jpegLink", f"https://api.govinfo.gov/packages/{PACKAGE}/jpeg"),
        ("jpegLink", f"https://api.govinfo.gov/packages/{PACKAGE}/jpeg"),
        ("txtLink", f"https://api.govinfo.gov/packages/{PACKAGE}/htm"),
    )


@pytest.mark.parametrize(
    ("body", "final_url", "message"),
    [
        (json.dumps({"packageId": "CRPT-119hrpt2", "collectionCode": "CRPT"}).encode(), SUMMARY_URL, "packageId"),
        (json.dumps({"packageId": PACKAGE, "collectionCode": "CHRG"}).encode(), SUMMARY_URL, "collectionCode"),
        (json.dumps({"packageId": PACKAGE}).encode(), SUMMARY_URL, "collectionCode"),
        (json.dumps([PACKAGE]).encode(), SUMMARY_URL, "not a JSON object"),
        (b"{", SUMMARY_URL, "invalid"),
        (b"", SUMMARY_URL, "empty"),
        (SUMMARY, MODS_URL, "final URL"),
        (
            json.dumps({"packageId": PACKAGE, "collectionCode": "CRPT", "download": []}).encode(),
            SUMMARY_URL,
            "download block",
        ),
        (
            json.dumps({"packageId": PACKAGE, "collectionCode": "CRPT", "download": {"zipLink": 7}}).encode(),
            SUMMARY_URL,
            "download link",
        ),
    ],
)
def test_summary_refusals(body: bytes, final_url: str, message: str) -> None:
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_package_summary(body, package=PACKAGE, final_url=final_url, max_bytes=200_000)


def test_summary_over_its_byte_bound_refuses() -> None:
    with pytest.raises(GovInfoBodySourceError, match="byte bound"):
        validate_package_summary(SUMMARY, package=PACKAGE, final_url=SUMMARY_URL, max_bytes=len(SUMMARY) - 1)


def test_real_mods_states_the_access_id_and_the_offered_renditions() -> None:
    mods = validate_package_mods(MODS, package=PACKAGE, final_url=MODS_URL, max_bytes=200_000)
    assert mods.access_ids == (PACKAGE, PACKAGE)
    assert mods.collection_code == "CRPT"
    assert mods.offered_formats == ("htm", "pdf")
    assert mods.other_renditions == ()


def test_this_packages_rendition_at_another_address_reads_as_disagreement() -> None:
    # BILLS states a USLM rendition this way: the package's own content
    # address, a supported file type, a folder this module does not derive.
    uslm = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/uslm/{PACKAGE}.xml"
    body = mods_xml(
        urls=(
            f'<url displayLabel="HTML rendition" access="raw object">{BODY_URL}</url>'
            f'<url displayLabel="USLM rendition" access="raw object">{uslm}</url>'
            '<url displayLabel="Content Detail" access="object in context">'
            f"https://www.govinfo.gov/app/details/{PACKAGE}</url>"
        )
    )
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.offered_formats == ("htm",)
    assert mods.moved_renditions == (("xml", uslm),)
    assert mods.other_renditions == ()


def test_another_packages_rendition_and_an_unsupported_file_type_say_nothing_here() -> None:
    other = "https://www.govinfo.gov/content/pkg/CRPT-119hrpt2/html/CRPT-119hrpt2.htm"
    jpeg = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/jpeg/{PACKAGE}.jpg"
    body = mods_xml(
        urls=(
            f'<url displayLabel="HTML rendition" access="raw object">{other}</url>'
            f'<url displayLabel="Image" access="raw object">{jpeg}</url>'
        )
    )
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.offered_formats == ()
    assert mods.moved_renditions == ()
    assert mods.other_renditions == (("HTML rendition", other), ("Image", jpeg))


@pytest.mark.parametrize(
    ("body", "final_url", "message"),
    [
        (mods_xml(access_id="CRPT-119hrpt2"), MODS_URL, "accessId differs"),
        (mods_xml(collection="CHRG"), MODS_URL, "collectionCode differs"),
        (b'<mods xmlns="http://www.loc.gov/mods/v3"><location/></mods>', MODS_URL, "states no accessId"),
        (b"<notmods/>", MODS_URL, "unreadable"),
        (b"<mods", MODS_URL, "unreadable"),
        (mods_xml(), SUMMARY_URL, "final URL"),
        (b"", MODS_URL, "empty"),
    ],
)
def test_mods_refusals(body: bytes, final_url: str, message: str) -> None:
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_package_mods(body, package=PACKAGE, final_url=final_url, max_bytes=200_000)


def test_every_package_level_access_id_must_agree() -> None:
    body = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{PACKAGE}</accessId></extension>"
        "<extension><accessId>CRPT-119hrpt9</accessId></extension></mods>"
    ).encode()
    with pytest.raises(GovInfoBodySourceError, match="accessId differs"):
        validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)


def test_a_constituent_access_id_names_a_granule_not_this_package() -> None:
    body = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{PACKAGE}</accessId></extension>"
        '<relatedItem type="constituent"><extension>'
        f"<accessId>{PACKAGE}-pt1</accessId></extension></relatedItem></mods>"
    ).encode()
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.access_ids == (PACKAGE,)


def test_real_body_is_proved_by_its_locator_and_media_type() -> None:
    identity = validate_package_body(
        BODY, package=PACKAGE, format="htm", content_type="text/html", final_url=BODY_URL, max_bytes=200_000
    )
    assert identity.format == "htm"
    assert identity.media_type == "text/html"
    assert identity.byte_size == len(BODY) == 13_953
    # The body names no package: identity rests on the locator, the MODS
    # rendition statement and the error-page exclusion, not on a printed id.
    assert PACKAGE.encode() not in BODY


@pytest.mark.parametrize(
    ("body", "format", "content_type", "final_url", "message"),
    [
        (b"", "htm", "text/html", BODY_URL, "empty"),
        (ERROR_PAGE, "htm", "text/html", BODY_URL, "error page"),
        (b"<html>whatever</html>", "htm", "text/html", "https://www.govinfo.gov/error", "error page"),
        (BODY, "htm", "application/pdf", BODY_URL, "Content-Type"),
        (BODY, "htm", None, BODY_URL, "Content-Type"),
        (BODY, "htm", "text/html", MODS_URL, "final URL"),
        (
            b"not a pdf",
            "pdf",
            "application/pdf",
            f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{PACKAGE}.pdf",
            "%PDF-",
        ),
    ],
)
def test_body_refusals(body: bytes, format: str, content_type: str | None, final_url: str, message: str) -> None:
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_package_body(
            body, package=PACKAGE, format=format, content_type=content_type, final_url=final_url, max_bytes=200_000
        )


def test_body_over_its_byte_bound_refuses() -> None:
    with pytest.raises(GovInfoBodySourceError, match="byte bound"):
        validate_package_body(
            BODY, package=PACKAGE, format="htm", content_type="text/html", final_url=BODY_URL, max_bytes=len(BODY) - 1
        )


@pytest.mark.parametrize("format", sorted(PACKAGE_BODY_FORMATS))
def test_every_supported_format_accepts_its_own_media_type(format: str) -> None:
    body = b"%PDF-1.4\n" if format == "pdf" else b"<x/>"
    media_type = PACKAGE_BODY_FORMATS[format].media_types[0]
    identity = validate_package_body(
        body,
        package=PACKAGE,
        format=format,
        content_type=f"{media_type}; charset=utf-8",
        final_url=package_body_locator(PACKAGE, format),
        max_bytes=1_000,
    )
    assert identity.format == format and identity.media_type == media_type


def test_the_error_page_rule_is_the_same_one_the_federal_register_route_uses() -> None:
    with pytest.raises(FederalRegisterBodySourceError, match="soft-404"):
        validate_govinfo_granule(
            ERROR_PAGE,
            source_document_number="98-14931",
            publication_date="1998-06-03",
            access_id="98-14931",
            final_url="https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm",
            max_bytes=1_024,
        )
