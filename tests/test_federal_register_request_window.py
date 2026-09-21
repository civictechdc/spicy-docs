"""Current Federal Register requests preserve exact fields and refuse query drift."""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest

from spicy_docs.sources.federal_register.native import (
    FederalRegisterSourceError,
    federal_register_documents_url,
    federal_register_request_window,
)

QUERY_SCOPE = {"publishedFrom": "2026-08-25", "publishedThrough": "2026-08-25"}
EXPECTED_WINDOW = (date(2026, 8, 25), date(2026, 8, 25))
# Independent exact bytes preserve all 23 current fields, their order and encoding.
CURRENT_REQUEST = (
    "https://www.federalregister.gov/api/v1/documents.json?per_page=1000&order=newest"
    "&conditions%5Bpublication_date%5D%5Bgte%5D=2026-08-25"
    "&conditions%5Bpublication_date%5D%5Blte%5D=2026-08-25"
    "&fields%5B%5D=abstract&fields%5B%5D=agencies&fields%5B%5D=agency_names"
    "&fields%5B%5D=body_html_url&fields%5B%5D=cfr_references&fields%5B%5D=comments_close_on"
    "&fields%5B%5D=docket_ids&fields%5B%5D=document_number&fields%5B%5D=effective_on"
    "&fields%5B%5D=end_page&fields%5B%5D=executive_order_number&fields%5B%5D=full_text_xml_url"
    "&fields%5B%5D=html_url"
    "&fields%5B%5D=pdf_url&fields%5B%5D=publication_date&fields%5B%5D=regulation_id_numbers"
    "&fields%5B%5D=signing_date&fields%5B%5D=start_page&fields%5B%5D=subtype"
    "&fields%5B%5D=title&fields%5B%5D=topics&fields%5B%5D=type&fields%5B%5D=volume"
)


def _request(pairs: list[tuple[str, str]]) -> str:
    """Build a request URL over the given window parameters."""
    parts = urlsplit(CURRENT_REQUEST)
    return urlunsplit(parts._replace(query=urlencode(pairs)))


def test_current_request_preserves_exact_bytes_and_round_trips() -> None:
    """The current request preserves exact bytes and round-trips to its window."""
    assert federal_register_documents_url(QUERY_SCOPE) == CURRENT_REQUEST
    assert federal_register_request_window(CURRENT_REQUEST) == EXPECTED_WINDOW


@pytest.mark.parametrize("per_page", [1, 500, 1000])
def test_current_fields_round_trip_with_supported_page_sizes(per_page: int) -> None:
    """Current fields round-trip with each supported page size."""
    request = federal_register_documents_url(QUERY_SCOPE, per_page=per_page)
    assert request == CURRENT_REQUEST.replace("per_page=1000", f"per_page={per_page}")
    assert federal_register_request_window(request) == EXPECTED_WINDOW


@pytest.mark.parametrize("change", ["missing", "added", "previous-field-set"])
def test_changed_document_field_set_is_refused(change: str) -> None:
    """A changed document field set is refused."""
    pairs = parse_qsl(urlsplit(CURRENT_REQUEST).query)
    if change == "missing":
        pairs.remove(("fields[]", "topics"))
    elif change == "previous-field-set":
        pairs.remove(("fields[]", "full_text_xml_url"))
    else:
        pairs.append(("fields[]", "some_future_field"))
    with pytest.raises(FederalRegisterSourceError, match="field set differs from current fields"):
        federal_register_request_window(_request(pairs))


@pytest.mark.parametrize(
    "change",
    ["duplicate-field", "reordered-fields", "reordered-query", "alternate-encoding"],
)
def test_equivalent_but_noncanonical_requests_are_refused(change: str) -> None:
    """Equivalent but noncanonical requests are refused."""
    pairs = parse_qsl(urlsplit(CURRENT_REQUEST).query)
    if change == "duplicate-field":
        pairs.append(("fields[]", "topics"))
    elif change == "reordered-fields":
        pairs[-1], pairs[-2] = pairs[-2], pairs[-1]
    elif change == "reordered-query":
        pairs[0], pairs[1] = pairs[1], pairs[0]
    request = _request(pairs)
    if change == "alternate-encoding":
        request = request.replace("fields%5B%5D", "fields[]")
    with pytest.raises(FederalRegisterSourceError, match="not canonical"):
        federal_register_request_window(request)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("per_page", "0"),
        ("per_page", "1001"),
        ("per_page", "1.5"),
        ("per_page", "0500"),
        ("order", "oldest"),
        ("conditions[publication_date][gte]", "not-a-date"),
        ("conditions[publication_date][gte]", "2026-08-26"),
    ],
)
def test_query_value_drift_is_refused(key: str, value: str) -> None:
    """Query value drift is refused."""
    pairs = [
        (name, value if name == key else existing) for name, existing in parse_qsl(urlsplit(CURRENT_REQUEST).query)
    ]
    with pytest.raises(FederalRegisterSourceError):
        federal_register_request_window(_request(pairs))


@pytest.mark.parametrize("key", ["per_page", "order", "conditions[publication_date][gte]"])
def test_repeated_singleton_query_fields_are_refused(key: str) -> None:
    """Repeated singleton query fields are refused."""
    pairs = parse_qsl(urlsplit(CURRENT_REQUEST).query)
    pairs.append(next(pair for pair in pairs if pair[0] == key))
    with pytest.raises(FederalRegisterSourceError):
        federal_register_request_window(_request(pairs))


@pytest.mark.parametrize("change", ["missing-per-page", "extra-page"])
def test_missing_and_additional_query_fields_are_refused(change: str) -> None:
    """Missing and additional query fields are refused."""
    pairs = parse_qsl(urlsplit(CURRENT_REQUEST).query)
    if change == "missing-per-page":
        pairs = [pair for pair in pairs if pair[0] != "per_page"]
    else:
        pairs.append(("page", "1"))
    with pytest.raises(FederalRegisterSourceError, match="request fields differ"):
        federal_register_request_window(_request(pairs))


@pytest.mark.parametrize(
    "request_url",
    [
        CURRENT_REQUEST.replace("https://", "http://"),
        CURRENT_REQUEST.replace("www.federalregister.gov", "example.test"),
        CURRENT_REQUEST.replace("www.federalregister.gov", "www.federalregister.gov:443"),
        CURRENT_REQUEST.replace("www.federalregister.gov", "user@www.federalregister.gov"),
        CURRENT_REQUEST.replace("documents.json", "documents"),
        CURRENT_REQUEST + "#fragment",
    ],
)
def test_window_request_requires_the_canonical_source_url(request_url: str) -> None:
    """The window request requires the canonical source URL."""
    with pytest.raises(FederalRegisterSourceError, match="URL is invalid"):
        federal_register_request_window(request_url)
