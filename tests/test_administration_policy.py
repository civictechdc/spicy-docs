"""Policy records retain unknowns and source associations through offline/live boundaries."""

import json
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from spicy_docs.sources.administration_policy import (
    MAX_METADATA_BYTES,
    MAX_PDF_BYTES,
    AdministrationPolicyAcquirer,
    AdministrationPolicyError,
    AdministrationPolicyRefused,
    AdministrationPolicyUnavailable,
    PolicyBudget,
    metadata_url,
    parse_policy_metadata,
)

PIN = "2bdff048a85b1febd3c7fa85ab2b86426d2ef4fc"
FIXTURES = Path(__file__).parent / "fixtures" / "administration_policy"


def parse(body: bytes, administration: str = "47-Trump"):
    return parse_policy_metadata(body, commit=PIN, administration=administration)


def test_pinned_real_archive_excerpts_preserve_each_complete_record():
    import yaml

    for path in FIXTURES.glob("*.yaml"):
        raw = path.read_bytes()
        expected = yaml.safe_load(raw)
        actual = parse(raw, path.stem)
        assert [json.loads(r.raw_json) for r in actual.records] == expected
        assert [r.source_record_index for r in actual.records] == list(range(len(expected)))
        for record, row in zip(actual.records, expected, strict=True):
            assert record.bill_ids == tuple(f"{bill}-{row['congress']}" for bill in row["bills"])
            assert record.date_issued_status == "valid"
            if "file" in row:
                assert unquote(record.archived_pdf_url).endswith("/archive/" + row["file"])
            else:
                assert record.archived_pdf_url is None


def test_no_bill_multibill_and_rescission_records_survive():
    files = {p.stem: parse(p.read_bytes(), p.stem) for p in FIXTURES.glob("*.yaml")}
    assert any(r.bill_ids == () for r in files["40-Reagan"].records)
    assert any(len(r.bill_ids) > 1 for r in files["44-Obama"].records)
    assert any(json.loads(r.raw_json).get("rescinded") is True for r in files["46-Biden"].records)


def test_repeated_statements_and_unknown_fields_keep_distinct_source_identity():
    source = json.loads(parse((FIXTURES / "47-Trump.yaml").read_bytes()).records[0].raw_json)
    source["unrecognized"] = {"reason": None, "tags": ["new"]}
    result = parse(json.dumps([source, source]).encode())
    assert len(result.records) == 2
    assert result.records[0].bill_ids == result.records[1].bill_ids
    assert result.records[0].source_id != result.records[1].source_id
    assert json.loads(result.records[0].raw_json)["unrecognized"] == source["unrecognized"]


@pytest.mark.parametrize(
    "filename",
    [
        "../x.pdf",
        "statements/47-Trump/../x.pdf",
        "statements/46-Biden/118/x.pdf",
        "statements/47-Trump/119/x.pdf?key=value",
        "statements/47-Trump/119/%2e%2e.pdf",
    ],
)
def test_archive_file_cannot_leave_pinned_administration(filename):
    source = json.loads(parse((FIXTURES / "47-Trump.yaml").read_bytes()).records[0].raw_json)
    source["file"] = filename
    with pytest.raises(AdministrationPolicyError, match="inside the selected administration"):
        parse(json.dumps([source]).encode())


@pytest.mark.parametrize(
    "patch",
    [
        {"congress": True},
        {"bills": ["hr0"]},
        {"bills": None},
        {"rescinded": "true"},
        {"document_title": ""},
        {"file": None},
    ],
)
def test_malformed_row_refuses_whole_file(patch):
    source = json.loads(parse((FIXTURES / "47-Trump.yaml").read_bytes()).records[0].raw_json)
    changed = source | patch
    with pytest.raises(AdministrationPolicyError, match="record 1"):
        parse(json.dumps([source, changed]).encode())


def test_unusual_date_is_retained_with_status():
    source = json.loads(parse((FIXTURES / "47-Trump.yaml").read_bytes()).records[0].raw_json)
    source["date_issued"] = "2026-99-99"
    (record,) = parse(json.dumps([source]).encode()).records
    assert record.date_issued == "2026-99-99"
    assert record.date_issued_status == "invalid"


def test_metadata_requires_pinned_selection_and_bounded_bytes():
    with pytest.raises(AdministrationPolicyError, match="commit"):
        metadata_url("main", "47-Trump")
    with pytest.raises(AdministrationPolicyError, match="administration"):
        metadata_url(PIN, "../47-Trump")
    with pytest.raises(AdministrationPolicyError, match="byte bound"):
        parse_policy_metadata(b"[]\n", commit=PIN, administration="47-Trump", max_bytes=1)
    assert parse(b"[]").records == ()
    with pytest.raises(AdministrationPolicyError, match="YAML list"):
        parse(b"<html>Temporarily unavailable</html>")


def test_acquirer_captures_metadata_and_literal_pdf_independently():
    raw = (FIXTURES / "47-Trump.yaml").read_bytes()
    calls = []
    pdf = b"%PDF-1.7\nfixture\n%%EOF\n"

    def serve(request):
        calls.append(str(request.url))
        return httpx.Response(
            200,
            stream=httpx.ByteStream(pdf if request.url.path.endswith(".pdf") else raw),
            headers={"content-type": "application/pdf" if request.url.path.endswith(".pdf") else "text/plain"},
        )

    with AdministrationPolicyAcquirer(
        budget=PolicyBudget(min_request_interval_seconds=0), transport=httpx.MockTransport(serve)
    ) as source:
        result = source.acquire_metadata(commit=PIN, administration="47-Trump")
        capture = source.acquire_pdf(result.file, record_index=0)
    assert result.capture.body == raw
    assert result.capture.sha256 == result.file.input_sha256
    assert capture.body == pdf
    assert calls == [metadata_url(PIN, "47-Trump"), result.file.records[0].archived_pdf_url]


@pytest.mark.parametrize(
    "status,body,media,error_type",
    [
        (404, b"missing", "text/plain", AdministrationPolicyUnavailable),
        (200, b"<html>challenge</html>", "text/plain", AdministrationPolicyError),
        (200, b"[]", "text/html", AdministrationPolicyError),
    ],
)
def test_acquisition_failure_keeps_response_evidence(status, body, media, error_type):
    with (
        AdministrationPolicyAcquirer(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": media})
            )
        ) as source,
        pytest.raises(error_type) as raised,
    ):
        source.acquire_metadata(commit=PIN, administration="47-Trump")
    assert raised.value.capture.body == body


def test_pdf_selection_does_not_fall_back_to_external_page():
    metadata = parse((FIXTURES / "40-Reagan.yaml").read_bytes(), "40-Reagan")
    with AdministrationPolicyAcquirer(
        transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP"))
    ) as source:
        with pytest.raises(AdministrationPolicyError, match="external page"):
            source.acquire_pdf(metadata, record_index=0)
        with pytest.raises(AdministrationPolicyError, match="record_index"):
            source.acquire_pdf(metadata, record_index=-1)


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("operation", ["metadata", "pdf"])
def test_keyless_refusal_uses_source_error_and_preserves_bytes_and_context(status, operation):
    """Both selected routes retain challenge evidence without calling it a credential failure."""
    body = b"archive access refused"
    metadata = parse((FIXTURES / "47-Trump.yaml").read_bytes())
    with (
        AdministrationPolicyAcquirer(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": "text/plain"})
            )
        ) as source,
        pytest.raises(AdministrationPolicyRefused, match="refused access") as raised,
    ):
        if operation == "metadata":
            source.acquire_metadata(commit=PIN, administration="47-Trump")
        else:
            source.acquire_pdf(metadata, record_index=0)
    assert raised.value.refused_response.response_bytes == body
    assert raised.value.refused_response.unavailable_reason == "access-refused"
    assert raised.value.administration_policy_acquisition["operation"] == operation
    assert raised.value.administration_policy_acquisition["requestCount"] == 1


def test_unknown_nested_key_refuses_before_raw_json_can_drop_a_value():
    """YAML 0xA and string 10 must never become duplicate JSON keys in a retained record."""
    import yaml

    original = yaml.safe_load((FIXTURES / "47-Trump.yaml").read_bytes())[0]
    raw = (
        yaml.safe_dump([original], sort_keys=False) + "  unknown:\n    0xA: numeric key\n    '10': string key\n"
    ).encode()
    with pytest.raises(AdministrationPolicyError, match="string mapping keys"):
        parse(raw)


@pytest.mark.parametrize("body", [b"<html>Denied</html>", b"%PDF-1.7\ntruncated"])
def test_pdf_format_refusal_keeps_exact_capture(body):
    """A successful HTTP code cannot turn a challenge or truncated PDF into a document."""
    metadata = parse((FIXTURES / "47-Trump.yaml").read_bytes())
    with (
        AdministrationPolicyAcquirer(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, stream=httpx.ByteStream(body), headers={"content-type": "application/pdf"}
                )
            )
        ) as source,
        pytest.raises(AdministrationPolicyError) as raised,
    ):
        source.acquire_pdf(metadata, record_index=0)
    assert raised.value.capture.body == body
    assert raised.value.refused_response.response_bytes == body
    assert raised.value.administration_policy_acquisition["operation"] == "pdf"


@pytest.mark.parametrize("operation", ["metadata", "pdf"])
def test_redirect_cannot_replace_the_selected_commit(operation):
    """The bounded transport refuses redirects before requesting a moving branch."""
    metadata = parse((FIXTURES / "47-Trump.yaml").read_bytes())
    body = b"redirect to moving branch"
    calls = []

    def serve(request):
        calls.append(str(request.url))
        return httpx.Response(
            302,
            stream=httpx.ByteStream(body),
            headers={"location": str(request.url).replace(PIN, "main"), "content-type": "text/plain"},
        )

    with (
        AdministrationPolicyAcquirer(
            budget=PolicyBudget(min_request_interval_seconds=0), transport=httpx.MockTransport(serve)
        ) as source,
        pytest.raises(AdministrationPolicyError, match="HTTP 302") as raised,
    ):
        if operation == "metadata":
            source.acquire_metadata(commit=PIN, administration="47-Trump")
        else:
            source.acquire_pdf(metadata, record_index=0)
    assert raised.value.capture.body == body
    assert len(calls) == 1 and PIN in calls[0]
    assert raised.value.refused_response.response_bytes == body


@pytest.mark.parametrize(
    ("field", "cap"), [("max_metadata_bytes", MAX_METADATA_BYTES), ("max_pdf_bytes", MAX_PDF_BYTES)]
)
def test_budget_cannot_raise_a_per_file_cap(field, cap):
    with pytest.raises(ValueError, match=field):
        PolicyBudget(**{field: cap + 1})


def test_a_narrowed_budget_refuses_a_larger_capture():
    raw = (FIXTURES / "47-Trump.yaml").read_bytes()
    with (
        AdministrationPolicyAcquirer(
            budget=PolicyBudget(max_metadata_bytes=len(raw) - 1),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, stream=httpx.ByteStream(raw), headers={"content-type": "text/plain"})
            ),
        ) as source,
        pytest.raises(AdministrationPolicyError),
    ):
        source.acquire_metadata(commit=PIN, administration="47-Trump")
