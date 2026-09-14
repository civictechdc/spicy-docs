"""OLRC U.S. Code requests and response checks prove native identity and keep publisher spellings."""

import io
import zipfile
from pathlib import Path

import pytest

from spicy_docs.sources.uscode import (
    DEFAULT_MAX_XML_BYTES,
    MAX_USCODE_BYTES,
    TITLES,
    ReleasePoint,
    TitleSelection,
    UsCodeSourceError,
    annual_archive_locator,
    corpus_xml_locator,
    iter_act_fragments,
    iter_table3_acts,
    parse_popular_names,
    parse_table3_page,
    popular_names_locator,
    read_annual_archive,
    read_corpus_archive,
    read_table3_bulk_archive,
    read_title_archive,
    table3_act_locator,
    table3_bulk_locator,
    table3_file_name,
    title_xml_locator,
    validate_annual_title_html,
    validate_title_xml,
)

FIXTURES = Path(__file__).parent / "fixtures" / "uscode"
CURRENT = ReleasePoint(119, 103)
RETAINED = ReleasePoint(119, 102)
TITLE_ZIP = (FIXTURES / "xml_usc01@119-103.zip").read_bytes()
APPENDIX_XML = (FIXTURES / "usc50A.xml").read_bytes()
ANNUAL_HTML = (FIXTURES / "annual-2024usc01-head.htm").read_bytes()
POPULAR_NAMES = (FIXTURES / "popularnames-head.htm").read_bytes()
TABLE3_CHAPTER = (FIXTURES / "table3-1955_360-head.htm").read_bytes()
TABLE3_LAW = (FIXTURES / "table3-111_226-head.htm").read_bytes()
TABLE3_TRUNCATED = (FIXTURES / "table3-100_234-truncated.htm").read_bytes()
BULK_XML = (FIXTURES / "table3-fulldump-head.xml").read_bytes()

with zipfile.ZipFile(io.BytesIO(TITLE_ZIP)) as _archive:
    TITLE_XML = _archive.read("usc01.xml")

NS = (
    b'xmlns="http://xml.house.gov/schemas/uslm/1.0" xmlns:dc="http://purl.org/dc/elements/1.1/"'
    b' xmlns:dcterms="http://purl.org/dc/terms/"'
)
# Constructed source-shaped inputs for structural refusals; fixtures cover the publisher shape.
MINIMAL_TITLE = (
    b"<uscDoc " + NS + b' identifier="/us/usc/t1"><meta><dc:title>Title 1</dc:title><dc:type>USCTitle</dc:type>'
    b"<docNumber>1</docNumber><docPublicationName>Online@119-103</docPublicationName>"
    b'<property role="is-positive-law">yes</property><dc:publisher>OLRC</dc:publisher>'
    b"<dcterms:created>2026-09-09T11:00:02</dcterms:created><dc:creator>USCConverter 1.7.2</dc:creator></meta>"
    b"<main><title><num>Title 1\xe2\x80\x94</num><heading>GENERAL PROVISIONS</heading></title></main></uscDoc>"
)


def title(body=TITLE_XML, *, selection=None, **kwargs):
    return validate_title_xml(body, selection=selection or TitleSelection(CURRENT, "01"), **kwargs)


def archive(*members: tuple[str, bytes], compression=zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buffer.getvalue()


BULK_ZIP = archive(("fulldump@119-73.xml", BULK_XML))


# --------------------------------------------------------------------------- #
# selections and locators
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("coordinates", [(True, 1), (0, 1), (1000, 1), (119, 0), (119, "103"), (119.0, 1)])
def test_release_point_refuses_invalid_coordinates(coordinates):
    with pytest.raises(UsCodeSourceError):
        ReleasePoint(*coordinates)


def test_release_point_round_trips_the_publisher_label():
    assert ReleasePoint.from_label("119-103") == CURRENT
    assert CURRENT.label == "119-103" and CURRENT.path == "119/103"
    for label in ("119-103 ", "119_103", "0-1", "119-", "", "Online@119-103"):
        with pytest.raises(UsCodeSourceError):
            ReleasePoint.from_label(label)


def test_title_selection_keeps_the_publisher_code_and_derives_its_native_spelling():
    assert TitleSelection(CURRENT, "01").doc_number == "1"
    assert TitleSelection(CURRENT, "05a").doc_number == "5a"
    assert TitleSelection(CURRENT, "50a").identifier == "/us/usc/t50a"
    assert TitleSelection(CURRENT, "11a").is_appendix and not TitleSelection(CURRENT, "11").is_appendix
    assert TitleSelection(CURRENT, "05a").file_name == "xml_usc05a@119-103.zip"
    # 53 is reserved: the publisher links it and the route answers 302, so the
    # code is a selection and the refusal belongs to the response.
    assert "53" in TITLES and len(TITLES) == 59
    for code in ("1", "5A", "60", "all", "All", ""):
        with pytest.raises(UsCodeSourceError):
            TitleSelection(CURRENT, code)
    with pytest.raises(UsCodeSourceError):
        TitleSelection((119, 103), "01")


def test_locators_name_exact_keyless_routes():
    assert title_xml_locator(TitleSelection(CURRENT, "05a")) == (
        "https://uscode.house.gov/download/releasepoints/us/pl/119/103/xml_usc05a@119-103.zip"
    )
    assert corpus_xml_locator(CURRENT) == (
        "https://uscode.house.gov/download/releasepoints/us/pl/119/103/xml_uscAll@119-103.zip"
    )
    assert annual_archive_locator(2024) == ("https://uscode.house.gov/download/annualhistoricalarchives/XHTML/2024.zip")
    assert popular_names_locator() == "https://uscode.house.gov/popularnames/popularnames.htm"
    assert table3_bulk_locator() == "https://uscode.house.gov/table3/table3-xml-bulk.zip"
    with pytest.raises(UsCodeSourceError):
        title_xml_locator(("119-103", "01"))
    with pytest.raises(UsCodeSourceError):
        corpus_xml_locator("119-103")
    for year in (1993, True, "2024", 2101):
        with pytest.raises(UsCodeSourceError):
            annual_archive_locator(year)


def test_table3_file_names_follow_the_rule_the_publishers_own_page_applies():
    # getActFileName() in table3years.htm: the first "-", then the ":", become "_".
    assert table3_file_name("1955:360") == "1955_360.htm"
    assert table3_file_name("111-226") == "111_226.htm"
    assert table3_act_locator("90-148") == "https://uscode.house.gov/table3/90_148.htm"
    for key in ("1955-360", "119_21", "0-1", "1955:", "abc", "", "119-21.htm", None):
        with pytest.raises(UsCodeSourceError):
            table3_file_name(key)


# --------------------------------------------------------------------------- #
# release-point USLM
# --------------------------------------------------------------------------- #


def test_title_fixture_yields_native_identity_and_publisher_spellings():
    result = title()
    assert result.source == "release-point-title" and result.title == "01"
    assert (result.doc_number, result.release_point) == ("1", "Online@119-103")
    assert result.document_type == "USCTitle" and result.heading == "Title 1"
    assert result.positive_law == "yes" and result.publisher == "OLRC"
    assert result.converter == "USCConverter 1.7.2" and result.created == "2026-09-09T11:00:02"
    assert result.schema_location == "http://xml.house.gov/schemas/uslm/1.0 USLM-1.0.15.xsd"
    assert result.identifier == "/us/usc/t1" and result.body_present is True
    assert result.identity_basis == (
        "doc-number:native",
        "release-point:native",
        "document-type:native",
        "identifier:native",
    )


def test_eliminated_appendix_keeps_its_own_converter_and_states_no_root_identifier():
    result = title(APPENDIX_XML, selection=TitleSelection(RETAINED, "50a"))
    assert (result.doc_number, result.document_type) == ("50a", "USCTitleAppendix")
    assert result.heading == "Title 50 Appendix" and result.positive_law == "no"
    # Converted in 2015 and reissued unchanged since; its root carries no identifier.
    assert result.converter == "USCConverter 1.1" and result.identifier is None
    assert result.identity_basis == ("doc-number:native", "release-point:native", "document-type:native")
    assert result.body_present is True


def test_response_url_is_checked_only_when_the_caller_supplies_one():
    assert title(final_url=title_xml_locator(TitleSelection(CURRENT, "01"))).doc_number == "1"
    with pytest.raises(UsCodeSourceError, match="URL"):
        title(final_url=title_xml_locator(TitleSelection(CURRENT, "02")))


@pytest.mark.parametrize(
    "body,message",
    [
        (MINIMAL_TITLE.replace(b"<docNumber>1</docNumber>", b"<docNumber>2</docNumber>"), "native number"),
        (MINIMAL_TITLE.replace(b"<docNumber>1</docNumber>", b""), "lacks an identity field"),
        (
            MINIMAL_TITLE.replace(b"<docNumber>1</docNumber>", b"<docNumber>1</docNumber>" * 2),
            "repeats an identity field",
        ),
        (MINIMAL_TITLE.replace(b"Online@119-103", b"Online@119-102"), "native release point"),
        (MINIMAL_TITLE.replace(b"<dc:type>USCTitle</dc:type>", b"<dc:type>USCTitleAppendix</dc:type>"), "kind"),
        (MINIMAL_TITLE.replace(b'identifier="/us/usc/t1"', b'identifier="/us/usc/t2"'), "native identifier"),
        (MINIMAL_TITLE.replace(b"<uscDoc ", b"<pLaw ").replace(b"</uscDoc>", b"</pLaw>"), "root is not uscDoc"),
        (
            MINIMAL_TITLE.replace(
                b'xmlns="http://xml.house.gov/schemas/uslm/1.0"', b'xmlns="http://schemas.gpo.gov/xml/uslm"'
            ),
            "root is not uscDoc",
        ),
        (MINIMAL_TITLE.replace(b"<main>", b"<main><uscDoc>"), "nested"),
        (MINIMAL_TITLE.replace(b"</meta>", b"</meta><meta/>"), "exactly one meta"),
        (
            MINIMAL_TITLE.replace(b"<main>", b"<main> ").replace(
                b"<title><num>Title 1\xe2\x80\x94</num><heading>GENERAL PROVISIONS</heading></title>", b""
            ),
            "source content",
        ),
        (
            MINIMAL_TITLE.replace(
                b'<property role="is-positive-law">yes</property>',
                b'<property role="is-positive-law">yes</property>' * 2,
            ),
            "repeats the is-positive-law property",
        ),
        (b"<html><body>Document not found</body></html>", "root is not uscDoc"),
        (MINIMAL_TITLE[:-9], "malformed"),
        (b"<!DOCTYPE uscDoc [<!ENTITY x 'y'>]>" + MINIMAL_TITLE, "DOCTYPE"),
        (b"", "nonempty"),
    ],
)
def test_title_refusals_name_the_failed_check(body, message):
    with pytest.raises(UsCodeSourceError, match=message):
        title(body)


def test_minimal_document_and_appendix_body_section_both_carry_text():
    assert title(MINIMAL_TITLE).heading == "Title 1"
    appendix = (
        MINIMAL_TITLE.replace(b"<docNumber>1</docNumber>", b"<docNumber>50a</docNumber>")
        .replace(b"<dc:type>USCTitle</dc:type>", b"<dc:type>USCTitleAppendix</dc:type>")
        .replace(b'identifier="/us/usc/t1"', b'identifier="/us/usc/t50a"')
        .replace(b"<main>", b"<appendix>")
        .replace(b"</main>", b"</appendix>")
    )
    assert title(appendix, selection=TitleSelection(CURRENT, "50a")).document_type == "USCTitleAppendix"


@pytest.mark.parametrize("max_bytes", [0, -1, True, 1.5, MAX_USCODE_BYTES + 1])
def test_byte_bounds_are_explicit_and_capped(max_bytes):
    with pytest.raises(UsCodeSourceError):
        title(max_bytes=max_bytes)
    with pytest.raises(UsCodeSourceError):
        read_table3_bulk_archive(BULK_ZIP, max_bytes=max_bytes)


def test_body_larger_than_max_bytes_is_refused_before_parsing():
    with pytest.raises(UsCodeSourceError, match="max_bytes"):
        title(max_bytes=len(TITLE_XML) - 1)
    assert title(max_bytes=len(TITLE_XML)).doc_number == "1"
    assert DEFAULT_MAX_XML_BYTES == 128 * 1024 * 1024


def test_title_archive_holds_one_member_named_for_the_requested_title():
    result = read_title_archive(TITLE_ZIP, selection=TitleSelection(CURRENT, "01"))
    assert result.release_point == "119-103"
    assert [entry.name for entry in result.entries] == ["usc01.xml"]
    assert result.entries[0].byte_size == len(TITLE_XML)
    assert result.entries[0].sha256.startswith("sha256:")
    assert result.entries[0].metadata.doc_number == "1"


@pytest.mark.parametrize(
    "body,selection,message",
    [
        (archive(("usc02.xml", TITLE_XML)), ("01",), "member name is not the requested title"),
        (archive(("usc01.xml", TITLE_XML), ("usc02.xml", TITLE_XML)), ("01",), "exactly one member"),
        (archive(("readme.txt", b"x")), ("01",), "member name is not the requested title"),
        (archive(("usc01.xml", TITLE_XML)), ("02",), "member name is not the requested title"),
        (b"PK\x03\x04not really a zip", ("01",), "malformed"),
        (TITLE_XML, ("01",), "local file header"),
        (b"", ("01",), "nonempty"),
    ],
)
def test_title_archive_refusals(body, selection, message):
    with pytest.raises(UsCodeSourceError, match=message):
        read_title_archive(body, selection=TitleSelection(CURRENT, *selection))


def test_title_archive_entry_bound_and_crc_are_checked_before_any_entry_is_trusted():
    with pytest.raises(UsCodeSourceError, match="max_entry_bytes"):
        read_title_archive(TITLE_ZIP, selection=TitleSelection(CURRENT, "01"), max_entry_bytes=len(TITLE_XML) - 1)
    body = bytearray(archive(("usc01.xml", TITLE_XML), compression=zipfile.ZIP_STORED))
    body[body.index(b"<uscDoc") + 1] ^= 0x01
    with pytest.raises(UsCodeSourceError, match="CRC"):
        read_title_archive(bytes(body), selection=TitleSelection(CURRENT, "01"))


def test_corpus_archive_validates_every_member_against_its_own_bytes():
    # The publisher spells the same appendix both ways: usc05A.xml and usc11a.xml.
    upper = (
        MINIMAL_TITLE.replace(b"<docNumber>1</docNumber>", b"<docNumber>5a</docNumber>")
        .replace(b"<dc:type>USCTitle</dc:type>", b"<dc:type>USCTitleAppendix</dc:type>")
        .replace(b'identifier="/us/usc/t1"', b'identifier="/us/usc/t5a"')
    )
    result = read_corpus_archive(archive(("usc01.xml", TITLE_XML), ("usc05A.xml", upper)), release_point=CURRENT)
    assert [entry.metadata.doc_number for entry in result.entries] == ["1", "5a"]
    assert result.release_point == "119-103"


@pytest.mark.parametrize(
    "body,kwargs,message",
    [
        (archive(("usc01.xml", TITLE_XML), ("readme.txt", b"x")), {}, "not a title member"),
        (archive(("usc60.xml", TITLE_XML)), {}, "must be one of the codes"),
        (archive(("usc02.xml", TITLE_XML)), {}, "native number"),
        (archive(("a/usc01.xml", TITLE_XML), ("b/usc01.xml", TITLE_XML)), {}, "repeats an entry"),
        (archive(("usc01.xml", TITLE_XML)), {"max_entries": 0}, "max_entries"),
        (archive(("usc01.xml", TITLE_XML), ("usc03.xml", TITLE_XML)), {"max_entries": 1}, "more entries"),
    ],
)
def test_corpus_archive_refusals(body, kwargs, message):
    with pytest.raises(UsCodeSourceError, match=message):
        read_corpus_archive(body, release_point=CURRENT, **kwargs)


def test_corpus_archive_refuses_a_member_of_another_release_point():
    with pytest.raises(UsCodeSourceError, match="native release point"):
        read_corpus_archive(archive(("usc50A.xml", APPENDIX_XML)), release_point=CURRENT)
    assert read_corpus_archive(archive(("usc50A.xml", APPENDIX_XML)), release_point=RETAINED).entries[0].name


# --------------------------------------------------------------------------- #
# annual historical archives
# --------------------------------------------------------------------------- #


def test_annual_fixture_states_its_own_edition_year_title_and_currency():
    result = validate_annual_title_html(ANNUAL_HTML, year=2024)
    assert result.source == "annual-title"
    assert result.publication_name == "2024 Main Edition" and result.publication_id == "2024MNED024"
    assert result.publication_year == "2024"
    assert result.laws_enacted_through == "20250106"
    assert result.laws_enacted_through_stated == "January 6th, 2025"
    assert result.title_name == "TITLE 1 - GENERAL PROVISIONS"
    assert (result.title_enum, result.title_status) == ("1", "positive-law")
    assert result.conversion_program == "xy2html.pm-0.401-20240520"
    assert result.identity_basis == ("publication-year:native", "title-enum:native")


@pytest.mark.parametrize(
    "body,kwargs,message",
    [
        (ANNUAL_HTML, {"year": 2023}, "publication year differs"),
        (ANNUAL_HTML.replace(b"<!-- AUTHORITIES-USC-TITLE-ENUM:1 -->", b""), {}, "lacks an identity comment"),
        (
            ANNUAL_HTML.replace(b"<!-- AUTHORITIES-USC-TITLE-ENUM:1 -->", b"<!-- AUTHORITIES-USC-TITLE-ENUM:1 -->" * 2),
            {},
            "repeats an identity comment",
        ),
        (
            ANNUAL_HTML.replace(b"AUTHORITIES-PUBLICATION-YEAR:2024", b"AUTHORITIES-PUBLICATION-YEAR:24"),
            {},
            "four-digit",
        ),
        (
            ANNUAL_HTML.replace(b"AUTHORITIES-USC-TITLE-NAME:TITLE 1", b"AUTHORITIES-USC-TITLE-NAME:TITLE \xc2\xa71"),
            {},
            "printable ASCII",
        ),
        (ANNUAL_HTML.replace(b"</html>", b""), {}, "not closed"),
        (ANNUAL_HTML.replace(b"<!DOCTYPE html", b"<html"), {}, "XHTML doctype"),
        (b"", {}, "nonempty"),
    ],
)
def test_annual_refusals_name_the_failed_check(body, kwargs, message):
    with pytest.raises(UsCodeSourceError, match=message):
        validate_annual_title_html(body, **kwargs)


def test_annual_archive_keeps_the_files_the_publisher_ships_beside_its_titles():
    body = archive(("2024/2024usc01.htm", ANNUAL_HTML), ("2024/usc.css", b"body{}"), ("2024/index.html", b"<html/>"))
    result = read_annual_archive(body, year=2024)
    assert [entry.name for entry in result.entries] == ["2024/2024usc01.htm"]
    assert [entry.name for entry in result.others] == ["2024/usc.css", "2024/index.html"]
    assert result.others[0].sha256.startswith("sha256:") and result.others[0].metadata is None
    assert result.publication_names == ("2024 Main Edition",) and result.carried_forward == ()


def test_annual_archive_reports_the_publishers_own_carried_forward_member():
    # 2016 and 2017 both ship a Title 50 Appendix stating 2015: the appendix was
    # eliminated and the file is reissued unchanged. Reported, never refused.
    stale = ANNUAL_HTML.replace(b"AUTHORITIES-PUBLICATION-YEAR:2024", b"AUTHORITIES-PUBLICATION-YEAR:2015").replace(
        b"AUTHORITIES-USC-TITLE-ENUM:1", b"AUTHORITIES-USC-TITLE-ENUM:50"
    )
    body = archive(("2024/2024usc01.htm", ANNUAL_HTML), ("2024/2024usc50a.htm", stale))
    result = read_annual_archive(body, year=2024)
    assert result.carried_forward == ("2024/2024usc50a.htm",)
    assert len(result.entries) == 2
    with pytest.raises(UsCodeSourceError, match="states no member of the requested year"):
        read_annual_archive(archive(("2024/2024usc50a.htm", stale)), year=2024)


@pytest.mark.parametrize(
    "members,message",
    [
        ((("2024/usc.css", b"body{}"),), "holds no title member"),
        ((("2024/2024usc02.htm", ANNUAL_HTML),), "enum differs from its member name"),
        ((("2024/report.htm", ANNUAL_HTML),), "states a title under an unroutable name"),
    ],
)
def test_annual_archive_refusals(members, message):
    with pytest.raises(UsCodeSourceError, match=message):
        read_annual_archive(archive(*members), year=2024)


def test_annual_member_names_are_read_in_every_case_the_publisher_uses():
    # 2010 ships 2010USC12.htm; 2011 ships 2011usc05a.htm whose enum is just "5".
    upper = archive(("2024/2024USC01.HTM", ANNUAL_HTML))
    assert len(read_annual_archive(upper, year=2024).entries) == 1
    appendix = ANNUAL_HTML.replace(b"AUTHORITIES-USC-TITLE-ENUM:1", b"AUTHORITIES-USC-TITLE-ENUM:5")
    assert len(read_annual_archive(archive(("2024/2024usc05a.htm", appendix)), year=2024).entries) == 1


# --------------------------------------------------------------------------- #
# Popular Name Tool
# --------------------------------------------------------------------------- #


def test_popular_names_fixture_reads_one_record_per_stated_fact():
    result = parse_popular_names(POPULAR_NAMES)
    assert result.source == "popular-names"
    assert result.entries == 9 and len(result.records) == 11
    assert result.release_points == ("119-103",)
    assert result.stated_but_not_carried == {}
    first = result.records[0]
    assert first.name == "____________Act of____________" and first.content_type == "cite"
    assert first.table3_key == "111-226" and first.date_key == "2010-08-10" and first.item == "1"
    assert (first.statutes_at_large_volume, first.statutes_at_large_page) == ("124", "2389")
    assert first.statutes_at_large_witness == "both"
    # The page links each act's own Table III file, so the name is read, not derived.
    assert first.table3_href == "/table3/111_226.htm"
    assert all(
        record.table3_href == "/table3/" + table3_file_name(record.table3_key)
        for record in result.records
        if record.table3_href and record.table3_key
    )


def test_popular_names_keeps_the_tools_own_vocabulary_and_anchors():
    records = {record.name: record for record in parse_popular_names(POPULAR_NAMES).records}
    dollar = records["1921 Silver Dollar Coin Anniversary Act"]
    assert (dollar.usc_title, dollar.usc_section, dollar.usc_key) == ("31", "5112", "31:5112")
    assert dollar.stated.startswith("Pub. L. 116-286, Jan. 5, 2021,")
    chapter = records["1950 Amendment to Public Law 38"]
    assert chapter.table3_key == "1950:592" and chapter.statutes_at_large_volume == "64"


def test_popular_names_reads_the_statviewer_query_and_names_its_witness():
    only_prose = POPULAR_NAMES.replace(b"/statviewer.htm?volume=124&amp;page=2389", b"/elsewhere.htm")
    assert parse_popular_names(only_prose).records[0].statutes_at_large_witness == "stated"
    disagreeing = POPULAR_NAMES.replace(b"volume=124&amp;page=2389", b"volume=124&amp;page=9999")
    record = parse_popular_names(disagreeing).records[0]
    # Reported, never resolved: the machine-stated value stands and says so.
    assert (record.statutes_at_large_page, record.statutes_at_large_witness) == ("9999", "disagreement")


def test_popular_names_quarantines_what_it_declines_to_read():
    nameless = POPULAR_NAMES.replace(b"<p class='popular-name'>____________Act of____________</p>", b"")
    result = parse_popular_names(nameless)
    defect = result.defects[0]
    assert (defect.reason, defect.raw_value) == ("entry_without_a_name", "____________Actof____________")
    typeless = POPULAR_NAMES.replace(b"content-type='cite' t3searchkey='111-226'", b"t3searchkey='111-226'")
    assert parse_popular_names(typeless).defects[0].reason == "information_without_a_content_type"
    # 18A is not title 18: the key is kept and no anchor is minted from it.
    appendix = POPULAR_NAMES.replace(b"usckey='31:5112'", b"usckey='18A:1'")
    record = next(r for r in parse_popular_names(appendix).records if r.usc_key == "18A:1")
    assert record.usc_title is None and record.usc_section is None
    assert [d.reason for d in parse_popular_names(appendix).defects] == ["usc_key_unparsable"]


def test_popular_names_carries_the_division_that_tells_two_acts_of_one_law_apart():
    divided = POPULAR_NAMES.replace(b", Aug. 10, 2010,", b", div. EE, Dec. 27, 2020,")
    assert parse_popular_names(divided).records[0].division == "EE"


@pytest.mark.parametrize(
    "body,kwargs,message",
    [
        (POPULAR_NAMES.replace(b"</html>", b""), {}, "not closed"),
        (POPULAR_NAMES.replace(b"popular-name-table-entry", b"other-table-entry"), {}, "states no entry"),
        (POPULAR_NAMES, {"max_entries": 1}, "more entries than max_entries"),
        (POPULAR_NAMES.replace(b"<p class='popular-name'>", b"\xff<p class='popular-name'>"), {}, "UTF-8"),
        (b"", {}, "nonempty"),
    ],
)
def test_popular_names_refusals(body, kwargs, message):
    with pytest.raises(UsCodeSourceError, match=message):
        parse_popular_names(body, **kwargs)


# --------------------------------------------------------------------------- #
# Table III
# --------------------------------------------------------------------------- #


def test_table3_page_states_its_own_act_and_currency():
    result = parse_table3_page(TABLE3_CHAPTER, key="1955:360")
    assert result.source == "table3-act" and result.key == "1955:360"
    assert result.stated_key == "1955:360" and result.identity_basis == ("act-key:native",)
    # Table III lags the Code: 119-73 while the Code stands at 119-103.
    assert result.release_point == "119-73"
    assert result.congress == "84th Cong." and result.statutes_at_large_volume == "69 Stat."
    assert result.act_date == "July 14, 1955"
    assert (result.prior_act, result.next_act) == ("1955:359", "1955:368")
    assert len(result.records) == 4
    first = result.records[0]
    assert (first.act_section, first.usc_title, first.usc_section) == ("101", "42", "7401")
    # This act's statviewer links carry a volume and an empty page.
    assert (first.statutes_at_large_volume, first.statutes_at_large_page) == ("69", None)


def test_table3_page_keeps_the_en_dash_the_publisher_spells_a_public_law_with():
    result = parse_table3_page(TABLE3_LAW, key="111-226")
    assert result.key == "111-226" and result.stated_key == "111–226"
    assert (result.prior_act, result.next_act) == ("111–225", "111–227")
    assert result.records[0].statutes_at_large_page == "2389"
    assert result.records[0].usc_section == "1 nt"


def test_an_act_the_table_does_not_hold_is_refused_not_read_as_no_classifications():
    # The publisher answers HTTP 200 and 16,134 bytes of site furniture, then
    # closes the stream. Zero rows from that answer is not a fact about the act.
    assert b"table3row_" not in TABLE3_TRUNCATED and b"</html>" not in TABLE3_TRUNCATED
    with pytest.raises(UsCodeSourceError, match="truncated"):
        parse_table3_page(TABLE3_TRUNCATED, key="100-234")


@pytest.mark.parametrize(
    "body,kwargs,message",
    [
        (TABLE3_CHAPTER, {"key": "1955:359"}, "states another act"),
        (TABLE3_CHAPTER.replace(b"<span class='act'>1955:360", b"<span class='other'>1955:360"), {}, "states no act"),
        (TABLE3_CHAPTER, {"max_rows": 1}, "more rows than max_rows"),
        (TABLE3_CHAPTER.replace(b"</html>", b""), {}, "truncated"),
        (TABLE3_CHAPTER.replace(b"<caption", b"\xff<caption"), {}, "UTF-8"),
        (b"", {}, "nonempty"),
    ],
)
def test_table3_page_refusals(body, kwargs, message):
    with pytest.raises(UsCodeSourceError, match=message):
        parse_table3_page(body, **{"key": "1955:360", **kwargs})


def test_table3_bulk_archive_censuses_the_member_the_publisher_names():
    result = read_table3_bulk_archive(BULK_ZIP)
    assert result.source == "table3-bulk" and result.release_point == "119-73"
    assert result.member == "fulldump@119-73.xml" and result.member_byte_size == len(BULK_XML)
    assert result.member_sha256.startswith("sha256:")
    assert (result.act_count, result.record_count) == (3, 15)
    assert result.identity_basis == ("release-point:member-name",)
    assert read_table3_bulk_archive(BULK_ZIP, release_point="119-73").act_count == 3
    with pytest.raises(UsCodeSourceError, match="another release point"):
        read_table3_bulk_archive(BULK_ZIP, release_point="119-103")


def test_table3_bulk_acts_are_streamed_with_every_attribute_the_file_states():
    acts = list(iter_table3_acts(BULK_ZIP))
    assert [act.search_key for act in acts] == ["1789-06-01:1", "1789-07-27:4", "1789-08-07:7"]
    assert acts[0].congress == "1" and acts[0].num == "1"
    assert acts[0].date == "1789-06-01" and acts[0].statutes_at_large_volume == "1"
    assert acts[0].act_id == "bd6f585f-7c3e-43ca-ab20-e5da034b5d55"
    assert (acts[0].sequence, acts[0].insertion, acts[0].format) == ("2", "AAAA", "1")
    assert acts[0].print_in_supplement == "false"
    assert acts[0].include_in_online_release_point == "true"
    # A pre-1957 chapter act may also state its session public-law number; these do not.
    assert acts[0].public_law is None
    record = acts[0].records[0]
    assert (record.act_section, record.statutes_at_large_page) == ("2", "23")
    # Pre-codification acts state a status where modern ones state a title and section.
    assert record.usc_status == "R.S. Sec 28" and record.usc_title is None
    assert record.usc_key == "0" * 31 and record.sequence == "0"
    assert record.record_id == "606453be-0556-4faf-ac61-e904bf5b963f"
    assert record.print_in_supplement is None


def test_the_bulk_reader_fails_closed_on_a_name_it_has_no_field_for():
    # A vocabulary this reader has not seen is a reason to stop, not to drop a
    # publisher fact in silence.
    for before, after, message in (
        (b"<act ", b"<act novel-attribute='x' ", "attribute this reader has no field for: novel-attribute"),
        (b"<num>1</num>", b"<num>1</num><novel/>", "element this reader has no field for: novel"),
        (b"<record ", b"<record novel='x' ", "attribute this reader has no field for: novel"),
    ):
        body = archive(("fulldump@119-73.xml", BULK_XML.replace(before, after, 1)))
        with pytest.raises(UsCodeSourceError, match=message):
            read_table3_bulk_archive(body)


def test_the_bulk_reader_keeps_the_two_records_the_file_states_an_empty_key_on():
    # One record of the Homeland Security Act states no id and one of the
    # Families First Coronavirus Response Act states no usckey, out of 317,590.
    blanked = BULK_XML.replace(b"id='606453be-0556-4faf-ac61-e904bf5b963f'", b"id=''", 1).replace(
        b"usckey='0000000000000000000000000000000'", b"usckey=''", 1
    )
    record = next(iter_table3_acts(archive(("fulldump@119-73.xml", blanked)))).records[0]
    assert record.record_id is None and record.usc_key is None
    assert record.act_section == "2"


def test_the_bulk_member_is_split_on_act_close_and_the_split_is_checked():
    first = BULK_XML[: BULK_XML.index(b"</act>") + len(b"</act>")]
    assert [fragment for fragment in iter_act_fragments(first)] == [first.lstrip()]
    assert list(iter_act_fragments(b"  \r\n  ")) == []
    for junk, message in (
        (b"</act>", "closes an act it never opened"),
        (first + b"junk" + first, "bytes between two act elements"),
        (first + b"trailing", "bytes after the last act element"),
    ):
        with pytest.raises(UsCodeSourceError, match=message):
            list(iter_act_fragments(junk))


@pytest.mark.parametrize(
    "body,message",
    [
        (archive(("table3.xml", BULK_XML)), "not a fulldump file"),
        (archive(("fulldump@119-73.xml", BULK_XML), ("extra.xml", BULK_XML)), "exactly one member"),
        (archive(("fulldump@119-73.xml", b"<act id='1'><num>1</num></act>")), "lacks the search-key attribute"),
        (archive(("fulldump@119-73.xml", b"<act id='a' search-key='1'></act>")), "lacks a num element"),
        (archive(("fulldump@119-73.xml", b"<other></other>")), "bytes after the last act element"),
        (archive(("fulldump@119-73.xml", b"   ")), "states no act"),
        (BULK_XML, "local file header"),
    ],
)
def test_table3_bulk_refusals(body, message):
    with pytest.raises(UsCodeSourceError, match=message):
        read_table3_bulk_archive(body)


def test_table3_bulk_member_bound_is_checked_before_the_member_is_read():
    with pytest.raises(UsCodeSourceError, match="max_member_bytes"):
        read_table3_bulk_archive(BULK_ZIP, max_member_bytes=len(BULK_XML) - 1)
