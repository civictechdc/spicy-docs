"""One text derivation per rendition, each on a real publisher response.

The htm, txt and xml fixtures are exact publisher bytes; the PDF branch reads
the captured PyMuPDF page text under `tests/fixtures/gpo_pdf_text/`, so no PDF
is decoded here. The one live case is marked `integration`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spicy_docs.extraction.body_text import (
    RENDITION_CLEANUP_RULES,
    RENDITION_DERIVATIONS,
    RENDITION_MEDIA_TYPES,
    BodyText,
    BodyTextError,
    RenditionCleanup,
    body_text,
    rendition_text,
)
from spicy_docs.extraction.gpo_normalize import GpoCleanupRecord, normalize_gpo_glyphs, normalize_gpo_pages
from spicy_docs.extraction.model import PageContent, PageResult, TextBlock
from spicy_docs.sources.agency_reports.report_blocks import parse_agency_blocks
from spicy_docs.sources.govinfo.bodies import BODY_PREFERENCE, PACKAGE_BODY_FORMATS

BODIES = Path(__file__).parent / "fixtures" / "govinfo_bodies"
BILLS = Path(__file__).parent / "fixtures" / "govinfo_bills"
PDF_TEXT = Path(__file__).parent / "fixtures" / "gpo_pdf_text"
ENV_FILE = Path(os.environ.get("SPICY_DOCS_ENV_FILE", Path.home() / "Work/spicy-stack/spicy-docs/.env"))

HRPT1_HTM = (BODIES / "body-CRPT-119hrpt1.htm").read_bytes()
HRPT105_HTM = (BODIES / "body-CRPT-119hrpt105.htm").read_bytes()
CDIR_TXT = (BODIES / "body-CDIR-2026-02-20.excerpt.txt").read_bytes()
BILL_XML = (BILLS / "text-119hr6028ih.xml").read_bytes()
BILL_USLM = (BILLS / "uslm-119hconres11enr.xml").read_bytes()
HRPT105_PDF_PAGES: tuple[str, ...] = tuple(json.loads((PDF_TEXT / "CRPT-119hrpt105.json").read_text()))


class FakeExtractor:
    """Replays captured PyMuPDF page text, so the PDF branch needs no PDF."""

    def __init__(self, pages: tuple[str, ...]) -> None:
        self.pages = pages
        self.media_types: list[str] = []

    def extract(self, source: bytes, *, media_type: str):
        self.media_types.append(media_type)
        for number, text in enumerate(self.pages, start=1):
            yield PageResult({"page": number}, PageContent((TextBlock(text),), ()))


# ---------------------------------------------------------------------------
# The tables, and the one place they must agree with the grammar.
# ---------------------------------------------------------------------------


def test_the_derivation_table_covers_exactly_the_package_body_grammar() -> None:
    """`body_text` restates PACKAGE_BODY_FORMATS rather than importing upward; pin them equal."""
    assert set(RENDITION_DERIVATIONS) == set(PACKAGE_BODY_FORMATS)
    assert set(RENDITION_MEDIA_TYPES) == set(PACKAGE_BODY_FORMATS)
    for name, body_format in PACKAGE_BODY_FORMATS.items():
        assert RENDITION_MEDIA_TYPES[name] == body_format.media_types
    assert set(BODY_PREFERENCE) == set(RENDITION_DERIVATIONS)


def test_every_cleanup_rule_names_renditions_the_table_knows() -> None:
    """Cleanup rules are distinct, name known renditions (never pdf, whose rules live in gpo_normalize) and carry an
    artifact.
    """
    names = [rule.name for rule in RENDITION_CLEANUP_RULES]
    assert len(names) == len(set(names))
    for rule in RENDITION_CLEANUP_RULES:
        assert rule.renditions and set(rule.renditions) <= set(RENDITION_DERIVATIONS)
        assert "pdf" not in rule.renditions  # the PDF branch's rules are gpo_normalize.METADATA_RULES
        assert rule.artifact


# ---------------------------------------------------------------------------
# One derivation per rendition, each on real publisher bytes.
# ---------------------------------------------------------------------------


def test_htm_rendition_reads_the_pre_wrapper_and_drops_the_title_metadata() -> None:
    """The htm branch reads only the pre wrapper (4 markup elements, 591 metadata chars), dropping title metadata
    while keeping the printed heading.
    """
    derived = rendition_text(HRPT1_HTM, rendition="htm", media_type="text/html")

    assert isinstance(derived, BodyText)
    assert derived.rendition == "htm"
    assert derived.derivation == "markup-reader"
    assert derived.media_type == "text/html"
    assert derived.byte_size == len(HRPT1_HTM) == 13953
    assert derived.pages is None
    record = derived.record
    assert isinstance(record, RenditionCleanup)
    # The wrapper is html/title/body/pre and nothing else; only its text survives.
    assert record.markup_elements == 4
    assert record.metadata_element_chars == 591
    assert "PROVIDING FOR CONSIDERATION OF THE BILL" in derived.text
    assert "<pre>" not in derived.text and "<title>" not in derived.text
    # The title's own spelling of the heading is gone; the printed one stays.
    assert "House Report 119-1 - PROVIDING" not in derived.text


def test_txt_rendition_normalizes_crlf_and_keeps_the_leading_layout() -> None:
    """The txt branch counts 111 normalized line endings and 52 stripped trailing-space lines, while keeping GPO's
    leading layout.
    """
    derived = rendition_text(CDIR_TXT, rendition="txt", media_type="text/plain")

    assert derived.derivation == "text-rendition-cleanup"
    assert derived.rendition == "txt"
    assert derived.pages is None
    record = derived.record
    assert isinstance(record, RenditionCleanup)
    assert record.markup_events == 0 and record.markup_elements == 0
    assert record.line_endings_normalized == 111
    assert record.trailing_space_lines == 52
    assert "\r" not in derived.text
    assert "Official Congressional Directory" in derived.text
    # Leading spaces are GPO's centering and stay; trailing ones go.
    assert any(line.startswith("  ") for line in derived.text.split("\n"))
    assert all(line == line.rstrip() for line in derived.text.split("\n"))


def test_xml_rendition_keeps_element_boundaries_as_line_breaks() -> None:
    """Element boundaries become 26 line breaks, 38 whitespace-only lines are dropped, and no two elements' text runs
    together.
    """
    derived = rendition_text(BILL_XML, rendition="xml", media_type="application/xml")

    assert derived.derivation == "markup-reader"
    assert derived.pages is None
    record = derived.record
    assert isinstance(record, RenditionCleanup)
    assert record.element_line_breaks == 26
    # The pretty-print indentation between elements is formatting, not content.
    assert record.whitespace_only_lines == 38
    lines = derived.text.split("\n")
    assert "119th CONGRESS" in lines
    assert "H. R. 6028" in lines
    assert "Short title" in lines
    # Two elements' text never runs together on one line.
    assert "119th CONGRESSH. R. 6028" not in derived.text
    assert all(line.strip() for line in lines)


def test_uslm_rendition_takes_the_same_markup_reader_branch_as_xml() -> None:
    """B7: USLM's root varies by bill type (this one is <resolution>), so it reads as generic XML."""
    derived = rendition_text(BILL_USLM, rendition="uslm", media_type="application/xml")

    assert derived.derivation == RENDITION_DERIVATIONS["uslm"] == "markup-reader"
    assert derived.rendition == "uslm"
    assert derived.pages is None
    record = derived.record
    assert isinstance(record, RenditionCleanup)
    # Measured 2026-09-19 on BILLS-119hconres11enr (fixture README): 42
    # elements, no CRLF, no end-of-text marker, no GPO quote pair, no
    # trailing space on this one small fixture.
    assert record.markup_elements == 42
    assert record.element_line_breaks == 31
    assert record.whitespace_only_lines == 32
    assert record.line_endings_normalized == 0
    assert record.trailing_space_lines == 0
    lines = derived.text.split("\n")
    assert "119 HCONRES 11 ENR: Concurrent Resolution" in lines
    assert "Concurrent Resolution" in lines
    assert "Resolved by the House of Representatives (the Senate concurring)," in derived.text
    assert all(line.strip() for line in lines)


def test_pdf_rendition_is_extraction_then_gpo_normalization() -> None:
    """The PDF branch reports three extracted pages joined by newline, gpo-normalized with footers on and line
    numbers off.
    """
    extractor = FakeExtractor(HRPT105_PDF_PAGES)
    derived = rendition_text(b"%PDF-1.4\nstub", rendition="pdf", extractor=extractor)

    assert extractor.media_types == ["application/pdf"]
    assert derived.derivation == "pdf-extraction-gpo-normalized"
    assert derived.media_type == "application/pdf"
    assert derived.pages is not None and len(derived.pages) == 3
    # The text is the pages joined the way report_blocks._flatten joins them.
    assert derived.text == "\n".join(derived.pages)
    record = derived.record
    assert isinstance(record, GpoCleanupRecord)
    assert record.line_numbers is False and record.gpo_footers is True
    assert normalize_gpo_pages(HRPT105_PDF_PAGES)[0] == derived.pages


@pytest.mark.parametrize(
    ("data", "rendition", "media_type"),
    [
        (HRPT1_HTM, "htm", "text/html"),
        (CDIR_TXT, "txt", "text/plain"),
        (BILL_XML, "xml", "application/xml"),
        (BILL_USLM, "uslm", "application/xml"),
    ],
)
def test_every_rendition_yields_nonempty_text_and_its_own_derivation(
    data: bytes, rendition: str, media_type: str
) -> None:
    """Every rendition yields non-empty text carrying its declared derivation and byte size."""
    derived = rendition_text(data, rendition=rendition, media_type=media_type)
    assert derived.text.strip()
    assert derived.derivation == RENDITION_DERIVATIONS[rendition]
    assert derived.byte_size == len(data)


# ---------------------------------------------------------------------------
# The cleanup rules, each with a before and an after.
# ---------------------------------------------------------------------------


def test_line_ending_rule() -> None:
    """CRLF is normalized to LF and the two endings are counted."""
    before = "Calendar No. 140\r\n113th Congress\r\n"
    after = rendition_text(before.encode(), rendition="txt")
    assert after.text == "Calendar No. 140\n113th Congress\n"
    assert after.record.line_endings_normalized == 2


def test_end_of_text_marker_rule() -> None:
    """A trailing end-of-text marker becomes a blank line and is counted."""
    before = "the last line\n\x1a\n"
    after = rendition_text(before.encode(), rendition="txt")
    assert after.text == "the last line\n\n"
    assert after.record.end_of_text_markers == 1


def test_gpo_quote_pair_rule_collapses_both_spellings_to_one_double_quote() -> None:
    """GPO spells one quotation ``/'' in htm and curly-doubled in its PDF."""
    htm = rendition_text(b"the ``Review of Final Rule'' resolution", rendition="txt")
    assert htm.text == 'the "Review of Final Rule" resolution'
    assert htm.record.quote_pairs_collapsed == 2
    # The same sentence as PyMuPDF renders it from the PDF, through the shared rule.
    assert normalize_gpo_glyphs("the ‘‘Review of Final Rule’’ resolution") == htm.text


def test_trailing_space_rule_keeps_leading_layout() -> None:
    """Trailing spaces are stripped and counted while the leading layout indent stays."""
    before = "        Mr. Chairman   \nbody   \n"
    after = rendition_text(before.encode(), rendition="txt")
    assert after.text == "        Mr. Chairman\nbody\n"
    assert after.record.trailing_space_lines == 2


def test_a_self_closing_title_does_not_swallow_the_body() -> None:
    """`<title/>` has no end tag; counting it open would drop everything after it."""
    derived = rendition_text(b"<html><title/><body><pre>REAL BODY</pre></body></html>", rendition="htm")
    assert "REAL BODY" in derived.text
    assert derived.record.metadata_element_chars == 0


def test_blank_lines_survive_the_htm_branch_because_the_parser_reads_them() -> None:
    """A heading's body is "the non-blank lines under it"; dropping blanks would merge blocks."""
    derived = rendition_text(HRPT105_HTM, rendition="htm", media_type="text/html")
    assert "\n\n" in derived.text
    assert derived.record.whitespace_only_lines == 0


# ---------------------------------------------------------------------------
# The parser comparison: does the report parser accept the htm rendition?
# ---------------------------------------------------------------------------


def test_the_htm_rendition_parses_into_the_same_blocks_as_the_pdf_text() -> None:
    """Pinned 2026-09-19 on CRPT-119hrpt105, the one package held in both renditions.

    The PDF side reproduces the pinned count: 11 header lines, 9 matched
    blocks after the mid-word-break guard. The htm side matches it on every
    real heading and is one block *shorter*, and that one block is right to be
    missing: the PDF's extra `REPORT` block is the cover masthead, and its
    whole body is the two decorative cover glyphs `"` and `!` that
    `docs/extraction-gpo.md` already records as PyMuPDF artifacts of this
    exact page. The cleanup is what changes, never the parser's patterns.
    """
    htm = rendition_text(HRPT105_HTM, rendition="htm", media_type="text/html")
    pdf = rendition_text(b"%PDF-1.4\nstub", rendition="pdf", extractor=FakeExtractor(HRPT105_PDF_PAGES))

    htm_blocks = parse_agency_blocks(htm.text)
    pdf_blocks = parse_agency_blocks(pdf.text)
    assert len(pdf_blocks) == 10
    assert len([b for b in pdf_blocks if b.pattern not in {"preamble", "full_report"}]) == 9
    assert len(htm_blocks) == 9
    assert len([b for b in htm_blocks if b.pattern not in {"preamble", "full_report"}]) == 8

    # The one divergent block, and why the htm side is the right one.
    only_pdf = [b for b in pdf_blocks if b.agency_key == "REPORT"]
    assert len(only_pdf) == 1
    assert only_pdf[0].body == '"\n!'
    assert not [b for b in htm_blocks if b.agency_key == "REPORT"]

    # Every other heading is present on both sides, modulo GPO's justified
    # double spaces, which the PDF branch collapses and the htm branch keeps
    # because that spacing is the table layout.
    def squeeze(blocks) -> set[str]:
        return {" ".join(b.agency.split()) for b in blocks if b.agency and b.agency_key != "REPORT"}

    assert squeeze(htm_blocks) == squeeze(pdf_blocks)


def test_the_pdf_branch_splits_words_the_htm_branch_keeps_whole() -> None:
    """Why PDF is last: a committee report is never gutter-numbered, so
    `normalize_gpo_pages` cannot rejoin its print wraps."""
    htm = rendition_text(HRPT105_HTM, rendition="htm", media_type="text/html")
    pdf = rendition_text(b"%PDF-1.4\nstub", rendition="pdf", extractor=FakeExtractor(HRPT105_PDF_PAGES))

    def wraps(text: str) -> int:
        return sum(
            1
            for line in text.split("\n")
            if line.endswith("-") and line[:-1].endswith(tuple("abcdefghijklmnopqrstuvwxyz"))
        )

    assert wraps(pdf.text) == 16
    assert wraps(htm.text) == 0
    # The whole words only one side has.
    assert "resolution" in htm.text and "designees" in htm.text
    assert "reso\nlution" not in htm.text
    assert "olution" in pdf.text.replace("resolution", "")


# ---------------------------------------------------------------------------
# Refusals, and the fetched-body adapter.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rendition", ["", "html", "jpeg", None, 7])
def test_an_unknown_rendition_is_refused_by_name(rendition: object) -> None:
    """Empty, unknown and non-string rendition names are all refused."""
    with pytest.raises(BodyTextError, match="rendition must be one of"):
        rendition_text(b"body", rendition=rendition)  # type: ignore[arg-type]


def test_a_media_type_that_disagrees_with_the_rendition_is_refused() -> None:
    """A media type outside the rendition's own is refused, while a charset parameter is not a disagreement."""
    with pytest.raises(BodyTextError, match="not one of text/html"):
        rendition_text(HRPT1_HTM, rendition="htm", media_type="application/pdf")
    # A charset parameter is not a disagreement.
    assert rendition_text(HRPT1_HTM, rendition="htm", media_type="text/html; charset=utf-8").text


def test_empty_bytes_are_refused_because_no_body_route_can_mean_empty() -> None:
    """Empty bytes are refused: no body route can mean empty."""
    with pytest.raises(BodyTextError, match="nonempty bytes"):
        rendition_text(b"", rendition="txt")


def test_undecodable_text_is_refused_rather_than_replaced() -> None:
    """Non-UTF-8 bytes are refused rather than replacement-decoded."""
    with pytest.raises(BodyTextError, match="must be UTF-8"):
        rendition_text(b"\xff\xfe not utf-8", rendition="txt")


class FakeBody:
    """The three facts `FetchedBody` names, as `GovInfoPackageBody` states them."""

    class Identity:
        media_type = "text/html"
        byte_size = len(HRPT1_HTM)

    class Capture:
        body = HRPT1_HTM

    format = "htm"
    body = Identity()
    body_capture = Capture()


def test_body_text_reads_the_rendition_off_the_fetched_body() -> None:
    """rendition_text reads rendition, media type and size off a fetched body and equals the explicit-argument call."""
    derived = body_text(FakeBody())
    assert derived.rendition == "htm"
    assert derived.media_type == "text/html"
    assert derived.byte_size == len(HRPT1_HTM)
    assert derived == rendition_text(HRPT1_HTM, rendition="htm", media_type="text/html")


def test_body_text_refuses_something_that_is_not_a_fetched_body() -> None:
    """An input that does not state its format is refused."""
    with pytest.raises(BodyTextError, match="must state format"):
        body_text(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Live: the committee-report renditions GovInfo actually offers.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_committee_report_offers_no_txt_rendition_and_its_htm_matches_the_fixture() -> None:
    """Bounded, keyed, one package. CRPT offers htm and pdf; `txt` is not on offer.

    This is the measurement behind the fixture that stands in for a committee
    report's "text rendition": there is no `text/{id}.txt` for CRPT at all, so
    the text-bearing rendition the sealed order reaches is `htm`.
    """
    from spicy_docs.sources.govinfo.body_acquisition import (
        GovInfoBodyAcquirer,
        GovInfoBodyBudget,
        GovInfoFormatNotOfferedError,
    )
    from spicy_docs.transport.credentials import read_api_key

    if not ENV_FILE.exists():
        pytest.skip(f"no credential file at {ENV_FILE}")
    budget = GovInfoBodyBudget(
        max_requests=6,
        max_body_bytes=1024 * 1024,
        max_metadata_bytes=4 * 1024 * 1024,
        timeout_seconds=60,
        min_request_interval_seconds=0.5,
    )
    with GovInfoBodyAcquirer(budget=budget, api_key=read_api_key(ENV_FILE, "API_GOV")) as client:
        with pytest.raises(GovInfoFormatNotOfferedError) as caught:
            client.acquire("CRPT-119hrpt105", prefer=("txt",))
        assert caught.value.offered_formats == ("htm", "pdf")

        result = client.acquire("CRPT-119hrpt105")

    assert result.format == "htm"
    assert result.body_capture.body == HRPT105_HTM
    derived = body_text(result)
    assert derived.rendition == "htm"
    assert derived.derivation == "markup-reader"
    assert derived == rendition_text(HRPT105_HTM, rendition="htm", media_type="text/html")
