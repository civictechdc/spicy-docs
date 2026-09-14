"""USLM requests and response checks prove native identity and keep publisher spellings."""

import io
import zipfile
from pathlib import Path

import pytest

from spicy_docs.sources.govinfo.uslm import (
    DEFAULT_MAX_BYTES,
    MAX_USLM_BYTES,
    PublicLawSelection,
    StatuteCompilationSelection,
    UslmSourceError,
    public_law_archive_locator,
    public_law_xml_locator,
    read_public_law_archive,
    read_statute_compilations_archive,
    statute_compilation_xml_locator,
    statute_compilations_archive_locator,
    validate_public_law_xml,
    validate_statute_compilation_xml,
)

FIXTURES = Path(__file__).parent / "fixtures" / "uslm"
LAW = PublicLawSelection(119, "public", 1)
COMPILATION = StatuteCompilationSelection(10542)
LAW_XML = (FIXTURES / "plaw-119publ1.xml").read_bytes()
COMPS_XML = (FIXTURES / "comps-10542.xml").read_bytes()
NS = b'xmlns="http://schemas.gpo.gov/xml/uslm" xmlns:dc="http://purl.org/dc/elements/1.1/"'
# Constructed source-shaped inputs for structural refusals; fixtures cover the publisher shape.
MINIMAL_LAW = (
    b"<pLaw " + NS + b"><meta><dc:title>Public Law 119\xe2\x80\x931: Test</dc:title><dc:type>Public Law</dc:type>"
    b"<docNumber>1</docNumber><citableAs>Public Law 119\xe2\x80\x931</citableAs><citableAs>139 Stat. 3</citableAs>"
    b"<approvedDate>2025-01-29</approvedDate><congress>119</congress><publicPrivate>public</publicPrivate></meta>"
    b"<main><section>Text.</section></main></pLaw>"
)
MINIMAL_COMPS = (
    b"<statuteCompilation " + NS + b"><meta><dc:title>ACT</dc:title><dc:type>Statute Compilation</dc:type>"
    b'<currentThroughPublicLaw>113\xe2\x80\x9323</currentThroughPublicLaw><property role="fileId">10542</property>'
    b'<congress>113</congress></meta><preface><property role="compShortTitle">ACT</property></preface>'
    b"<main><section>Text.</section></main></statuteCompilation>"
)


def law(body=LAW_XML, *, selection=LAW, final_url=None, **kwargs):
    return validate_public_law_xml(
        body, selection=selection, final_url=final_url or public_law_xml_locator(selection), **kwargs
    )


def compilation(body=COMPS_XML, *, selection=COMPILATION, final_url=None, **kwargs):
    return validate_statute_compilation_xml(
        body, selection=selection, final_url=final_url or statute_compilation_xml_locator(selection), **kwargs
    )


def archive(*members: tuple[str, bytes], compression=zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "selection",
    [
        (True, "public", 1),
        (0, "public", 1),
        (1000, "public", 1),
        (119, "Public", 1),
        (119, "enrolled", 1),
        (119, "public", 0),
        (119, "public", "1"),
    ],
)
def test_law_selection_refuses_invalid_coordinates(selection):
    with pytest.raises(UslmSourceError):
        PublicLawSelection(*selection)


@pytest.mark.parametrize("file_id", [True, 0, -1, "10542", 1.0, 10**9])
def test_compilation_selection_refuses_invalid_identifier(file_id):
    with pytest.raises(UslmSourceError):
        StatuteCompilationSelection(file_id)


def test_selection_file_names_round_trip_and_publisher_placeholder_identifier_is_accepted():
    assert PublicLawSelection.from_file_name("PLAW-119publ1.xml") == LAW
    assert PublicLawSelection.from_file_name("PLAW-115pvtl1.xml") == PublicLawSelection(115, "private", 1)
    assert PublicLawSelection(115, "private", 1).file_name == "PLAW-115pvtl1.xml"
    assert PublicLawSelection(115, "private", 1).citation == "Private Law 115–1"
    assert StatuteCompilationSelection.from_file_name("COMPS-88888888.xml").file_id == 88888888
    for name in ("PLAW-119publ1.XML", "plaw-119publ1.xml", "PLAW-119publ.xml", "dir/PLAW-119publ1.xml", "COMPS-1.xml"):
        with pytest.raises(UslmSourceError):
            PublicLawSelection.from_file_name(name)
    for name in ("COMPS-.xml", "COMPS-1", "PLAW-119publ1.xml", "COMPS-1.xml.bak"):
        with pytest.raises(UslmSourceError):
            StatuteCompilationSelection.from_file_name(name)


def test_locators_name_exact_keyless_bulkdata_routes():
    assert public_law_xml_locator(LAW) == "https://www.govinfo.gov/bulkdata/PLAW/119/public/PLAW-119publ1.xml"
    assert public_law_archive_locator(119, "private") == (
        "https://www.govinfo.gov/bulkdata/PLAW/119/private/PLAW-119-private.zip"
    )
    assert statute_compilation_xml_locator(COMPILATION) == "https://www.govinfo.gov/bulkdata/COMPS/COMPS-10542.xml"
    assert statute_compilations_archive_locator() == "https://www.govinfo.gov/bulkdata/COMPS/COMPS.zip"
    with pytest.raises(UslmSourceError):
        public_law_archive_locator(119, "Public")
    with pytest.raises(UslmSourceError):
        public_law_xml_locator((119, "public", 1))


def test_public_law_fixture_yields_native_identity_and_publisher_spellings():
    result = law()
    assert result.source == "public-law" and result.root_tag == "pLaw"
    assert (result.congress, result.public_private, result.doc_number) == ("119", "public", "1")
    assert result.citable_as == ("Public Law 119–1", "139 Stat. 3")
    assert result.title.startswith("Public Law 119–1: To require the Secretary of Homeland Security")
    assert result.document_type == "Public Law"
    assert result.approved_date == "2025-01-29"
    assert result.processed_date == "2026-09-09"
    assert result.processed_by == "GPO Locator to USLM Converter 4.15.98;Stage2.20260514"
    assert result.schema_location.endswith("uslm-2.0.17.xsd")
    assert result.body_present is True
    assert result.identity_basis == ("congress:native", "kind:native", "number:native", "citation:native")
    assert result.file_id is None and result.current_through_public_law == ()


def test_compilation_fixture_yields_file_identifier_and_raw_currency():
    result = compilation()
    assert result.source == "statute-compilation" and result.root_tag == "statuteCompilation"
    assert result.file_id == "10542"
    assert result.title == "Hydropower Regulatory Efficiency Act of 2013"
    assert result.short_title == "Hydropower Regulatory Efficiency Act of 2013"
    assert result.current_through_public_law == ("113–23",)
    assert result.citable_as == ("Public Law 113–23",)
    assert (result.congress, result.doc_number, result.approved_date) == ("113", "23", "2013-08-09")
    assert result.document_type == "Statute Compilation"
    assert result.schema_location.endswith("uslm-2.0.10.xsd")
    assert result.identity_basis == ("file-id:native",)
    assert result.body_present is True and result.public_private is None


def test_minimal_documents_validate_and_currency_variants_stay_raw_in_order():
    assert law(MINIMAL_LAW).citable_as == ("Public Law 119–1", "139 Stat. 3")
    repeated = MINIMAL_COMPS.replace(
        b"</currentThroughPublicLaw>",
        b"</currentThroughPublicLaw><currentThroughPublicLaw>P.L.  111\xe2\x80\x93148</currentThroughPublicLaw>",
    )
    assert compilation(repeated).current_through_public_law == ("113–23", "P.L.  111–148")
    absent = MINIMAL_COMPS.replace(b"<currentThroughPublicLaw>113\xe2\x80\x9323</currentThroughPublicLaw>", b"")
    assert compilation(absent).current_through_public_law == ()


def test_preface_only_stub_is_accepted_and_flagged_without_main_text():
    stub = MINIMAL_COMPS.replace(b"<main><section>Text.</section></main>", b"<main/>")
    assert compilation(stub).body_present is False
    empty = stub.replace(b'<preface><property role="compShortTitle">ACT</property></preface>', b"<preface/>")
    with pytest.raises(UslmSourceError, match="source content"):
        compilation(empty)


def test_citation_comparison_tolerates_dash_and_spacing_but_keeps_the_publisher_string():
    hyphen = MINIMAL_LAW.replace(
        b"<citableAs>Public Law 119\xe2\x80\x931</citableAs>", b"<citableAs>Public  Law 119-1</citableAs>"
    )
    assert law(hyphen).citable_as == ("Public  Law 119-1", "139 Stat. 3")


@pytest.mark.parametrize(
    "body,message",
    [
        (MINIMAL_LAW.replace(b"<congress>119</congress>", b"<congress>118</congress>"), "native identity"),
        (
            MINIMAL_LAW.replace(b"<publicPrivate>public</publicPrivate>", b"<publicPrivate>private</publicPrivate>"),
            "native identity",
        ),
        (MINIMAL_LAW.replace(b"<docNumber>1</docNumber>", b"<docNumber>2</docNumber>"), "native identity"),
        (MINIMAL_LAW.replace(b"<docNumber>1</docNumber>", b""), "lacks an identity field"),
        (
            MINIMAL_LAW.replace(b"<congress>119</congress>", b"<congress>119</congress><congress>119</congress>"),
            "repeats an identity field",
        ),
        (MINIMAL_LAW.replace(b"<citableAs>Public Law 119\xe2\x80\x931</citableAs>", b""), "citable form"),
        (
            MINIMAL_LAW.replace(b"<dc:title>Public Law 119\xe2\x80\x931: Test</dc:title>", b"<dc:title> </dc:title>"),
            "lacks an identity field",
        ),
        (MINIMAL_LAW.replace(b"<pLaw ", b"<statuteCompilation ").replace(b"</pLaw>", b"</statuteCompilation>"), "root"),
        (MINIMAL_LAW.replace(b"<main>", b"<main><pLaw>"), "nested"),
        (MINIMAL_LAW.replace(b"</meta>", b"</meta><meta/>"), "exactly one meta"),
        (MINIMAL_LAW.replace(b"<main><section>Text.</section></main>", b"<main> </main>"), "source content"),
        (MINIMAL_LAW.replace(b'xmlns="http://schemas.gpo.gov/xml/uslm"', b'xmlns="urn:other"'), "root"),
        (b"<html><body>Checking your browser</body></html>", "root"),
        (MINIMAL_LAW[:-7], "malformed"),
        (b"<!DOCTYPE pLaw [<!ENTITY x 'y'>]>" + MINIMAL_LAW, "DOCTYPE"),
        (b"", "nonempty"),
    ],
)
def test_public_law_refusals_name_the_failed_check(body, message):
    with pytest.raises(UslmSourceError, match=message):
        law(body)


@pytest.mark.parametrize(
    "body,message",
    [
        (
            MINIMAL_COMPS.replace(
                b'<property role="fileId">10542</property>', b'<property role="fileId">10543</property>'
            ),
            "file identifier",
        ),
        (
            MINIMAL_COMPS.replace(
                b'<property role="fileId">10542</property>', b'<property role="other">10542</property>'
            ),
            "fileId",
        ),
        (
            MINIMAL_COMPS.replace(
                b'<property role="fileId">10542</property>', b'<property role="fileId">10542</property>' * 2
            ),
            "fileId",
        ),
        (
            MINIMAL_COMPS.replace(b"<dc:type>Statute Compilation</dc:type>", b"<dc:type>Public Law</dc:type>"),
            "document type",
        ),
        (
            MINIMAL_COMPS.replace(b"<statuteCompilation ", b"<pLaw ").replace(b"</statuteCompilation>", b"</pLaw>"),
            "root",
        ),
        (MINIMAL_COMPS.replace(b"<dc:title>ACT</dc:title>", b""), "lacks an identity field"),
    ],
)
def test_compilation_refusals_name_the_failed_check(body, message):
    with pytest.raises(UslmSourceError, match=message):
        compilation(body)


def test_response_url_must_be_the_requested_locator():
    with pytest.raises(UslmSourceError, match="URL"):
        law(final_url=public_law_xml_locator(PublicLawSelection(119, "public", 2)))
    with pytest.raises(UslmSourceError, match="URL"):
        compilation(final_url=statute_compilation_xml_locator(StatuteCompilationSelection(1)))


@pytest.mark.parametrize("max_bytes", [0, -1, True, 1.5, MAX_USLM_BYTES + 1])
def test_byte_bounds_are_explicit_and_capped(max_bytes):
    with pytest.raises(UslmSourceError):
        law(max_bytes=max_bytes)
    with pytest.raises(UslmSourceError):
        read_statute_compilations_archive(archive(("COMPS-10542.xml", COMPS_XML)), max_bytes=max_bytes)


def test_body_larger_than_max_bytes_is_refused_before_parsing():
    with pytest.raises(UslmSourceError, match="max_bytes"):
        law(max_bytes=len(LAW_XML) - 1)
    assert law(max_bytes=len(LAW_XML)).doc_number == "1"
    assert DEFAULT_MAX_BYTES == 32 * 1024 * 1024


def test_public_law_archive_validates_every_entry_against_its_own_name():
    second = LAW_XML.replace(b"<docNumber>1</docNumber>", b"<docNumber>2</docNumber>").replace(
        b"<citableAs>Public Law 119\xe2\x80\x931</citableAs>", b"<citableAs>Public Law 119\xe2\x80\x932</citableAs>"
    )
    body = archive(("PLAW-119publ1.xml", LAW_XML), ("folder/", b""), ("PLAW-119publ2.xml", second))
    result = read_public_law_archive(body, congress=119, kind="public")
    assert result.source == "public-law"
    assert [entry.name for entry in result.entries] == ["PLAW-119publ1.xml", "PLAW-119publ2.xml"]
    assert result.entries[0].byte_size == len(LAW_XML)
    assert result.entries[0].sha256 == "sha256:ee0e7a5d534411f78dd325405c42d386a1cfcf14f3870c93f5488874bb7acb54"
    assert result.entries[1].metadata.doc_number == "2"
    nested = read_public_law_archive(archive(("119/public/PLAW-119publ1.xml", LAW_XML)), congress=119, kind="public")
    assert nested.entries[0].name == "119/public/PLAW-119publ1.xml"


def test_compilations_archive_validates_entries_and_refuses_foreign_names():
    result = read_statute_compilations_archive(archive(("COMPS-10542.xml", COMPS_XML)))
    assert result.source == "statute-compilation"
    assert result.entries[0].metadata.file_id == "10542"
    with pytest.raises(UslmSourceError, match="file name"):
        read_statute_compilations_archive(archive(("PLAW-119publ1.xml", LAW_XML)))


@pytest.mark.parametrize(
    "body,kwargs,message",
    [
        (archive(("PLAW-118publ1.xml", LAW_XML)), {}, "another Congress"),
        (archive(("PLAW-119pvtl1.xml", LAW_XML)), {}, "another Congress"),
        (archive(("PLAW-119publ2.xml", LAW_XML)), {}, "native identity"),
        (archive(("PLAW-119publ1.xml", LAW_XML), ("a/PLAW-119publ1.xml", LAW_XML)), {}, "repeats an entry"),
        (archive(("PLAW-119publ1.xml", LAW_XML), ("readme.txt", b"x")), {}, "file name"),
        (archive(("PLAW-119publ1.xml", LAW_XML)), {"max_entry_bytes": len(LAW_XML) - 1}, "max_entry_bytes"),
        (archive(("PLAW-119publ1.xml", LAW_XML), ("PLAW-119publ2.xml", LAW_XML)), {"max_entries": 1}, "max_entries"),
        (b"PK\x03\x04not really a zip", {}, "malformed"),
        (LAW_XML, {}, "local file header"),
        (b"", {}, "nonempty"),
    ],
)
def test_public_law_archive_refusals(body, kwargs, message):
    with pytest.raises(UslmSourceError, match=message):
        read_public_law_archive(body, congress=119, kind="public", **kwargs)


def test_archive_crc_corruption_is_refused_before_any_entry_is_trusted():
    body = bytearray(archive(("PLAW-119publ1.xml", LAW_XML), compression=zipfile.ZIP_STORED))
    offset = body.index(b"<pLaw")
    body[offset + 1] ^= 0x01
    with pytest.raises(UslmSourceError, match="CRC"):
        read_public_law_archive(bytes(body), congress=119, kind="public")


def test_archive_bounds_are_validated_before_reading():
    body = archive(("PLAW-119publ1.xml", LAW_XML))
    with pytest.raises(UslmSourceError, match="max_bytes"):
        read_public_law_archive(body, congress=119, kind="public", max_bytes=len(body) - 1)
    with pytest.raises(UslmSourceError, match="max_entries"):
        read_public_law_archive(body, congress=119, kind="public", max_entries=0)
    with pytest.raises(UslmSourceError):
        read_public_law_archive(body, congress=119, kind="Public")
