"""Shared XML safety rules survive chunk boundaries and publisher namespaces.

Entities, malformed documents, unpermitted external DOCTYPEs, nesting depth, and byte bounds all refuse; encoding
declarations and BOMs are respected."""

import pytest

from spicy_docs.reading.xml import parse_xml, scan_xml


@pytest.mark.parametrize("fragment,split,decoded", [(b"&amp;", 2, "&"), ("é".encode(), 1, "é")])
def test_streaming_scan_preserves_unicode_entities_and_namespaced_attributes(fragment, split, decoded):
    prefix = b'<r xmlns:p="urn:publisher" p:key="value"><p:body>'
    padding = 65536 - len(prefix) - split
    body = prefix + b"a" * padding + fragment + b"</p:body></r>"
    assert body[65536 - split : 65536] == fragment[:split]
    assert body[65536 : 65536 + len(fragment) - split] == fragment[split:]
    starts, ends, text = [], [], []
    scan_xml(
        body,
        start=lambda tag, attrs: starts.append((tag, attrs)),
        end=ends.append,
        data=text.append,
        max_bytes=len(body),
        error_type=ValueError,
        label="test XML",
    )
    assert starts == [("r", {"{urn:publisher}key": "value"}), ("{urn:publisher}body", {})]
    assert ends == ["{urn:publisher}body", "r"]
    assert "".join(text) == "a" * padding + decoded


def test_xml_encoding_declaration_and_bom_are_respected():
    body = '<?xml version="1.0" encoding="UTF-16"?><r>café &amp; source</r>'.encode("utf-16")
    assert parse_xml(body, max_bytes=1024, error_type=ValueError, label="test XML").text == "café & source"


@pytest.mark.parametrize(
    "body",
    [
        b'<!DOCTYPE r [<!ENTITY x "altered">]><r>&x;</r>',
        b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///not-a-source">]><r>&x;</r>',
        b"<r>&undeclared;</r>",
        b"<r><x></r>",
    ],
)
def test_declared_entities_and_malformed_documents_refuse(body):
    with pytest.raises(ValueError):
        parse_xml(body, max_bytes=1024, error_type=ValueError, label="test XML", allow_external_doctype=True)


def test_external_doctype_is_inert_and_requires_explicit_source_permission():
    body = b'<!DOCTYPE r SYSTEM "https://example.invalid/do-not-load.dtd"><r>source</r>'
    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_xml(body, max_bytes=1024, error_type=ValueError, label="test XML")
    assert (
        parse_xml(body, max_bytes=1024, error_type=ValueError, label="test XML", allow_external_doctype=True).text
        == "source"
    )


def test_nesting_and_byte_bounds_refuse_before_returning_a_tree():
    body = b"<r>" * 4 + b"</r>" * 4
    with pytest.raises(ValueError, match="nesting depth"):
        parse_xml(body, max_bytes=1024, error_type=ValueError, label="test XML", max_depth=3)
    with pytest.raises(ValueError, match="within max_bytes"):
        parse_xml(body, max_bytes=len(body) - 1, error_type=ValueError, label="test XML")
