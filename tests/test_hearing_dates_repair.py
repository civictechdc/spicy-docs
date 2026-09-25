"""Native date conservation and bounded historical package grammar."""

import json
import re
from pathlib import Path

import pytest

from spicy_docs.interpretation.hearing_bill_links import cover_links
from spicy_docs.schemas.hearing_bill_link_tables import shape_hearing_bill_link
from spicy_docs.sources.govinfo.bodies import (
    PUBLISHER_PLACEHOLDER,
    GovInfoBodySourceError,
    package_mods_locator,
    parse_package_id,
    publisher_body_status,
    validate_package_mods,
)

BOTH = "CHRG-118hhrg52385"
FIXTURES = Path(__file__).parent / "fixtures/hearing_bill_links"


def test_compiled_dates_preserve_cover_without_bill_date_product():
    package = "CHRG-117shrg56721"
    raw = (Path(__file__).parent / "fixtures/govinfo_compiled_hearing/CHRG-117shrg56721.mods.xml").read_bytes()
    mods = validate_package_mods(raw, package=package, final_url=package_mods_locator(package), max_bytes=1_000_000)
    assert len(mods.held_dates) == 11 and mods.held_date is None
    links = cover_links(mods)
    assert [link.bill_id for link in links] == ["117-s-2792"]
    row = shape_hearing_bill_link(links[0])
    assert row["held_date"] is None and json.loads(row["held_dates_json"]) == list(mods.held_dates)


@pytest.mark.parametrize(
    "dates,scalar",
    [
        ([], None),
        (["2023-05-23"], "2023-05-23"),
        (["2023-05-23", "2023-05-23"], "2023-05-23"),
        (["2023-05-23", "2023-05-24"], None),
    ],
)
def test_zero_single_repeated_and_distinct_native_dates(dates, scalar):
    raw = (FIXTURES / f"mods-{BOTH}.excerpt.xml").read_text()
    raw = re.sub(r"<heldDate>.*?</heldDate>", "".join(f"<heldDate>{d}</heldDate>" for d in dates), raw)
    mods = validate_package_mods(raw.encode(), package=BOTH, final_url=package_mods_locator(BOTH), max_bytes=1_000_000)
    assert mods.held_dates == tuple(dates) and mods.held_date == scalar


@pytest.mark.parametrize("package", ["CHRG-79jhrg79716p11", "CHRG-79jhrg79716p19"])
def test_only_evidenced_historical_parts(package):
    parsed = parse_package_id(package)
    assert parsed.package_id == package and parsed.congress == 79 and parsed.document_type == "jhrg"
    assert parsed.number == "79716" and parsed.volume == package[-3:] and parsed.issue_suffix is None
    assert parse_package_id("CHRG-79jhrg79716").volume is None


@pytest.mark.parametrize(
    "package",
    [
        "CHRG-79jhrg79716p12",
        "CHRG-79jhrg79716p1",
        "CHRG-79hhrg79716p11",
        "CHRG-179jhrg79716p11",
        "CHRG-118hhrg56198p11",
        "CHRG-79jhrg79716p11evil",
        "CRPT-79jhrg79716p11",
    ],
)
def test_unmeasured_suffixes_stay_refused(package):
    with pytest.raises(GovInfoBodySourceError):
        parse_package_id(package)


def test_placeholder_signal_does_not_claim_graphics_mean_missing_text():
    assert publisher_body_status(PUBLISHER_PLACEHOLDER, rendition="htm") == "publisher_placeholder"
    assert publisher_body_status(PUBLISHER_PLACEHOLDER, rendition="pdf") == "publisher_placeholder"
    assert publisher_body_status("[GRAPHIC NOT AVAILABLE IN TIFF FORMAT]", rendition="htm") == "not_flagged"
    assert publisher_body_status("Extracted pages", rendition="pdf") == "pdf_extracted"


@pytest.mark.parametrize("package", ["CHRG-79jhrg79716p11", "CHRG-79jhrg79716p19"])
def test_historical_part_native_summary_and_mods_must_agree(package):
    from spicy_docs.sources.govinfo.bodies import validate_package_summary

    fixture = Path(__file__).parent / "fixtures/govinfo_compiled_hearing"
    summary = (fixture / f"{package}.summary.json").read_bytes()
    mods = (fixture / f"{package}.mods.xml").read_bytes()
    stated = validate_package_summary(
        summary, package=package, final_url=f"https://api.govinfo.gov/packages/{package}/summary", max_bytes=1_000_000
    )
    native = validate_package_mods(mods, package=package, final_url=package_mods_locator(package), max_bytes=1_000_000)
    assert stated.identity == native.identity and native.offered_formats == ("pdf",)
    other = package.replace("p11", "p19") if package.endswith("p11") else package.replace("p19", "p11")
    with pytest.raises(GovInfoBodySourceError):
        validate_package_mods(mods, package=other, final_url=package_mods_locator(other), max_bytes=1_000_000)
