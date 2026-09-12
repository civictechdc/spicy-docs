"""CFR requests and response checks retain source dates and refuse false identity."""

import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from spicy_docs.sources.cfr import (
    MAX_CFR_BYTES,
    AnnualCfrSelection,
    CfrSourceError,
    EcfrSelection,
    annual_cfr_xml_locator,
    ecfr_bulk_xml_locator,
    ecfr_xml_locator,
    parse_ecfr_titles,
    validate_annual_cfr_xml,
    validate_ecfr_bulk_xml,
    validate_ecfr_xml,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cfr"


def api(body=None, *, part=None, section=None, title=1, date="2026-07-31", **kwargs):
    selection = EcfrSelection(title, date, part=part, section=section)
    name = "ecfr-api-section18-1.xml" if section else "ecfr-api-part18.xml" if part else "ecfr-api-title1.xml"
    return validate_ecfr_xml(
        (FIXTURES / name).read_bytes() if body is None else body,
        selection=selection,
        final_url=ecfr_xml_locator(selection),
        **kwargs,
    )


def annual(body=None, *, section=None, year=2025, title=None, volume=None, **kwargs):
    identity = AnnualCfrSelection(year, title or (30 if section else 1), volume or (3 if section else 1), section)
    name = "annual-title30-vol3-sec716-2.xml" if section else "annual-title1-vol1.xml"
    return validate_annual_cfr_xml(
        (FIXTURES / name).read_bytes() if body is None else body,
        identity=identity,
        final_url=annual_cfr_xml_locator(identity),
        **kwargs,
    )


def bulk(body=None, **kwargs):
    return validate_ecfr_bulk_xml(
        (FIXTURES / "ecfr-bulk-title1.xml").read_bytes() if body is None else body,
        title=1,
        final_url=ecfr_bulk_xml_locator(1),
        **kwargs,
    )


@pytest.mark.parametrize("title", [True, "1", 0, 35, 51, -1])
def test_title_selectors_refuse_invalid_and_reserved(title):
    with pytest.raises(CfrSourceError):
        EcfrSelection(title, "2026-01-01")
    with pytest.raises(CfrSourceError):
        AnnualCfrSelection(2025, title, 1)
    with pytest.raises(CfrSourceError):
        ecfr_bulk_xml_locator(title)


@pytest.mark.parametrize("date", ["2026-1-1", "20260201", "2026-02-30", "2026-01-01?part=1", None])
def test_date_is_a_real_explicit_calendar_date(date):
    with pytest.raises(CfrSourceError):
        EcfrSelection(1, date)


@pytest.mark.parametrize("part,section", [(None, "1.1"), ("../1", None), ("1", "1.1&part=2")])
def test_scope_selectors_refuse_ambiguous_or_injectable_coordinates(part, section):
    with pytest.raises(CfrSourceError):
        EcfrSelection(1, "2026-01-01", part, section)


def test_locators_keep_distinct_publisher_routes_and_allow_real_coordinate_forms():
    assert ecfr_xml_locator(EcfrSelection(5, "2026-01-01", "0", "0.1")).endswith("?part=0&section=0.1")
    assert ecfr_xml_locator(EcfrSelection(26, "2026-01-01", "1", "1.401(k)-1")).endswith("section=1.401%28k%29-1")
    assert ecfr_xml_locator(EcfrSelection(41, "2026-01-01", "102-5", "102-5.1")).endswith("section=102-5.1")
    assert annual_cfr_xml_locator(AnnualCfrSelection(2025, 30, 3, "716.2")) == (
        "https://www.govinfo.gov/content/pkg/CFR-2025-title30-vol3/xml/CFR-2025-title30-vol3-sec716-2.xml"
    )
    with pytest.raises(CfrSourceError, match="unsupported"):
        AnnualCfrSelection(2025, 26, 1, "1.401(k)-1")
    for locator in [ecfr_xml_locator, annual_cfr_xml_locator]:
        with pytest.raises(CfrSourceError):
            locator(SimpleNamespace(title=1, date="2026-01-01", year=2025, volume=1, section=None))


def test_roster_preserves_currency_processing_and_literal_names_without_inferring_reservation():
    original = (FIXTURES / "ecfr-titles.json").read_bytes()
    source = json.loads(original)
    result = parse_ecfr_titles(original)
    assert len(result.titles) == 50 and result.titles[34].reserved
    assert result.date == "2026-08-20" and not result.import_in_progress
    source["meta"]["import_in_progress"] = True
    source["titles"][0].update(name="  Literal—name  ", latest_issue_date=None, processing_in_progress=True)
    result = parse_ecfr_titles(json.dumps(source).encode())
    assert result.titles[0].name == "  Literal—name  "
    assert result.titles[0].latest_issue_date is None and not result.titles[0].reserved
    assert result.titles[0].processing_in_progress is True and result.import_in_progress


@pytest.mark.parametrize("mutation", ["partial", "duplicate", "date", "reserved", "processing", "name", "number"])
def test_roster_refuses_incomplete_or_wrong_success_shapes(mutation):
    source = json.loads((FIXTURES / "ecfr-titles.json").read_bytes())
    if mutation == "partial":
        source["titles"].pop()
    elif mutation == "duplicate":
        source["titles"][-1] = source["titles"][0]
    else:
        field, value = {
            "date": ("latest_issue_date", "2026-02-31"),
            "reserved": ("reserved", 0),
            "processing": ("processing_in_progress", "false"),
            "name": ("name", ""),
            "number": ("number", True),
        }[mutation]
        source["titles"][0][field] = value
    with pytest.raises(CfrSourceError):
        parse_ecfr_titles(json.dumps(source).encode())


@pytest.mark.parametrize("body", [b"", b"<html>Access request</html>", b"{}", b'{"titles":[],"titles":[],"meta":{}}'])
def test_roster_empty_and_error_content_refuses(body):
    with pytest.raises(CfrSourceError):
        parse_ecfr_titles(body)


def test_api_metadata_does_not_invent_title_context_or_equal_amendment_date():
    title = api(date="2026-08-10")
    assert title.title == 1 and title.amendment_dates == ("Dec. 29, 2022(fm)\n", "2022-12-29")
    assert title.stated_date is None and title.identity_basis == ("title:native", "date:request-url")
    part = api(part="18")
    assert part.title is None and part.part == "18" and part.section is None
    section = api(part="18", section="18.1")
    assert section.root_tag == "DIV5" and section.section == "18.1" and "section:native" in section.identity_basis


@pytest.mark.parametrize(
    "old,new",
    [
        (b'TYPE="TITLE"', b'TYPE="PART"'),
        (b'N="1" TYPE="TITLE"', b'N="2" TYPE="TITLE"'),
        ("Title 1—".encode(), "Title 2—".encode()),
    ],
)
def test_api_title_contradictions_refuse(old, new):
    source = (FIXTURES / "ecfr-api-title1.xml").read_bytes()
    assert old in source
    with pytest.raises(CfrSourceError):
        api(source.replace(old, new))


@pytest.mark.parametrize(
    "old,new",
    [
        (b'N="18"', b'N="19"'),
        (b'N="18.1"', b'N="18.2"'),
        (b"title-1/", b"title-2/"),
        (b"_SUBSTITUTE_DATE_", b"2026-07-30"),
        (b"section-18.1", b"section-18.9"),
        (b"section-18.1", b"part-18"),
    ],
)
def test_api_subset_checks_native_and_supplied_hierarchy_identity(old, new):
    source = (FIXTURES / "ecfr-api-section18-1.xml").read_bytes()
    assert old in source
    with pytest.raises(CfrSourceError):
        api(source.replace(old, new), part="18", section="18.1")


def test_api_section_refuses_extra_section_but_part_request_accepts_multiple():
    source = (FIXTURES / "ecfr-api-part18.xml").read_bytes()
    assert api(source, part="18").part == "18"
    with pytest.raises(CfrSourceError):
        api(source, part="18", section="18.1")


def test_bulk_title_uses_header_id_not_volume_and_checks_all_blocks():
    source = (FIXTURES / "ecfr-bulk-title1.xml").read_bytes()
    volume_two = source.replace(b'<DIV1 N="1"', b'<DIV1 N="2"')
    assert bulk(volume_two).title == 1
    root = ET.fromstring(source)
    block = root.find("TEXT/BODY/ECFRBRWS")
    assert block is not None
    encoded = ET.tostring(block, encoding="utf-8")
    two = source.replace(b"</BODY>", encoded + b"</BODY>")
    assert len(bulk(two).amendment_dates) == 2
    wrong_second = encoded.replace("Title 1—".encode(), "Title 2—".encode())
    assert wrong_second != encoded
    with pytest.raises(CfrSourceError, match="title heading"):
        bulk(source.replace(b"</BODY>", wrong_second + b"</BODY>"))
    with pytest.raises(CfrSourceError, match="each bulk"):
        bulk(source.replace(b"</BODY>", b"<ECFRBRWS><DIV1 N='2' TYPE='TITLE'/></ECFRBRWS></BODY>"))


@pytest.mark.parametrize(
    "old,new", [(b"\n1</IDNO>", b"\n2</IDNO>"), (b"Title 1:", b"Title 2:"), ("Title 1—".encode(), "Title 2—".encode())]
)
def test_bulk_header_and_body_title_disagreement_refuses(old, new):
    source = (FIXTURES / "ecfr-bulk-title1.xml").read_bytes()
    assert old in source
    with pytest.raises(CfrSourceError):
        bulk(source.replace(old, new))


def test_annual_requested_edition_and_native_revision_are_separate():
    result = annual()
    assert result.stated_date == "As of January 1, 2023"
    assert result.revision_text == "Revised as of January 1, 2023"
    assert result.title == 1 and result.volume is None
    assert result.identity_basis == ("title:native", "volume:request-url", "edition:request-url")
    assert annual(year=2023).revision_text == result.revision_text
    granule = annual(section="716.2")
    assert (granule.title, granule.volume, granule.section, granule.stated_date) == (30, 3, "716.2", "2025-07-01")


@pytest.mark.parametrize(
    "replacement", [b"date unknown (2023)", b"As of _SUBSTITUTE_DATE_", b"As of February 30, 2023"]
)
def test_printed_revision_text_is_preserved_without_interpreting_ambiguous_dates(replacement):
    source = (FIXTURES / "annual-title1-vol1.xml").read_bytes()
    source = source.replace(b"Revised as of January 1, 2023", replacement).replace(
        b"As of January 1, 2023", replacement
    )
    assert annual(source).revision_text == replacement.decode()


@pytest.mark.parametrize(
    "old,new", [(b"<CFRTITLE>30", b"<CFRTITLE>31"), (b"<VOL>3", b"<VOL>4"), (b"716.2</SECTNO>", b"716.3</SECTNO>")]
)
def test_annual_granule_native_identity_contradictions_refuse(old, new):
    source = (FIXTURES / "annual-title30-vol3-sec716-2.xml").read_bytes()
    assert old in source
    with pytest.raises(CfrSourceError):
        annual(source.replace(old, new), section="716.2")


@pytest.mark.parametrize("reader", [api, annual, bulk])
@pytest.mark.parametrize(
    "body", [b"", b"<html><p>Access request</p></html>", b"<error>Not found</error>", b"<ECFR/>", b"<CFRDOC/>"]
)
def test_error_and_empty_success_shapes_refuse(reader, body):
    with pytest.raises(CfrSourceError):
        reader(body)


def test_response_url_and_xml_safety_are_checked_before_acceptance():
    selection = EcfrSelection(1, "2026-07-31")
    source = (FIXTURES / "ecfr-api-title1.xml").read_bytes()
    with pytest.raises(CfrSourceError, match="URL"):
        validate_ecfr_xml(source, selection=selection, final_url=ecfr_xml_locator(selection) + "&extra=true")
    declaration = b'<!DOCTYPE ECFR [<!ENTITY unsafe "expanded">]>'
    with pytest.raises(CfrSourceError, match="DOCTYPE"):
        api(declaration + source[source.index(b"<ECFR>") :])
    with pytest.raises(CfrSourceError, match="DOCTYPE"):
        api(b'<!DOCTYPE ECFR SYSTEM "file:///tmp/not-to-read.dtd">' + source[source.index(b"<ECFR>") :])
    with pytest.raises(CfrSourceError, match="nesting"):
        api(b"<ECFR>" + b"<x>" * 256 + b"</x>" * 256 + b"</ECFR>")
    with pytest.raises(CfrSourceError, match="max_bytes"):
        api(source, max_bytes=len(source) - 1)
    with pytest.raises(CfrSourceError, match="max_bytes"):
        api(source, max_bytes=MAX_CFR_BYTES + 1)


def test_xml_validation_does_not_build_a_tree(monkeypatch):
    from spicy_docs.sources import xml

    def refuse(*args, **kwargs):
        raise AssertionError("source identity validation must scan, not build a tree")

    monkeypatch.setattr(ET, "fromstring", refuse)
    monkeypatch.setattr(ET, "TreeBuilder", refuse)
    monkeypatch.setattr(xml, "TreeBuilder", refuse)
    api()
    annual()
    bulk()


@pytest.mark.parametrize(
    "content",
    [
        "<GPOTABLE><ROW><ENT>Source table value</ENT></ROW></GPOTABLE>",
        "<GPH><GID>er01ja25.001</GID></GPH>",
    ],
)
def test_table_or_graphic_only_annual_section_has_source_content(content):
    source = ET.fromstring((FIXTURES / "annual-title30-vol3-sec716-2.xml").read_bytes())
    section = source.find("SECTION")
    assert section is not None
    for child in list(section):
        if child.tag != "SECTNO":
            section.remove(child)
    section.append(ET.fromstring(content))
    assert annual(ET.tostring(source), section="716.2").section == "716.2"


def test_ecfr_graphic_reference_is_source_content_without_fetching_the_image():
    source = b'<DIV5 N="18" TYPE="PART"><DIV8 N="18.1" TYPE="SECTION"><img src="/graphics/source.gif"/></DIV8></DIV5>'
    assert api(source, part="18", section="18.1").section == "18.1"


def test_native_part_is_not_inferred_from_section_number():
    source = (FIXTURES / "ecfr-api-title14-numbering.xml").read_bytes()
    assert api(source, title=14).title == 14
    root = ET.fromstring(source)
    part = root.find(".//DIV5")
    assert part is not None and part.get("N") == "241"
    parsed = api(ET.tostring(part), title=14, part="241", section="19-8.1")
    assert parsed.part == "241" and parsed.section == "19-8.1"
    selection = EcfrSelection(14, "2026-08-19", "241", "19-8")
    assert ecfr_xml_locator(selection).endswith("part=241&section=19-8")
    source = (FIXTURES / "annual-title30-vol3-sec716-2.xml").read_bytes()
    assert annual(source.replace(b'HEADING="PART 716"', b'HEADING="PART 715"'), section="716.2").section == "716.2"
