"""Literal USLM observations retain the source, including unfamiliar references."""

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from spicy_docs.sources.uscode import UsCodeSourceError
from spicy_docs.sources.uscode_references import scan_uscode_references

FIXTURES = Path(__file__).parent / "fixtures" / "uscode"


def read(xml, **kwargs):
    references, credits = [], []
    counts = scan_uscode_references(xml, on_reference=references.append, on_source_credit=credits.append, **kwargs)
    return references, credits, counts


def select(root, path):
    positions = [int(p) for p in re.findall(r"/\*\[(\d+)\]", path)]
    assert positions[0] == 1
    assert "".join(f"/*[{p}]" for p in positions) == path
    node = root
    for position in positions[1:]:
        node = list(node)[position - 1]
    return node


def localname(tag):
    return tag.rsplit("}", 1)[-1]


def source(name):
    data = (FIXTURES / name).read_bytes()
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.read("usc01.xml")
    return data


@pytest.mark.parametrize("name", ["xml_usc01@119-103.zip", "usc50A.xml", "title-05-s423.xml"])
def test_every_literal_reference_and_credit_matches_independent_tree(name):
    xml = source(name)
    root = ET.fromstring(xml)
    references, credits, counts = read(xml)
    expected_refs = [e for e in root.iter() if "href" in e.attrib or localname(e.tag) == "ref"]
    expected_credits = [e for e in root.iter() if localname(e.tag) == "sourceCredit"]
    assert counts.elements == sum(1 for _ in root.iter())
    assert counts.references == len(expected_refs) == len(references)
    assert counts.source_credits == len(expected_credits) == len(credits)
    assert [select(root, row.element.source_xpath) for row in references] == expected_refs
    assert [select(root, row.element.source_xpath) for row in credits] == expected_credits
    parents = {child: parent for parent in root.iter() for child in parent}
    for row in [*references, *credits]:
        node = select(root, row.element.source_xpath)
        assert row.element.tag == node.tag
        assert row.element.attributes == node.attrib
        current = node
        for ancestor in reversed(row.ancestors):
            current = parents[current]
            assert select(root, ancestor.source_xpath) is current
            assert ancestor.tag == current.tag and ancestor.attributes == current.attrib
        assert current is root
    assert [row.text for row in credits] == ["".join(e.itertext()) for e in expected_credits]


def test_real_inline_credit_and_xhtml_links_keep_original_namespaces_and_spaces():
    refs, credits, _ = read(source("title-05-s423.xml"))
    assert credits[0].text == "(Pub. L. 117–286, §\u202f3(b), Dec. 27, 2022, 136 Stat. 4255.)"
    link = next(row for row in refs if row.href == "/us/pl/110/409/s4/a/3")
    assert link.element.tag == "{http://www.w3.org/1999/xhtml}a"
    note = next(a for a in reversed(link.ancestors) if localname(a.tag) == "note")
    assert note.attributes["topic"] == "historicalAndRevision"
    assert credits[0].ancestors[-1].attributes["identifier"] == "/us/usc/t5/s423"


def test_unknown_empty_fragment_relative_and_missing_references_are_observations():
    refs, credits, counts = read(
        b'<root href="https://example.test"><ref href="/unfamiliar/value"/>'
        b'<ref href=""/><ref href="#local"/><ref href="relative"/>'
        b'<ref idref="fn-1" class="footnoteRef"/><a href="/us/usc/t5/unknown"/></root>'
    )
    assert [row.href for row in refs] == [
        "https://example.test",
        "/unfamiliar/value",
        "",
        "#local",
        "relative",
        None,
        "/us/usc/t5/unknown",
    ]
    assert refs[5].element.attributes == {"idref": "fn-1", "class": "footnoteRef"}
    assert refs[0].ancestors == ()
    assert counts.references == 7 and credits == []


def test_credits_keep_unknown_empty_unattributed_and_nearest_unidentified_section():
    refs, credits, _ = read(
        '<root><sourceCredit strange="yes"/>\n'
        '<section identifier="/us/usc/t5/s1"><section status="repealed">'
        "<sourceCredit>\n  Unknown <i>credit</i>\t§\u202f4 &amp; 5.\n</sourceCredit>"
        "</section><sourceCredit>outer</sourceCredit></section></root>".encode()
    )
    assert refs == []
    assert [row.text for row in credits] == ["", "\n  Unknown credit\t§\u202f4 & 5.\n", "outer"]
    assert credits[0].element.attributes == {"strange": "yes"}
    assert [localname(a.tag) for a in credits[0].ancestors] == ["root"]
    inner = credits[1].ancestors[-1]
    assert localname(inner.tag) == "section" and inner.attributes == {"status": "repealed"}
    assert credits[1].ancestors[-2].attributes["identifier"] == "/us/usc/t5/s1"
    assert credits[2].ancestors[-1].attributes["identifier"] == "/us/usc/t5/s1"


def test_comments_and_processing_instructions_do_not_shift_element_paths():
    refs, _, _ = read(b'<root><!-- x --><ref href="a"/><?x y?><ref href="a"/></root>')
    assert [r.element.source_xpath for r in refs] == ["/*[1]/*[1]", "/*[1]/*[2]"]


def test_nested_credits_include_descendant_text_and_finish_in_close_order():
    _, credits, _ = read(b"<root><sourceCredit>before<sourceCredit>inside</sourceCredit>after</sourceCredit></root>")
    assert [c.text for c in credits] == ["inside", "beforeinsideafter"]


@pytest.mark.parametrize(
    "xml,match",
    [
        (b"", "nonempty"),
        (b"<root>", "malformed"),
        (b'<!DOCTYPE root SYSTEM "file:///does-not-exist"><root/>', "DOCTYPE"),
        (b'<!DOCTYPE root [<!ENTITY a "secret">]><root>&a;</root>', "DOCTYPE"),
        (b"<root>&unknown;</root>", "malformed"),
    ],
)
def test_invalid_source_refuses(xml, match):
    with pytest.raises(UsCodeSourceError, match=match):
        read(xml)


@pytest.mark.parametrize("argument", ["max_bytes", "max_observations", "max_text_characters", "max_depth"])
@pytest.mark.parametrize("value", [True, 0, -1, "3"])
def test_bounds_require_positive_integers(argument, value):
    with pytest.raises(UsCodeSourceError, match=argument):
        read(b"<root/>", **{argument: value})


def test_byte_depth_observation_and_active_credit_text_limits_refuse():
    for xml, kwargs, match in [
        (b"<root/>", {"max_bytes": 1}, "max_bytes"),
        (b"<root><child/></root>", {"max_depth": 1}, "nesting"),
        (b'<root><ref href="a"/><sourceCredit/></root>', {"max_observations": 1}, "observations"),
        (b"<root><sourceCredit>abcd</sourceCredit></root>", {"max_text_characters": 3}, "text"),
        (
            b"<root><sourceCredit><sourceCredit>abcd</sourceCredit></sourceCredit></root>",
            {"max_text_characters": 6},
            "text",
        ),
    ]:
        with pytest.raises(UsCodeSourceError, match=match):
            read(xml, **kwargs)


def test_text_budget_is_released_after_each_credit_and_unselected_text_is_not_buffered():
    _, credits, _ = read(
        b"<root>unselected<sourceCredit>abcd</sourceCredit><sourceCredit>efgh</sourceCredit></root>",
        max_text_characters=4,
    )
    assert [c.text for c in credits] == ["abcd", "efgh"]
    counts = scan_uscode_references(b"<root><sourceCredit>unselected</sourceCredit></root>", max_text_characters=1)
    assert counts.source_credits == 1


def test_callback_observations_are_provisional_until_a_successful_scan():
    rows = []
    with pytest.raises(UsCodeSourceError, match="malformed"):
        scan_uscode_references(b'<root><ref href="kept-before-failure"/>', on_reference=rows.append)
    assert [row.href for row in rows] == ["kept-before-failure"]


def test_callback_mutation_does_not_change_later_ancestry():
    ancestors = []

    def mutate(row):
        ancestors.append(row.ancestors[-1].attributes.copy())
        row.ancestors[-1].attributes.clear()
        row.element.attributes.clear()

    scan_uscode_references(
        b'<section identifier="source"><ref href="a"/><ref href="b"/></section>', on_reference=mutate
    )
    assert ancestors == [{"identifier": "source"}, {"identifier": "source"}]


@pytest.mark.parametrize("callback", ["on_reference", "on_source_credit"])
def test_callback_errors_keep_their_identity_instead_of_claiming_malformed_xml(callback):
    error = ValueError("output refused this row")

    def refuse(_row):
        raise error

    with pytest.raises(ValueError) as raised:
        scan_uscode_references(
            b'<root><ref href="source"/><sourceCredit>credit</sourceCredit></root>', **{callback: refuse}
        )
    assert raised.value is error
