import pytest
from rulespec_artifacts import LocalBlobSource

from spicy_docs.sources.refusals import RefusedResponse, attach_refused_response, retain_refused_response


@pytest.mark.parametrize("body", [b"", b"<broken>"])
def test_retained_refusal_keeps_empty_bytes_and_safe_context(tmp_path, body):
    error = ValueError("invalid source")
    attach_refused_response(
        error, RefusedResponse("https://example.test?api_key=secret", "source-validation", body, "text/xml")
    )
    result = retain_refused_response(error, store=tmp_path, max_bytes=100)
    assert result["request_key"] == "https://example.test?api_key=<redacted>"
    assert result["media_type"] == "text/xml"
    with LocalBlobSource(tmp_path).open(result["sha256"]) as stream:
        assert stream.read() == body


def test_refusal_credential_echo_is_not_written(tmp_path):
    error = ValueError("invalid source")
    attach_refused_response(
        error, RefusedResponse("safe-request", "source-validation", b"echo supersecret", "text/plain")
    )
    result = retain_refused_response(error, store=tmp_path, max_bytes=100, credential="supersecret")
    assert "sha256" not in result
    assert "credential" in result["unavailable_reason"]
    assert list(tmp_path.iterdir()) == []


def test_no_attached_response_is_distinct_from_unavailable_bytes(tmp_path):
    error = ValueError("transport failed")
    assert retain_refused_response(error, store=tmp_path, max_bytes=100) is None
    attach_refused_response(
        error, RefusedResponse("safe-request", "transport", None, "application/octet-stream", "not captured")
    )
    result = retain_refused_response(error, store=tmp_path, max_bytes=100)
    assert result["unavailable_reason"] == "not captured" and "sha256" not in result
