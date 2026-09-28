"""Shared XML safety rules survive chunk boundaries and publisher namespaces.

Entities, malformed documents, unpermitted external DOCTYPEs, nesting depth, and byte bounds all refuse; encoding
declarations and BOMs are respected."""

import pytest

from spicy_docs.reading.xml import parse_xml, parse_xml_with_spans, scan_xml


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


def test_spans_slice_the_publisher_bytes_across_a_chunk_boundary_and_quoted_brackets():
    """Each chosen element's span is its exact markup: a self-closed one with a ``>`` inside a quoted attribute, and
    one whose end tag straddles the 64 KiB feeding boundary. Elements off the path get no span, even with its tag."""
    head = b'<r><list><item k=">" /><item>'
    tail = b"</item><item>b</item></list><other><item>not chosen</item></other></r>"
    body = head + b"a" * (65536 - len(head) - 3) + tail
    assert body[65533:65540] == b"</item>"  # the second item's end tag spans the first 64 KiB chunk's end
    root, spans = parse_xml_with_spans(
        body, path=("r", "list", "item"), max_bytes=len(body), error_type=ValueError, label="t"
    )
    chosen = root.findall("list/item")
    assert [body[start:end] for start, end in (spans[element] for element in chosen)] == [
        b'<item k=">" />',
        b"<item>" + b"a" * (65536 - len(head) - 3) + b"</item>",
        b"<item>b</item>",
    ]
    assert len(spans) == 3 and root.find("other/item") not in spans


def test_spans_refuse_an_empty_path():
    with pytest.raises(ValueError, match="path"):
        parse_xml_with_spans(b"<r/>", path=(), max_bytes=4, error_type=ValueError, label="t")


def test_a_spanned_tree_is_freed_by_reference_counting_alone():
    """The parser, its handlers and the tree form no cycle once parsing ends, so a caller that drops the tree frees it
    without the cyclic collector; a cycle kept every parsed BILLSTATUS alive until a collection, and cost 25% more
    time over the retained 39,147-document corpus while a caller held its results."""
    import gc
    import weakref

    gc.disable()
    try:
        root, spans = parse_xml_with_spans(
            b"<r><a>x</a></r>", path=("r", "a"), max_bytes=64, error_type=ValueError, label="t"
        )
        alive = weakref.ref(root)
        del root, spans
        assert alive() is None
    finally:
        gc.enable()
