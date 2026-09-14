"""Unified Agenda editions prove themselves from every record, not from their file name."""

from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.unified_agenda import (
    MAX_EDITION_BYTES,
    UnifiedAgendaAcquirer,
    UnifiedAgendaBudget,
    UnifiedAgendaEdition,
    UnifiedAgendaSourceError,
    UnifiedAgendaUnavailableError,
    unified_agenda_xml_locator,
    validate_unified_agenda_xml,
)
from spicy_docs.transport import retry

FIXTURE = (Path(__file__).parent / "fixtures" / "unified_agenda" / "reginfo-rin-data-202510.xml").read_bytes()
EDITION = UnifiedAgendaEdition("202510")
BUDGET = UnifiedAgendaBudget(3, 4 * 1024 * 1024, 7, 0)
MINIMAL = (
    b'<REGINFO_RIN_DATA xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" RUN_DATE="2026-07-03-04:00"'
    b' xsi:noNamespaceSchemaLocation="https://www.reginfo.gov/public/xml/REGINFO_XML_Ver10262011.xsd">'
    b"<RIN_INFO><RIN>0503-AA90</RIN><PUBLICATION><PUBLICATION_ID>202510</PUBLICATION_ID></PUBLICATION>"
    b"<RULE_TITLE>A</RULE_TITLE></RIN_INFO>"
    b"<RIN_INFO><RIN>0503-AA80</RIN><PUBLICATION><PUBLICATION_ID>202510</PUBLICATION_ID></PUBLICATION></RIN_INFO>"
    b"</REGINFO_RIN_DATA>"
)


def validate(body=FIXTURE, *, edition=EDITION, final_url=None, **kwargs):
    return validate_unified_agenda_xml(
        body, edition=edition, final_url=final_url or unified_agenda_xml_locator(edition), **kwargs
    )


def response(body=FIXTURE, status=200, *, content_type="application/xml"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


class Transport(httpx.MockTransport):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


@pytest.mark.parametrize("stem", ["199510", "200404", "202510", "2012"])
def test_editions_follow_the_series_and_the_legacy_file_states_fall_2012(stem):
    edition = UnifiedAgendaEdition(stem)
    assert edition.file_name == f"REGINFO_RIN_DATA_{stem}.xml"
    assert edition.publication_id == ("201210" if stem == "2012" else stem)
    assert unified_agenda_xml_locator(edition) == (
        f"https://www.reginfo.gov/public/do/XMLViewFileAction?f=REGINFO_RIN_DATA_{stem}.xml"
    )


@pytest.mark.parametrize("stem", ["199410", "202505", "2025", "20251", "202510.xml", 202510, ""])
def test_invalid_edition_stems_refuse(stem):
    with pytest.raises(UnifiedAgendaSourceError):
        UnifiedAgendaEdition(stem)
    with pytest.raises(UnifiedAgendaSourceError):
        unified_agenda_xml_locator(stem)


def test_pinned_edition_yields_root_identity_and_record_rins():
    result = validate()
    assert (result.file_stem, result.publication_id) == ("202510", "202510")
    assert result.run_date == "2026-07-03-04:00"
    assert result.schema_location == "https://www.reginfo.gov/public/xml/REGINFO_XML_Ver10262011.xsd"
    assert result.record_count == 2 and result.rins == ("0503-AA90", "0503-AA80")


def test_html_inside_cdata_abstracts_is_text_not_a_declaration():
    assert b"<!DOCTYPE html>" in FIXTURE
    assert validate().record_count == 2


@pytest.mark.parametrize(
    "body,message",
    [
        (
            MINIMAL.replace(b"<PUBLICATION_ID>202510</PUBLICATION_ID>", b"<PUBLICATION_ID>202504</PUBLICATION_ID>", 1),
            "another edition",
        ),
        (MINIMAL.replace(b"<RIN>0503-AA80</RIN>", b""), "exactly one RIN"),
        (MINIMAL.replace(b"<RIN>0503-AA80</RIN>", b"<RIN>0503-AA80</RIN><RIN>0503-AA81</RIN>"), "exactly one RIN"),
        (MINIMAL.replace(b"<RIN>0503-AA80</RIN>", b"<RIN> </RIN>"), "exactly one RIN"),
        (MINIMAL.replace(b"<RIN>0503-AA80</RIN>", b"<RIN>0503-AA90</RIN>"), "repeats a RIN"),
        (
            MINIMAL.replace(b"<PUBLICATION><PUBLICATION_ID>202510</PUBLICATION_ID></PUBLICATION>", b"", 1),
            "another edition",
        ),
        (MINIMAL.replace(b"<REGINFO_RIN_DATA", b"<REGINFO").replace(b"</REGINFO_RIN_DATA>", b"</REGINFO>"), "root"),
        (MINIMAL.replace(b"<RULE_TITLE>A</RULE_TITLE>", b"<REGINFO_RIN_DATA/>"), "nested"),
        (b'<REGINFO_RIN_DATA RUN_DATE="2026-07-03-04:00"></REGINFO_RIN_DATA>', "no RIN_INFO"),
        (b"<!DOCTYPE REGINFO_RIN_DATA [<!ENTITY x 'y'>]>" + MINIMAL, "DOCTYPE"),
        (MINIMAL[:-10], "malformed"),
        (b"<html><body>Service Unavailable</body></html>", "root"),
        (MINIMAL.replace(b"<RIN>0503-AA80</RIN>", b"<RIN>" + b"x" * 5000 + b"</RIN>"), "4,096"),
        (b"", "nonempty"),
    ],
)
def test_record_and_document_refusals(body, message):
    with pytest.raises(UnifiedAgendaSourceError, match=message):
        validate(body)


def test_the_two_2004_editions_with_a_control_byte_are_refused_as_malformed():
    damaged = MINIMAL.replace(b"<RULE_TITLE>A</RULE_TITLE>", b"<RULE_TITLE>Department\x19s rule</RULE_TITLE>")
    with pytest.raises(UnifiedAgendaSourceError, match="malformed"):
        validate(damaged)


def test_response_url_and_byte_bounds_are_explicit():
    with pytest.raises(UnifiedAgendaSourceError, match="URL"):
        validate(final_url=unified_agenda_xml_locator(UnifiedAgendaEdition("202504")))
    with pytest.raises(UnifiedAgendaSourceError, match="max_bytes"):
        validate(max_bytes=len(FIXTURE) - 1)
    for bound in (0, True, MAX_EDITION_BYTES + 1):
        with pytest.raises(UnifiedAgendaSourceError):
            validate(max_bytes=bound)


def test_acquirer_captures_exact_edition_bytes_keyless():
    transport = Transport(response())
    with UnifiedAgendaAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_edition(EDITION, max_bytes=len(FIXTURE))
    assert result.capture.body == FIXTURE and result.metadata.record_count == 2
    assert result.capture.requested_url == unified_agenda_xml_locator(EDITION)
    assert result.budget.max_bytes == len(FIXTURE) and result.request_count == 1
    assert "x-api-key" not in transport.calls[0].headers


@pytest.mark.parametrize(
    "answer,error",
    [
        (response(b"<html>listing page</html>", content_type="text/html"), UnifiedAgendaSourceError),
        (response(b"<html>listing page</html>"), UnifiedAgendaSourceError),
        (response(MINIMAL.replace(b"202510", b"202504")), UnifiedAgendaSourceError),
        (response(b"gone", 404), UnifiedAgendaUnavailableError),
    ],
)
def test_wrong_shape_or_unavailable_edition_never_succeeds(answer, error):
    transport = Transport(answer)
    with UnifiedAgendaAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(error) as raised:
        source.acquire_edition(EDITION)
    assert raised.value.refused_response.response_bytes is not None
    assert raised.value.unified_agenda_acquisition["fileStem"] == "202510"


def test_budget_and_client_configuration_are_explicit():
    for fields in ({"max_requests": 0}, {"max_bytes": MAX_EDITION_BYTES + 1}, {"timeout_seconds": 0}):
        with pytest.raises(ValueError):
            UnifiedAgendaBudget(
                **{
                    "max_requests": 3,
                    "max_bytes": 4096,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        UnifiedAgendaAcquirer(budget=(3, 4096, 7, 0), transport=Transport())
    with UnifiedAgendaAcquirer(budget=BUDGET, transport=Transport()) as source, pytest.raises(ValueError):
        source.acquire_edition(EDITION, max_bytes=0)
