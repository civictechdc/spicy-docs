"""GAO refusals carry exact bounded target bytes without becoming valid pages."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import cast

import pytest

from spicy_docs.sources.gao import native as gao
from spicy_docs.sources.refusals import RefusedResponse, attach_refused_response
from spicy_docs.sources.zyte import ZyteHttpResponse, ZyteTransportError
from tests.test_gao_product_pages_source_native import PRODUCT_ID, PRODUCT_URL, _capture, _html


def _diagnostic(error: Exception) -> RefusedResponse:
    diagnostic = getattr(error, "refused_response", None)
    assert isinstance(diagnostic, RefusedResponse)
    return diagnostic


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_capture(_html(canonical_url="https://www.gao.gov/products/other")), "canonical URL"),
        (_capture(_html(topics=())), "topic anchor"),
        (_capture(_html(topics=(("information-security", "<b>Nested</b>"),))), "nested markup"),
        (_capture(b"\xff\xfe"), "valid UTF-8"),
        (_capture(b""), "empty"),
        (replace(_capture(), status_code=403), "target status"),
        (replace(_capture(), content_type="application/pdf"), "Content-Type"),
    ],
)
def test_refused_response_preserves_exact_body_and_source_error(response: ZyteHttpResponse, message: str) -> None:
    pages = gao.iter_gao_product_pages(lambda _url: response, query_scope={"productIds": [PRODUCT_ID]})
    with pytest.raises(gao.GaoProductSourceError, match=message) as caught:
        next(pages)

    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == PRODUCT_URL
    assert diagnostic.stage == "source-validation"
    assert diagnostic.response_bytes == response.body
    assert diagnostic.observed_byte_size == len(response.body)
    assert diagnostic.unavailable_reason is None
    assert diagnostic.media_type == (
        "application/octet-stream" if response.content_type == "application/pdf" else "text/html"
    )
    assert list(pages) == []


def test_duplicate_empty_topic_field_refuses_even_with_one_topic_anchor() -> None:
    # Synthetic drift: the original topic remains, but the publisher field is
    # declared a second time without an anchor. Counting anchors alone misses it.
    body = _html().replace(b"</body>", b'<div class="views-field-field-topic"></div></body>')
    pages = gao.iter_gao_product_pages(lambda _url: _capture(body), query_scope={"productIds": [PRODUCT_ID]})

    with pytest.raises(
        gao.GaoProductSourceError, match="exactly one publisher topic field with one topic anchor"
    ) as caught:
        next(pages)

    diagnostic = _diagnostic(caught.value)
    assert diagnostic.stage == "source-validation"
    assert diagnostic.request_key == PRODUCT_URL
    assert diagnostic.response_bytes == body
    assert diagnostic.observed_byte_size == len(body)
    assert list(pages) == []


def test_identity_refusal_does_not_export_untrusted_response_urls() -> None:
    untrusted_url = "https://www.gao.gov/products/other?api_key=never-record-this"
    response = replace(_capture(), requested_url=untrusted_url, resolved_url=untrusted_url)
    with pytest.raises(gao.GaoProductSourceError, match="requested URL") as caught:
        next(gao.iter_gao_product_pages(lambda _url: response, query_scope={"productIds": [PRODUCT_ID]}))

    assert _diagnostic(caught.value).request_key == PRODUCT_URL
    assert "never-record-this" not in str(asdict(_diagnostic(caught.value)))
    assert "never-record-this" not in str(caught.value)


def test_refused_body_can_reproduce_markup_failure_offline() -> None:
    body = _html(topics=(("information-security", "<b>Nested</b>"),))
    with pytest.raises(gao.GaoProductSourceError) as captured:
        next(gao.iter_gao_product_pages(lambda _url: _capture(body), query_scope={"productIds": [PRODUCT_ID]}))

    diagnostic = _diagnostic(captured.value)
    assert diagnostic.response_bytes == body
    assert diagnostic.response_bytes is not None
    # Re-run the source's existing field check with retained target bytes only;
    # no fetch or forgiving parser is needed to reproduce the original refusal.
    with pytest.raises(gao.GaoProductSourceError) as replayed:
        gao._publisher_fields(diagnostic.response_bytes, expected_url=diagnostic.request_key)
    assert str(replayed.value) == str(captured.value)


def test_per_response_bound_retains_no_truncated_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _html()
    monkeypatch.setattr(gao, "MAX_PAGE_BYTES", len(body) - 1)
    with pytest.raises(gao.GaoProductSourceError, match="byte bound") as caught:
        next(gao.iter_gao_product_pages(lambda _url: _capture(body), query_scope={"productIds": [PRODUCT_ID]}))

    diagnostic = _diagnostic(caught.value)
    assert diagnostic.response_bytes is None
    assert diagnostic.observed_byte_size == len(body)
    assert diagnostic.unavailable_reason == "response-byte-limit"
    assert diagnostic.media_type == "application/octet-stream"


@pytest.mark.parametrize("wrong_identity", [False, True])
def test_total_bound_also_applies_when_identity_validation_fails_first(
    monkeypatch: pytest.MonkeyPatch, wrong_identity: bool
) -> None:
    second_id = "gao-26-107694"
    second_url = gao.gao_product_url(second_id)
    first_body = _html()
    second_body = _html(canonical_url=second_url)
    monkeypatch.setattr(gao, "MAX_TOTAL_HTML_BYTES", len(first_body) + len(second_body) - 1)
    captures = iter(
        [
            _capture(first_body),
            ZyteHttpResponse(second_url, PRODUCT_URL if wrong_identity else second_url, 200, "text/html", second_body),
        ]
    )
    pages = gao.iter_gao_product_pages(lambda _url: next(captures), query_scope={"productIds": [PRODUCT_ID, second_id]})
    assert next(pages).request_key == PRODUCT_URL
    expected = "resolved URL" if wrong_identity else "total HTML byte bound"
    with pytest.raises(gao.GaoProductSourceError, match=expected) as caught:
        next(pages)

    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == second_url
    assert diagnostic.response_bytes is None
    assert diagnostic.observed_byte_size == len(second_body)
    assert diagnostic.unavailable_reason == "acquisition-byte-limit"
    assert list(pages) == []


def test_transport_refusal_preserves_the_original_exception_and_marks_body_unavailable() -> None:
    original = ZyteTransportError("Zyte acquisition failed with HTTP 401")

    def fetch(_url: str) -> ZyteHttpResponse:
        raise original

    with pytest.raises(ZyteTransportError) as caught:
        next(gao.iter_gao_product_pages(fetch, query_scope={"productIds": [PRODUCT_ID]}))

    assert caught.value is original
    assert str(caught.value) == "Zyte acquisition failed with HTTP 401"
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == PRODUCT_URL
    assert diagnostic.stage == "transport"
    assert diagnostic.response_bytes is None
    assert diagnostic.observed_byte_size is None
    assert diagnostic.unavailable_reason == "transport-unavailable"


def test_unsupported_fetch_result_has_no_diagnostic_body() -> None:
    with pytest.raises(gao.GaoProductSourceError, match="unsupported response") as caught:
        next(
            gao.iter_gao_product_pages(
                cast(gao.GaoProductFetch, lambda _url: object()), query_scope={"productIds": [PRODUCT_ID]}
            )
        )

    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == PRODUCT_URL
    assert diagnostic.response_bytes is None
    assert diagnostic.observed_byte_size is None
    assert diagnostic.unavailable_reason == "unsupported-response"


def test_nonbyte_target_body_is_unavailable_instead_of_coerced() -> None:
    response = replace(_capture(), body=cast(bytes, "not exact bytes"))
    with pytest.raises(gao.GaoProductSourceError, match="byte bound or is empty") as caught:
        next(gao.iter_gao_product_pages(lambda _url: response, query_scope={"productIds": [PRODUCT_ID]}))
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.response_bytes is None
    assert diagnostic.observed_byte_size is None
    assert diagnostic.unavailable_reason == "unsupported-response"


def test_transport_origin_context_survives_the_source_handler() -> None:
    original = ZyteTransportError("Zyte target response contains a transport credential")
    context = RefusedResponse(
        request_key=PRODUCT_URL,
        stage="transport",
        response_bytes=None,
        media_type="application/octet-stream",
        unavailable_reason="credential-suppressed",
    )
    attach_refused_response(original, context)

    def fetch(_url: str) -> ZyteHttpResponse:
        raise original

    with pytest.raises(ZyteTransportError) as caught:
        next(gao.iter_gao_product_pages(fetch, query_scope={"productIds": [PRODUCT_ID]}))
    assert caught.value is original
    assert _diagnostic(caught.value) is context
