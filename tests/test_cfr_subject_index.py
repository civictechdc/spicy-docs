"""Literal source markup, anomalies and original-byte positions."""

from pathlib import Path

import pytest

from spicy_docs.sources.cfr.models import CfrSourceError
from spicy_docs.sources.cfr.subject_index import read_cfr_subject_index

FIXTURES = Path(__file__).parent / "fixtures" / "cfr_metadata"


def test_retained_malformed_markup_does_not_erase_entries_or_terms() -> None:
    payload = (FIXTURES / "subject-index-45.html").read_bytes()
    result = read_cfr_subject_index(b"<dl>" + payload + b"</dl>")
    assert [(block.tag, block.heading.part if block.heading else None) for block in result.blocks] == [
        ("dt", "2531"),
        ("ddgrant", None),
        ("dd", None),
        ("dd", None),
        ("dt", "2532"),
        ("dd", None),
        ("dd", None),
    ]
    broken = result.blocks[1]
    assert broken.raw_html == b'<ddgrant programs="" programs-social="">'
    assert broken.attributes == (("programs", ""), ("programs-social", ""))
    assert broken.issues == ("unexpected_list_element",)


def test_text_entities_inline_markup_and_byte_spans_remain_distinct() -> None:
    payload = (
        '<p>é</p>\n<dl><dt data-name="é&amp;&#x2603;">40 CFR Part 52_Hé<i>ad</i>&amp; X.</dt><dd>N/A</dd></dl>'.encode()
    )
    result = read_cfr_subject_index(payload)
    heading, term = result.blocks
    assert heading.text == "40 CFR Part 52_Héad& X."
    assert heading.text_fragments == ("40 CFR Part 52_Hé", "ad", "& X.")
    assert heading.attributes == (("data-name", "é&☃"),)
    assert heading.heading is not None
    assert heading.heading.heading == "Hé ad & X."
    assert term.text == "N/A"
    for block in (*result.blocks, *result.metadata):
        start, end = block.byte_span
        assert block.raw_html == payload[start:end]


@pytest.mark.parametrize(
    "entry,title,keyword,part,separator,issue",
    [
        ("2 CFR 401_Requirements.", "2", None, "401", "_", "missing_keyword"),
        ("48 CFR Oart 739_Information technology.", "48", "Oart", "739", "_", "keyword_Oart"),
        ("40 CFR Part 60—Standards.", "40", "Part", "60", "—", "alternate_separator"),
        ("strong>48 CFR Part 2952_Solicitation.", "48", "Part", "2952", "_", "leaked_strong_tag"),
    ],
)
def test_heading_pieces_retain_publisher_irregularities(entry, title, keyword, part, separator, issue) -> None:
    (block,) = read_cfr_subject_index(f"<dl><dt>{entry}</dt></dl>".encode()).blocks
    assert block.text == entry
    assert block.heading is not None
    assert (block.heading.title, block.heading.keyword, block.heading.part, block.heading.separator) == (
        title,
        keyword,
        part,
        separator,
    )
    assert issue in block.heading.irregularities
    assert block.heading.heading.endswith(".")


def test_no_term_entries_blanks_unknown_heads_and_other_title_dd_are_retained() -> None:
    payload = b"<dl><dt>40 CFR Part 9_Reserved.</dt><dt>&nbsp;</dt><dt>40 CFR Unrecognized</dt><dd>N/A</dd><dd>12 CFR Part 3_Other.</dd></dl>"
    blocks = read_cfr_subject_index(payload).blocks
    assert len(blocks) == 5
    assert blocks[0].heading.part == "9"
    assert blocks[1].text == "\xa0"
    assert blocks[2].heading is None
    assert blocks[2].text == "40 CFR Unrecognized"
    assert blocks[3].text == "N/A"
    assert blocks[4].tag == "dd" and blocks[4].heading.title == "12"


def test_metadata_keeps_revision_distinct_from_page_review_date() -> None:
    payload = b"<h1>LoS: 35 CFR</h1><h3>Title 35: [Reserved]</h3><p>List of Subjects revised as of April 1, 2025.</p><dl><dt>&nbsp;</dt></dl><p>This page was last reviewed on May 1, 2025.</p>"
    result = read_cfr_subject_index(payload)
    assert [block.text for block in result.metadata] == [
        "LoS: 35 CFR",
        "Title 35: [Reserved]",
        "List of Subjects revised as of April 1, 2025.",
        "This page was last reviewed on May 1, 2025.",
    ]
    assert len(result.blocks) == 1


def test_retained_title_30_split_revision_remains_two_source_paragraphs() -> None:
    result = read_cfr_subject_index((FIXTURES / "subject-index-30-revision.html").read_bytes())
    assert [block.text for block in result.metadata] == [
        "Title 30: Mineral Resources",
        "List of Subjects revised as of April",
        "1, 2025.",
    ]


def test_unclosed_elements_are_retained_without_swallowing_next_heading() -> None:
    result = read_cfr_subject_index(b"<dl><dt>40 CFR Part 1_First<dd>A<dt>40 CFR Part 2_Second<dd>B")
    assert [block.text for block in result.blocks] == ["40 CFR Part 1_First", "A", "40 CFR Part 2_Second", "B"]
    assert all(block.issues == ("unclosed_element",) for block in result.blocks)


def test_comments_do_not_invent_blocks_and_separate_lists_keep_identity() -> None:
    result = read_cfr_subject_index(b"<!-- <dt>Fake</dt><dd>Fake</dd> --><dl><dt>A</dt></dl><dl><dd>B</dd></dl>")
    assert [(block.list_index, block.text) for block in result.blocks] == [(0, "A"), (1, "B")]


def test_invalid_utf8_retains_exact_bytes_with_explicit_issue() -> None:
    result = read_cfr_subject_index(b"<dl><dt>\xff</dt></dl>")
    assert result.issues == ("invalid_utf8",)
    assert result.blocks[0].raw_html == b"\xff"
    assert result.blocks[0].text == "\ufffd"


def test_orphan_text_and_unmatched_closing_tags_keep_original_bytes() -> None:
    payload = "<dl>é&amp;orphan</broken><dd>Actual</dd></dl>".encode()
    result = read_cfr_subject_index(payload)
    assert [(block.tag, block.text) for block in result.blocks] == [
        ("#text", "é"),
        ("#text", "&"),
        ("#text", "orphan"),
        ("/broken", ""),
        ("dd", "Actual"),
    ]
    assert result.blocks[3].issues == ("unexpected_list_close",)
    for block in result.blocks:
        assert payload[slice(*block.byte_span)] == block.raw_html


def test_semicolon_free_entity_is_not_changed_into_a_different_entity() -> None:
    result = read_cfr_subject_index(b"<dl><dd>A&amp B &unknown C</dd></dl>")
    assert result.blocks[0].text == "A& B &unknown C"


def test_comment_boundaries_and_self_closing_tags_do_not_invent_text_or_closes() -> None:
    result = read_cfr_subject_index(b"<dl><dt/><br/><dd>A<!-- hidden -->B<br/>C</dd></dl>")
    assert [(block.tag, block.text) for block in result.blocks] == [("dt", ""), ("br", ""), ("dd", "ABC")]
    assert result.blocks[-1].text_fragments == ("A", "B", "C")
    assert result.blocks[0].raw_html == b""


@pytest.mark.parametrize(
    "kwargs",
    [{"max_bytes": 1}, {"max_blocks": 1}, {"max_block_bytes": 1}, {"max_blocks": False}, {"max_block_bytes": 0}],
)
def test_explicit_bounds_refuse(kwargs: dict[str, int]) -> None:
    with pytest.raises(CfrSourceError):
        read_cfr_subject_index(b"<dl><dt>Heading</dt><dd>Term</dd></dl>", **kwargs)


@pytest.mark.parametrize(
    "payload",
    [
        b'<dl><broken data-x="larger than bound"></broken></dl>',
        b"<dl></unmatched-closing-tag></dl>",
        b"<dl><dt>&amp;&amp;&amp;</dt></dl>",
        b"<dl><dt><i><i><i><i></i></i></i></i></dt></dl>",
    ],
)
def test_block_bound_includes_unknown_tags_entities_and_inline_markup(payload: bytes) -> None:
    with pytest.raises(CfrSourceError, match="max_block_bytes"):
        read_cfr_subject_index(payload, max_block_bytes=10)
