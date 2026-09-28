"""Retained community IG metadata keeps source fields separate from archive paths."""

import hashlib
import json
from pathlib import Path

import pytest

from spicy_docs.sources.agency_reports.inspectors_general import (
    InspectorGeneralReportError,
    parse_inspector_general_report,
)

FIXTURES = Path(__file__).parent / "fixtures/inspectors_general"
PIN = "779b991b33e317eaa118985834618e67e3cc35c2"
URL = (
    f"https://raw.githubusercontent.com/unitedstates/reports/{PIN}/inspectors-general/cia/2007/2004-7601-IG/report.json"
)


def test_real_archive_record_keeps_distinct_years_and_origin():
    """The CIA archive directory says 2007 but its record year is 2016; neither overwrites the other."""
    body = (FIXTURES / "cia-report.json").read_bytes()
    result = parse_inspector_general_report(body, url=URL)
    assert result["record"] == json.loads(body)
    assert result["record"]["year"] == 2016
    assert result["record"]["published_on"] == "2007-07-16"
    assert result["source"]["url"] == URL
    assert result["source"]["sha256"] == "sha256:" + hashlib.sha256(body).hexdigest()
    assert result["assets"] == [{"url": result["record"]["url"], "file_type": "pdf", "source_field": "url"}]
    assert result["record"]["pdf"]["page_count"] == 109


def test_unknown_fields_and_literal_values_survive():
    """A scraper extension remains available, including repeated array observations and nulls."""
    record = json.loads((FIXTURES / "ccr-report.json").read_bytes())
    record["future_extension"] = {"amount": "001.20", "observations": [None, None], "label": " spaced "}
    result = parse_inspector_general_report(json.dumps(record).encode(), url=URL)
    assert result["record"] == record


def test_unreleased_metadata_does_not_invent_a_body():
    """Upstream permits unreleased reports with a landing page and no file URL."""
    record = json.loads((FIXTURES / "ccr-report.json").read_bytes())
    del record["url"]
    del record["file_type"]
    record.update(unreleased=True, landing_url="https://example.gov/reports/withheld")
    result = parse_inspector_general_report(json.dumps(record).encode(), url=URL)
    assert result["assets"] == []
    assert result["links"][-1]["source_field"] == "landing_url"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"[]", "object"),
        (b"{}", "report_id"),
        (b'{"report_id":"A", "report_id":"B"}', "repeats field"),
        (b'{"pdf":{"page_count":1,"page_count":2}}', "repeats field"),
        (b'{"x":NaN}', "unsupported number"),
        (b"<html>Denied</html>", "invalid"),
        (b"\xff", "invalid"),
    ],
)
def test_ambiguous_or_non_report_inputs_refuse(body, reason):
    """Metadata parsing refuses duplicate fields, malformed bytes and foreign success pages."""
    with pytest.raises(InspectorGeneralReportError, match=reason):
        parse_inspector_general_report(body, url=URL)


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"url": None}, "needs a URL"),
        ({"url": "javascript:alert(1)"}, "HTTP URL"),
        ({"url": "https://user:password@example.gov/file.pdf"}, "HTTP URL"),
        ({"year": True}, "integer"),
        ({"unreleased": "true"}, "boolean"),
        ({"file_type": None}, "file_type"),
    ],
)
def test_inconsistent_metadata_refuses(patch, reason):
    """No file is inferred from an invalid or missing source declaration."""
    record = json.loads((FIXTURES / "ccr-report.json").read_bytes())
    record.update(patch)
    with pytest.raises(InspectorGeneralReportError, match=reason):
        parse_inspector_general_report(json.dumps(record).encode(), url=URL)


@pytest.mark.parametrize("url", ["report.json", "ftp://example.gov/report.json", "https://user:pw@example.gov/r.json"])
def test_the_metadata_locator_is_checked_before_the_bytes(url):
    """A bad caller locator is named as such, whatever the body holds."""
    with pytest.raises(InspectorGeneralReportError, match="metadata locator"):
        parse_inspector_general_report(b"<html>Denied</html>", url=url)


def test_byte_bound():
    """Caller bounds limit retained metadata before parsing."""
    with pytest.raises(InspectorGeneralReportError, match="max_bytes"):
        parse_inspector_general_report(b"{}", url=URL, max_bytes=1)


@pytest.mark.parametrize("kwargs", [{"max_bytes": True}, {"max_nodes": 1}, {"max_depth": 1}])
def test_explicit_bounds_refuse(kwargs):
    """Shared JSON bounds cover nested PDF metadata and reject a boolean limit."""
    with pytest.raises(InspectorGeneralReportError, match="max_"):
        parse_inspector_general_report((FIXTURES / "ccr-report.json").read_bytes(), url=URL, **kwargs)


def test_only_retained_bytes_and_finite_numbers():
    """Strings are not acquired bytes; overflowing numeric input cannot enter an unknown field."""
    with pytest.raises(InspectorGeneralReportError, match="bytes"):
        parse_inspector_general_report("{}", url=URL)
    with pytest.raises(InspectorGeneralReportError, match="unsupported number"):
        parse_inspector_general_report(b'{"extra":1e999}', url=URL)
