"""Annual itempath observations preserve exact spans and bracketed source stubs."""

from pathlib import Path

import pytest

from spicy_docs.sources.uscode import UsCodeSourceError
from spicy_docs.sources.uscode.annual import scan_uscode_annual_sections

FIXTURES = Path(__file__).parent / "fixtures" / "uscode"


def rows(body):
    result = []
    assert scan_uscode_annual_sections(body, on_section=result.append) == len(result)
    return result


def test_real_bracketed_322_and_following_323_keep_independent_keys_and_byte_spans():
    body = (FIXTURES / "annual-2012usc40-sections.htm").read_bytes()
    stub, live = rows(body)
    assert stub.itempath.endswith("/[Sec. 322") and stub.bracketed
    assert stub.usckey == "400000000000000000000000000000000"
    assert live.itempath.endswith("/Sec. 323") and not live.bracketed
    assert live.usckey == "400000000032300000000000000000000"
    assert stub.parts[0].section == "322" and live.parts[0].section == "323"
    assert stub.heading.field_name == "repealedhead"
    assert "[§322. Repealed." in stub.heading.text
    assert "Consumer Information Center Fund" in live.heading.text
    for row in (stub, live):
        assert body[slice(*row.itempath_span)].decode() == row.itempath_comment
        assert body[slice(*row.document_comment_span)].decode() == row.document_comment
        assert body[slice(*row.heading.byte_span)].decode() == row.heading.html
        assert row.issues == ()


def test_annual_preserves_ranges_lists_unknown_chunks_and_nonsection_itempaths():
    body = """<!-- documentid:5a_range usckey:RAW publisher-extra:kept -->
<!-- itempath:/50/APPENDIX/[Secs. 7A–1 to 9B, 11, unrecognized label -->
<!-- itempath:/50/APPENDIX/CHAPTER 1 -->""".encode()
    section, chapter = rows(body)
    assert section.bracketed and section.section_label == "Secs."
    assert [(p.kind, p.range_start, p.range_end, p.section) for p in section.parts] == [
        ("range", "7A–1", "9B", None),
        ("section", None, None, "11"),
        ("unparsed", None, None, None),
    ]
    assert section.parts[1].raw == " 11"
    assert ("publisher-extra", "kept") in section.document_fields
    assert chapter.section_label is None and chapter.parts == ()
    assert chapter.usckey is None and chapter.document_comment is None
    assert chapter.issues == ("missing_usckey",)


def test_missing_repeated_or_empty_keys_do_not_inherit_other_blocks():
    body = b"""<!-- documentid:one usckey:FIRST --><!-- itempath:/10/Sec. 1 -->
<!-- documentid:two currentthrough:2012 --><!-- itempath:/10/Sec. 2 -->
<!-- documentid:three usckey:A usckey:B --><!-- itempath:/10/Sec. 3 -->
<!-- documentid:four usckey: --><!-- itempath:/10/Sec. 4 -->"""
    first, missing, repeated, empty = rows(body)
    assert first.usckey == "FIRST" and first.issues == ()
    assert missing.usckey is None and missing.issues == ("missing_usckey",)
    assert repeated.usckey is None and repeated.issues == ("repeated_usckey",)
    assert ("usckey", "A") in repeated.document_fields and ("usckey", "B") in repeated.document_fields
    assert empty.usckey == "" and empty.issues == ("empty_usckey",)


def test_invalid_utf8_has_an_issue_and_original_byte_spans():
    body = b"\xff<!-- documentid:x usckey:\xff --><!-- itempath:/10/Sec. 1 -->\n<!-- field-start:head --><h3>\xff</h3><!-- field-end:head -->"
    row = rows(body)[0]
    assert row.issues == ("invalid_utf8",)
    assert row.usckey == "\ufffd" and row.heading.text == "\ufffd"
    assert body[slice(*row.document_comment_span)].startswith(b"<!-- documentid:x usckey:\xff")
    assert body[slice(*row.itempath_span)] == b"<!-- itempath:/10/Sec. 1 -->"


def test_unclosed_heading_is_reported_without_borrowing_next_heading():
    body = b"<!-- itempath:/10/Sec. 1 --><!-- field-start:head --><h3>first</h3><!-- itempath:/10/Sec. 2 --><!-- field-start:head --><h3>second</h3><!-- field-end:head -->"
    first, second = rows(body)
    assert first.heading is None and "heading_field_unclosed" in first.issues
    assert second.heading.text == "second"


def test_many_unclosed_comment_openers_refuse_without_reading_any_partial_record():
    observations = []
    with pytest.raises(UsCodeSourceError, match="unclosed comment"):
        scan_uscode_annual_sections(b"<!-- itempath:/10/Sec. 1 " + b"<!--" * 4000, on_section=observations.append)
    assert observations == []


def test_long_comment_whitespace_is_kept_as_source_text_without_regex_retries():
    body = b"<!-- documentid:x " + b" " * 100_000 + b"y usckey:RAW -->\n<!-- itempath:/10/Sec. 1 -->"
    row = rows(body)[0]
    assert row.usckey == "RAW"
    assert row.document_fields[0] == ("documentid", "x " + " " * 100_000 + "y")


@pytest.mark.parametrize(
    "body,kwargs", [(b"", {}), (b"<!-- itempath:/1/Sec. 1", {}), (b"<!-- itempath:x -->", {"max_bytes": 2})]
)
def test_annual_refuses_empty_truncated_comments_and_over_budget(body, kwargs):
    with pytest.raises(UsCodeSourceError):
        scan_uscode_annual_sections(body, on_section=lambda row: None, **kwargs)
