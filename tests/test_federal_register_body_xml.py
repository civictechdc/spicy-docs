"""Authored XML fixtures isolate body identity checks from live availability."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from spicy_docs.sources.federal_register.body_sources import FederalRegisterBodySourceError
from spicy_docs.sources.federal_register.body_xml import (
    PublisherXmlIdentity,
    publisher_xml_locator,
    validate_publisher_xml,
)

_DOCUMENT_NUMBER = "2026-18670"
_PUBLICATION_DATE = "2026-09-11"
_URL = "https://www.federalregister.gov/documents/full_text/xml/2026/09/11/2026-18670.xml"
_MARKER = b"<FRDOC>[FR Doc. 2026-18670 Filed 9-10-26; 8:45 am]</FRDOC>"
_BODY = b"<RULE><P>Authored example.</P>" + _MARKER + b"</RULE>"
_SPLIT_MARKER = b"<FRDOC>[FR Doc. 2026-18670 </FRDOC>"
_FILED = b"<FILED>Filed 9-10-26; 11:15 am]</FILED>"


def _validate(body: bytes, **changes: object) -> PublisherXmlIdentity:
    """Validate an authored XML body under the fixture identity."""
    arguments: dict[str, object] = {
        "source_document_number": _DOCUMENT_NUMBER,
        "publication_date": _PUBLICATION_DATE,
        "final_url": _URL,
        "max_bytes": 4096,
    }
    arguments.update(changes)
    return validate_publisher_xml(body, **arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("document_type", ["RULE", "PRORULE", "NOTICE", "PRESDOCU"])
def test_supported_xml_roots_prove_exact_document_identity(document_type: str) -> None:
    """Supported XML roots prove exact document identity and marker fields."""
    body = f"<{document_type}>".encode() + _MARKER + f"</{document_type}>".encode()

    assert asdict(_validate(body)) == {
        "source_document_number": _DOCUMENT_NUMBER,
        "marker_document_number": _DOCUMENT_NUMBER,
        "publication_date": _PUBLICATION_DATE,
        "document_type": document_type,
        "match_kind": "publisher-document-number",
    }


def test_presidential_marker_pairs_with_following_filed_sibling() -> None:
    """A presidential marker pairs with the following FILED sibling while the filing date stays literal."""
    body = b"<PRESDOCU><EXECORD>" + _SPLIT_MARKER + b"\n  " + _FILED + b"</EXECORD></PRESDOCU>"

    identity = _validate(body)

    assert identity.marker_document_number == _DOCUMENT_NUMBER
    # The URL says September 11; the separate September 10 filing date stays literal.
    assert identity.publication_date == "2026-09-11"
    assert identity.document_type == "PRESDOCU"


@pytest.mark.parametrize(
    "body",
    [
        b"<PRESDOCU><EXECORD>" + _SPLIT_MARKER + b"</EXECORD></PRESDOCU>",
        b"<RULE>" + _SPLIT_MARKER + _FILED + b"</RULE>",
        b"<PRESDOCU>" + _FILED + _SPLIT_MARKER + b"</PRESDOCU>",
        b"<PRESDOCU>" + _SPLIT_MARKER + b"<P>Other content</P>" + _FILED + b"</PRESDOCU>",
        b"<PRESDOCU>" + _SPLIT_MARKER + b"Other text" + _FILED + b"</PRESDOCU>",
        b"<PRESDOCU><EXECORD>" + _SPLIT_MARKER + b"</EXECORD><OTHER>" + _FILED + b"</OTHER></PRESDOCU>",
        b"<PRESDOCU>" + _SPLIT_MARKER + b"<FILED>Filed 9-10-26</FILED></PRESDOCU>",
        b"<PRESDOCU>" + _SPLIT_MARKER + b"<FILED>Unrelated text]</FILED></PRESDOCU>",
        b"<PRESDOCU>" + _SPLIT_MARKER + b"<FILED/></PRESDOCU>",
        b"<PRESDOCU>" + _SPLIT_MARKER + b'<FILED xmlns="urn:other">Filed 9-10-26]</FILED></PRESDOCU>',
    ],
)
def test_incomplete_markers_require_the_presidential_filed_pair(body: bytes) -> None:
    """An incomplete presidential marker requires the paired FILED sibling."""
    with pytest.raises(FederalRegisterBodySourceError, match="paired FILED"):
        _validate(body)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"", "empty"),
        (b"<html><body>Access denied</body></html>", "root"),
        (b"<ROOT>" + _MARKER + b"</ROOT>", "root"),
        (b'<RULE xmlns="urn:other">' + _MARKER + b"</RULE>", "root"),
        (b'<x:RULE xmlns:x="urn:other">' + _MARKER + b"</x:RULE>", "root"),
        (b"<RULE><NOTICE>" + _MARKER + b"</NOTICE></RULE>", "nests document roots"),
        (b"<RULE><P>[FR Doc. 2026-18670]</P></RULE>", "no native FRDOC"),
        (b'<RULE><FRDOC xmlns="urn:other">[FR Doc. 2026-18670]</FRDOC></RULE>', "no native FRDOC"),
        (b"<RULE>" + _MARKER + _MARKER + b"</RULE>", "more than one"),
        (b"<RULE><FRDOC><FRDOC>[FR Doc. 2026-18670]</FRDOC></FRDOC></RULE>", "leaf"),
        (b"<RULE><FRDOC>[FR Doc. <E>2026-18670</E>]</FRDOC></RULE>", "leaf"),
        (b"<PRESDOCU>" + _SPLIT_MARKER + b"<FILED>Filed <E>9-10-26</E>]</FILED></PRESDOCU>", "leaf"),
        (b"<RULE><FRDOC/></RULE>", "marker is malformed"),
        (b"<RULE><FRDOC>2026-18670</FRDOC></RULE>", "marker is malformed"),
        (b"<RULE><FRDOC>Prefix [FR Doc. 2026-18670]</FRDOC></RULE>", "marker is malformed"),
        (b"<RULE><FRDOC>[FR Doc. 2026-18670] suffix</FRDOC></RULE>", "marker is malformed"),
        (b"<RULE>" + _MARKER.replace(b"2026-18670", b"2026-18671") + b"</RULE>", "number differs"),
        (b"<RULE>" + _MARKER.replace(b"2026-18670", b"2026-186700") + b"</RULE>", "number differs"),
        (b"<RULE>" + _MARKER, "malformed"),
        (b"<RULE>" + _MARKER + b"</RULE>trailing garbage", "malformed"),
        (b"<RULE>&undefined;" + _MARKER + b"</RULE>", "malformed"),
    ],
)
def test_xml_success_shape_and_identity_refusals(body: bytes, message: str) -> None:
    """XML success-shape and identity refusals name the failed check."""
    with pytest.raises(FederalRegisterBodySourceError, match=message):
        _validate(body)


@pytest.mark.parametrize(
    "declaration",
    [
        b"<!DOCTYPE RULE>",
        b'<!DOCTYPE RULE SYSTEM "https://example.test/body.dtd">',
        b'<!DOCTYPE RULE [<!ENTITY substitute "2026-18670">]>',
        b'<!DOCTYPE RULE [<!ENTITY substitute SYSTEM "file:///tmp/private">]>',
        b'<!DOCTYPE RULE [<!ENTITY % external SYSTEM "https://example.test/body.dtd"> %external;]>',
    ],
)
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_dtd_and_entity_declarations_are_refused_before_expansion(declaration: bytes, encoding: str) -> None:
    """DTD and entity declarations are refused before expansion."""
    body = (declaration + _BODY).decode().encode(encoding)

    with pytest.raises(FederalRegisterBodySourceError, match="DTD and entity"):
        _validate(body)


def test_a_complete_marker_does_not_require_unrelated_filed_content() -> None:
    """A complete marker needs no unrelated FILED content."""
    body = b"<NOTICE>" + _MARKER + b"<FILED><P>Unrelated source content</P></FILED></NOTICE>"

    assert _validate(body).marker_document_number == _DOCUMENT_NUMBER


def test_xml_character_references_do_not_require_entity_declarations() -> None:
    """XML character references need no entity declarations and the bytes stay exact."""
    body = _BODY.replace(b"Authored example.", b"Literal &amp; &#xA7; example.")
    retained = body

    assert _validate(body, max_bytes=len(body)).marker_document_number == _DOCUMENT_NUMBER
    assert body is retained


def test_split_source_identity_is_not_aliased_to_a_printed_base() -> None:
    """A split source identity is not aliased to a printed base number."""
    source_number = _DOCUMENT_NUMBER + "-2"

    with pytest.raises(FederalRegisterBodySourceError, match="number differs"):
        _validate(
            _BODY,
            source_document_number=source_number,
            final_url=publisher_xml_locator(source_number, _PUBLICATION_DATE),
        )


@pytest.mark.parametrize(
    "url",
    [
        _URL.replace("https://", "http://"),
        _URL.replace("www.federalregister.gov", "example.test"),
        _URL.replace("www.federalregister.gov", "key@www.federalregister.gov"),
        _URL.replace("/xml/", "/html/"),
        _URL.replace("/2026/09/11/", "/2026/09/10/"),
        _URL.replace("2026-18670.xml", "2026-18671.xml"),
        _URL + "?download=1",
        _URL + "#fragment",
    ],
)
def test_final_url_must_bind_the_requested_date_and_number(url: str) -> None:
    """The final URL must bind the requested date and number."""
    with pytest.raises(FederalRegisterBodySourceError, match="final URL"):
        _validate(_BODY, final_url=url)


def test_locator_uses_exact_canonical_source_values() -> None:
    """The locator uses exact canonical source values."""
    assert publisher_xml_locator(_DOCUMENT_NUMBER, _PUBLICATION_DATE) == _URL


@pytest.mark.parametrize(
    ("number", "publication_date", "message"),
    [
        ("../escape", _PUBLICATION_DATE, "document_number"),
        ("2026-18670?key=private", _PUBLICATION_DATE, "document_number"),
        ("", _PUBLICATION_DATE, "document_number"),
        (42, _PUBLICATION_DATE, "document_number"),
        (_DOCUMENT_NUMBER, "2026-9-11", "publication_date"),
        (_DOCUMENT_NUMBER, "20260911", "publication_date"),
        (_DOCUMENT_NUMBER, "2026-02-30", "publication_date"),
        (_DOCUMENT_NUMBER, None, "publication_date"),
    ],
)
def test_invalid_source_values_are_refused(number: object, publication_date: object, message: str) -> None:
    """Invalid source values are refused."""
    with pytest.raises(FederalRegisterBodySourceError, match=message):
        publisher_xml_locator(number, publication_date)  # type: ignore[arg-type]
    with pytest.raises(FederalRegisterBodySourceError, match=message):
        _validate(_BODY, source_document_number=number, publication_date=publication_date)


@pytest.mark.parametrize("max_bytes", [0, -1, True, 1.5, "4096", None])
def test_byte_bound_must_be_a_positive_integer(max_bytes: object) -> None:
    """The byte bound must be a positive integer."""
    with pytest.raises(FederalRegisterBodySourceError, match="positive integer"):
        _validate(_BODY, max_bytes=max_bytes)


def test_body_must_fit_the_byte_bound_and_remain_exact_bytes() -> None:
    """The body must fit the byte bound and be exact bytes, not text."""
    with pytest.raises(FederalRegisterBodySourceError, match="exceeds"):
        _validate(_BODY, max_bytes=len(_BODY) - 1)
    with pytest.raises(FederalRegisterBodySourceError, match="exact bytes"):
        _validate(bytearray(_BODY))  # type: ignore[arg-type]
