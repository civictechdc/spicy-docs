"""Publisher flags classify editions; body dates cannot establish cover-only status."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.cfr import (
    AnnualCfrSelection,
    CfrEditionType,
    CfrSourceError,
    annual_cfr_edition_locator,
    parse_annual_cfr_edition,
)
from spicy_docs.sources.cfr.acquisition import CfrAcquirer, CfrAcquisitionBudget, CfrSourceUnavailableError

FIXTURES = Path(__file__).parent / "fixtures" / "cfr"
SELECTION = AnnualCfrSelection(2025, 1, 1)
BODY = (FIXTURES / "annual-title1-edition.xml").read_bytes()
URL = "https://www.govinfo.gov/metadata/pkg/CFR-2025-title1-vol1/mods.xml"


def parse(body=BODY, selection=SELECTION, **kwargs):
    return parse_annual_cfr_edition(
        body, selection=selection, final_url=annual_cfr_edition_locator(selection), **kwargs
    )


def test_explicit_cover_only_type_keeps_publication_and_original_dates_separate():
    result = parse()
    assert (result.year, result.title, result.volume) == (2025, 1, 1)
    assert result.date_issued == "2025-01-01"
    assert result.original_date_issued == "2023-01-01"
    assert result.is_cover_only is True
    assert result.edition_type is CfrEditionType.COVER_ONLY
    assert result.is_current_edition is True and result.is_fallback_title is False
    assert result.edition_id == "CFR-title1-vol1"
    assert result.title_text == "General Provisions"


def test_false_flag_is_not_a_claim_that_the_text_was_revised():
    result = parse((FIXTURES / "annual-title1-2023-edition.xml").read_bytes(), AnnualCfrSelection(2023, 1, 1))
    assert result.is_cover_only is False
    assert result.edition_type is CfrEditionType.NOT_COVER_ONLY
    assert result.date_issued == result.original_date_issued == "2023-01-01"
    assert replace(result, is_cover_only=None).edition_type is CfrEditionType.UNKNOWN


def test_missing_flag_is_unknown_even_when_dates_differ():
    result = parse(BODY.replace(b"<isCoverOnly>true</isCoverOnly>", b""))
    assert result.is_cover_only is None and result.edition_type is CfrEditionType.UNKNOWN
    assert result.date_issued != result.original_date_issued


@pytest.mark.parametrize("value,expected", [(b"1", True), (b"0", False), (b" false ", False)])
def test_xml_boolean_spellings(value, expected):
    assert (
        parse(
            BODY.replace(b"<isCoverOnly>true</isCoverOnly>", b"<isCoverOnly>" + value + b"</isCoverOnly>")
        ).is_cover_only
        is expected
    )


@pytest.mark.parametrize("field", ["isCoverOnly", "isCurrentEdition", "isFallbackTitle"])
@pytest.mark.parametrize("value", ["", "yes", "TRUE", "2"])
def test_present_invalid_or_empty_flags_refuse(field, value):
    old = f"<{field}>" + ("false" if field == "isFallbackTitle" else "true") + f"</{field}>"
    with pytest.raises(CfrSourceError):
        parse(BODY.replace(old.encode(), f"<{field}>{value}</{field}>".encode()))


@pytest.mark.parametrize("tag", ["isCoverOnly", "dateIssued", "accessId", "titleNumber", "originalDateIssued"])
def test_duplicate_root_identity_and_edition_fields_refuse(tag):
    start = BODY.index(("<" + tag).encode())
    end = BODY.index(("</" + tag + ">").encode(), start) + len(tag) + 3
    duplicate = BODY[start:end]
    with pytest.raises(CfrSourceError, match="repeats"):
        parse(BODY[:end] + duplicate + BODY[end:])


@pytest.mark.parametrize(
    "old,new",
    [
        (b"<collectionCode>CFR", b"<collectionCode>BILLS"),
        (b"<accessId>CFR-2025-title1-vol1", b"<accessId>CFR-2024-title1-vol1"),
        (b"<titleNumber>1", b"<titleNumber>2"),
        (b"<volumeNumber>1", b"<volumeNumber>2"),
        (b"2025-01-01", b"2024-01-01"),
        (b"2023-01-01", b"2023-02-30"),
        (b"<editionId>CFR-title1-vol1", b"<editionId>CFR-title2-vol1"),
    ],
)
def test_contradictory_package_identity_or_invalid_dates_refuse(old, new):
    with pytest.raises(CfrSourceError):
        parse(BODY.replace(old, new))


def test_nested_granule_metadata_cannot_supply_package_fields():
    without_flag = BODY.replace(b"<isCoverOnly>true</isCoverOnly>", b"")
    nested = b"<relatedItem><extension><isCoverOnly>true</isCoverOnly><titleNumber>99</titleNumber></extension></relatedItem>"
    result = parse(without_flag.replace(b"</mods>", nested + b"</mods>"))
    assert result.edition_type is CfrEditionType.UNKNOWN and result.title == 1
    without_package = BODY.replace(b"<accessId>CFR-2025-title1-vol1</accessId>", b"")
    nested = b"<relatedItem><extension><accessId>CFR-2025-title1-vol1</accessId></extension></relatedItem>"
    with pytest.raises(CfrSourceError):
        parse(without_package.replace(b"</mods>", nested + b"</mods>"))


def test_metadata_namespace_scalar_fields_xml_safety_and_bounds():
    for invalid in [
        BODY.replace(b"http://www.loc.gov/mods/v3", b"https://invalid.test/mods"),
        BODY.replace(b"<isCoverOnly>true", b"<isCoverOnly><x>true</x>"),
        b'<!DOCTYPE mods [<!ENTITY x "true">]>' + BODY[BODY.index(b"<mods") :],
        BODY[:-8],
        b"<html>no</html>",
    ]:
        with pytest.raises(CfrSourceError):
            parse(invalid)
    assert parse(max_bytes=len(BODY)).edition_type is CfrEditionType.COVER_ONLY
    with pytest.raises(CfrSourceError):
        parse(max_bytes=len(BODY) - 1)


def test_section_and_wrong_final_url_refuse_before_interpretation():
    with pytest.raises(CfrSourceError):
        annual_cfr_edition_locator(replace(SELECTION, section="1.1"))
    with pytest.raises(CfrSourceError):
        parse_annual_cfr_edition(BODY, selection=SELECTION, final_url=URL + "?other=1")


def test_missing_optional_dates_and_flags_remain_absent():
    body = BODY
    for tag, value in [
        ("originalDateIssued", "2023-01-01"),
        ("isCurrentEdition", "true"),
        ("isFallbackTitle", "false"),
    ]:
        body = body.replace(f"<{tag}>{value}</{tag}>".encode(), b"")
    result = parse(body)
    assert result.original_date_issued is result.is_current_edition is result.is_fallback_title is None
    assert result.edition_type is CfrEditionType.COVER_ONLY


def test_acquisition_retains_one_exact_metadata_response_and_respects_override():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(BODY), headers={"content-type": "application/xml"})

    budget = CfrAcquisitionBudget(1, 8192, 10, 0)
    with CfrAcquirer(budget=budget, transport=httpx.MockTransport(handle)) as client:
        result = client.acquire_annual_edition(SELECTION, max_bytes=len(BODY))
    assert result.capture.body == BODY
    assert result.capture.requested_url == URL
    assert result.request_count == len(calls) == 1
    assert result.edition.edition_type is CfrEditionType.COVER_ONLY
    assert result.budget.max_bytes == len(BODY)
    assert calls[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "status,body", [(200, BODY.replace(b"<isCoverOnly>true", b"<isCoverOnly>bad")), (404, b"missing")]
)
def test_refused_or_missing_metadata_keeps_evidence(status, body):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status, stream=httpx.ByteStream(body), headers={"content-type": "application/xml"}
        )
    )
    with (
        CfrAcquirer(budget=CfrAcquisitionBudget(1, 8192, 10, 0), transport=transport) as client,
        pytest.raises(CfrSourceError) as raised,
    ):
        client.acquire_annual_edition(SELECTION)
    assert raised.value.capture.body == body
    assert raised.value.cfr_acquisition["operation"] == "annual-edition"
    assert raised.value.cfr_acquisition["requestCount"] == 1
    assert isinstance(raised.value, CfrSourceUnavailableError) == (status == 404)
