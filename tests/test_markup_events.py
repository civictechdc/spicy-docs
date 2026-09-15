"""Source text, byte positions, callbacks, and refusal bounds are independent of layout."""

from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest

from spicy_docs.reading.markup import MarkupRead, MarkupReadError, read_html_events, read_xml_events
from spicy_docs.reading.xml import scan_xml

FIXTURES = Path(__file__).parent / "fixtures"


def text_events(result):
    return [event for event in result.events if event.kind == "text"]


def check_spans(body, result):
    for event in text_events(result):
        assert 0 <= event.byte_start < event.byte_end <= len(body)
        assert event.is_literal is (body[event.byte_start : event.byte_end] == event.text.encode("utf-8"))
    return "".join(event.text for event in text_events(result))


@pytest.mark.parametrize("filename", ["cfr/annual-title1-vol1.xml", "uscode/title-05-s423.xml"])
def test_retained_xml_matches_independent_tree_text_counts_and_root(filename):
    body = (FIXTURES / filename).read_bytes()
    expected = ElementTree.fromstring(body)
    actual = read_xml_events(body)
    assert actual.root_expanded_name == expected.tag
    assert actual.element_count == sum(1 for _ in expected.iter())
    assert check_spans(body, actual) == "".join(expected.itertext())


def test_xml_literal_qnames_namespace_declarations_and_unknown_attributes_survive():
    body = b'<x:r xmlns:x="urn:outer" SOURCE="HED" x:extra="A &amp; B"><x:unknown xmlns:x="urn:inner" z=""/></x:r>'
    result = read_xml_events(body)
    assert result.root_name == "x:r"
    assert result.root_expanded_name == "{urn:outer}r"
    starts = [event for event in result.events if event.kind == "start"]
    assert starts[0].attributes == (("SOURCE", "HED"), ("x:extra", "A & B"))
    assert starts[0].namespace_declarations == (("x", "urn:outer"),)
    assert starts[1].name == "x:unknown"
    assert starts[1].attributes == (("z", ""),)
    assert starts[1].namespace_declarations == (("x", "urn:inner"),)
    assert [event.kind for event in result.events] == ["start", "start", "end", "end"]


@pytest.mark.parametrize("reader", [read_xml_events, read_html_events])
def test_comments_and_processing_instructions_do_not_extend_preceding_text_spans(reader):
    body = b"<p>A<!--x-->B<?q z?>C</p>"
    result = reader(body)
    assert check_spans(body, result) == "ABC"
    assert [body[event.byte_start : event.byte_end] for event in text_events(result)] == [b"A", b"B", b"C"]
    assert [event.kind for event in result.events] == ["start", "text", "comment", "text", "pi", "text", "end"]


def test_cdata_delimiters_are_not_claimed_by_text_runs():
    body = b"<p>A<![CDATA[B]]>C</p>"
    result = read_xml_events(body)
    assert check_spans(body, result) == "ABC"
    assert [(event.byte_start, event.byte_end) for event in text_events(result)] == [(3, 4), (13, 14), (17, 18)]


def test_xml_entities_and_line_endings_keep_their_complete_source_spelling():
    body = b"<p>A\r\nB &amp; caf&#233;.</p>"
    result = read_xml_events(body)
    assert check_spans(body, result) == "A\nB & café."
    changed = [event for event in text_events(result) if not event.is_literal]
    assert [(event.text, body[event.byte_start : event.byte_end]) for event in changed] == [
        ("\n", b"\r\n"),
        ("&", b"&amp;"),
        ("é", b"&#233;"),
    ]


@pytest.mark.parametrize(
    "encoding,declared", [("utf-16", "UTF-16"), ("utf-16-be", "UTF-16"), ("iso-8859-1", "ISO-8859-1")]
)
def test_xml_declared_encoding_preserves_original_byte_coordinates(encoding, declared):
    body = f'<?xml version="1.0" encoding="{declared}"?><r>café &#8364;.</r>'.encode(encoding)
    result = read_xml_events(body)
    assert check_spans(body, result) == "café €."
    assert result.events[0].attributes == (("version", "1.0"), ("encoding", declared))
    assert any(not event.is_literal for event in text_events(result))


@pytest.mark.parametrize("chunk", [1, 7, 65536])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "iso-8859-1"])
def test_xml_events_are_independent_of_feed_and_character_callback_boundaries(monkeypatch, chunk, encoding):
    body = (
        f'<?xml version="1.0" encoding="{encoding}"?><r>' + "a" * 65530 + "é\nplain &amp; \r\n<![CDATA[café]]>end</r>"
    ).encode(encoding)
    expected = read_xml_events(body)

    def feed(body, parser, **kwargs):
        for start in range(0, len(body), chunk):
            parser.Parse(body[start : start + chunk], False)
        parser.Parse(b"", True)

    monkeypatch.setattr("spicy_docs.reading.markup._feed_xml", feed)
    assert read_xml_events(body) == expected


@pytest.mark.parametrize("chunk", [1, 7, 65536])
@pytest.mark.parametrize("ending", ["tail</p>", "&notit &amp"])
def test_html_events_are_independent_of_feed_boundaries(monkeypatch, chunk, ending):
    body = ("<p>" + "a" * 65530 + "é\n&amp; &#233;<!--comment-->" + ending).encode()
    expected = read_html_events(body)
    monkeypatch.setattr("spicy_docs.reading.markup._HTML_FEED_CHARACTERS", chunk)
    assert read_html_events(body) == expected


class _HtmlReference(HTMLParser):
    """Independent standard-library text/count behavior used by the prior receivers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.count = 0

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        self.count += 1

    def handle_startendtag(self, tag, attrs):
        self.count += 1


@pytest.mark.parametrize(
    "body",
    [
        b"<head><title>A &amp; B</title></head><p>Text</p><script>x=&copy;</script>",
        b'<p>A<br>B</p><custom data-x="one" data-x="two" disabled/>',
        b"<p>&notit; &not; &notit &copy= &copy &bad; &amp &amp; &#65 &#65; &#x41; &#0; &#x1;</p>",
        b"<p>incomplete &foo &amp",
        b"plain & trailing",
        b"<p><!-- unclosed",
        b"<!DOCTYPE html><P>A</unexpected>B<?pi data?><p>C",
        "<p>café\fnext\u2028same line\nsecond — dash</p>".encode(),
    ],
)
def test_html_text_and_counts_match_the_existing_parser_without_policy(body):
    reference = _HtmlReference()
    reference.feed(body.decode())
    reference.close()
    result = read_html_events(body)
    assert check_spans(body, result) == "".join(reference.text)
    assert result.element_count == reference.count


def test_retained_html_excerpt_matches_independent_text_and_counts():
    body = (FIXTURES / "cfr_metadata/subject-index-45.html").read_bytes()
    reference = _HtmlReference()
    reference.feed(body.decode())
    reference.close()
    result = read_html_events(body)
    assert check_spans(body, result) == "".join(reference.text)
    assert result.element_count == reference.count


def test_duplicate_html_attributes_null_values_and_empty_decoded_entities_survive():
    body = b'<custom a="one" a="two" disabled>&#x1;</custom>'
    result = read_html_events(body)
    assert result.events[0].attributes == (("a", "one"), ("a", "two"), ("disabled", None))
    event = text_events(result)[0]
    assert event.text == ""
    assert body[event.byte_start : event.byte_end] == b"&#x1;"


@pytest.mark.parametrize(
    "body",
    [
        b"<r><x></r>",
        b"<x:r/>",
        b'<r a="1" a="2"/>',
        b"<r>&unknown;</r>",
        b'<!DOCTYPE r SYSTEM "file:///never-read"><r/>',
        b'<!DOCTYPE r [<!ENTITY x "substitute">]><r>&x;</r>',
        b'<?xml version="1.0" encoding="unknown"?><r/>',
    ],
)
def test_namespace_invalid_malformed_and_unsafe_xml_refuses(body):
    with pytest.raises(MarkupReadError):
        read_xml_events(body)


def test_real_bill_external_doctype_requires_explicit_inert_permission():
    body = (FIXTURES / "govinfo_bills/text-119hr6028ih.xml").read_bytes()
    with pytest.raises(MarkupReadError, match="DOCTYPE"):
        read_xml_events(body)
    result = read_xml_events(body, allow_external_doctype=True)
    assert check_spans(body, result) == "".join(ElementTree.fromstring(body).itertext())
    declaration = next(event for event in result.events if event.name == "doctype")
    assert declaration.attributes == (
        ("name", "bill"),
        ("system", "bill.dtd"),
        ("public", "-//US Congress//DTDs/bill.dtd//EN"),
    )


def test_inert_permission_does_not_load_a_dtd_or_enable_declared_entities(tmp_path):
    path = tmp_path / "test.dtd"
    path.write_text('<!ENTITY outside "changed">')
    declaration = f'<!DOCTYPE r SYSTEM "{path.as_uri()}">'.encode()
    body = declaration + b"<r>source</r>"
    assert check_spans(body, read_xml_events(body, allow_external_doctype=True)) == "source"
    with pytest.raises(MarkupReadError):
        read_xml_events(declaration + b"<r>&outside;</r>", allow_external_doctype=True)
    with pytest.raises(MarkupReadError, match="DOCTYPE"):
        read_xml_events(b'<!DOCTYPE r [<!ENTITY x "changed">]><r>&x;</r>', allow_external_doctype=True)


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_inert_doctype_permission_must_be_explicit_boolean(value):
    with pytest.raises(MarkupReadError, match="allow_external_doctype"):
        read_xml_events(b"<r/>", allow_external_doctype=value)


@pytest.mark.parametrize("reader", [read_xml_events, read_html_events])
@pytest.mark.parametrize("setting", ["max_bytes", "max_events", "max_depth"])
@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_bound_configuration_refuses(reader, setting, limit):
    with pytest.raises(MarkupReadError, match=setting):
        reader(b"<r/>", **{setting: limit})


def test_empty_html_is_an_empty_observation_but_empty_xml_refuses():
    assert read_html_events(b"") == MarkupRead((), 0, None, None)
    with pytest.raises(MarkupReadError, match="nonempty bytes"):
        read_xml_events(b"")


@pytest.mark.parametrize("setting", ["max_bytes", "max_events", "max_depth"])
@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_empty_html_still_validates_all_bounds(setting, limit):
    with pytest.raises(MarkupReadError, match=setting):
        read_html_events(b"", **{setting: limit})


@pytest.mark.parametrize("reader", [read_xml_events, read_html_events])
def test_input_event_and_depth_limits_refuse_before_success(reader):
    body = b"<r>" * 4 + b"text" + b"</r>" * 4
    with pytest.raises(MarkupReadError, match="max_bytes"):
        reader(body, max_bytes=len(body) - 1)
    with pytest.raises(MarkupReadError, match="max_events"):
        reader(body, max_events=4)
    with pytest.raises(MarkupReadError, match="nesting depth"):
        reader(body, max_depth=3)
    with pytest.raises(MarkupReadError, match="bytes"):
        reader("<r/>")


def test_html_invalid_utf8_refuses():
    with pytest.raises(MarkupReadError, match="UTF-8"):
        read_html_events(b"<p>\xff</p>")


def test_existing_xml_scan_still_preserves_callback_exception_identity():
    marker = RuntimeError("caller failure")

    def fail(*args):
        raise marker

    with pytest.raises(RuntimeError) as failure:
        scan_xml(
            b"<r>text</r>",
            start=lambda *args: None,
            end=lambda *args: None,
            data=fail,
            max_bytes=1024,
            error_type=ValueError,
            label="callback",
        )
    assert failure.value is marker
