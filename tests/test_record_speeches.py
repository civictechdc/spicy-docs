"""The congressionalrecord adapter: the seam, not the parser.

Upstream's own suite tests its segmentation. These test what this repository
adds around it: bounded UTF-8 inputs, refusals in this package's terms, a
partial parse reported as partial, and a line span for every item, checked
against the fixtures with a line test written independently of upstream's
patterns. The expected readings are the parser's at ``PARSER_PIN``. They began
as the 2026-09-28 review's
(``docs/unitedstates-review-2026-09-28/validation/legal-record/current-record-probe.json``
in the workspace); moving the pin to #94 and #90 changed only the speaker of a
rule or title, now ``None`` where it was the string ``"None"``.
"""

from __future__ import annotations

import copy
import json
import socket
import sys
import tomllib
from collections import Counter
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from spicy_docs.sources.congress import record_speeches
from spicy_docs.sources.congress.record_speeches import (
    EXTRA_REQUIRED,
    LOCATED,
    PARSER_PIN,
    UNLOCATED,
    RecordSpeechDocument,
    RecordSpeechesError,
    parse_record_speeches,
    parser_available,
    read_record_issue,
)

needs_parser = pytest.mark.skipif(
    not parser_available(), reason="needs the 'record-speeches' extra: uv sync --frozen --extra record-speeches"
)
# The encoding cases hold the locale fixed at UTF-8 and vary only what the adapter writes with.
utf8_locale = pytest.mark.skipif(
    record_speeches.locale.getpreferredencoding(False).lower().replace("-", "") != "utf8",
    reason="the encoding cases are stated for a UTF-8 locale, which upstream's text-mode open() then reads",
)
# Upstream reads MODS with bs4's HTML parser (cr_parser.py:90), which warns on a document with an
# XML declaration (a granule's own).
pytestmark = pytest.mark.filterwarnings("ignore:It looks like you're using an HTML parser to parse an XML document")

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "record_speeches"
BOUND = 1024 * 1024
KIGGANS = "CREC-2026-09-16-pt1-PgH5835-8"
PLEDGE = "CREC-2026-09-17-pt1-PgH5987-5"
SENATE = "CREC-2026-09-17-pt1-PgS4765-6"
# A granule of CREC-2025-03-11-i46: GovInfo spells its id without the issue's -i46.
SUFFIXED = "CREC-2025-03-11-pt1-PgS1677-4"
SUFFIXED_PACKAGE = "CREC-2025-03-11-i46"
# A 1994 granule: its header states [Page H], no page number, and its id's 10 orders the section's granules.
ERA_1994 = "CREC-1994-03-25-pt1-PgH10"
GRANULES = (KIGGANS, PLEDGE, SENATE, SUFFIXED, ERA_1994)
# Kiggans's own MODS: the keyless metadata route, and the keyed route acquire_granule retains.
GRANULE_MODS = ("CREC-2026-09-16-pt1-PgH5835-8.granule-mods.xml", "CREC-2026-09-16-pt1-PgH5835-8.granule-mods-api.xml")


def _body(granule: str) -> bytes:
    return (FIXTURES / f"{granule}.htm").read_bytes()


def _mods(granule: str) -> bytes:
    """The suffixed or 1994 granule's own MODS, else its issue's MODS excerpt, named by the id's first 15 characters."""
    if granule in (SUFFIXED, ERA_1994):
        return (FIXTURES / f"{granule}.granule-mods-api.xml").read_bytes()
    return (FIXTURES / f"{granule[:15]}.mods.excerpt.xml").read_bytes()


def _own_mods_renamed(granule: str, renamed: str) -> bytes:
    """``granule``'s own keyed MODS with every mention of its id replaced by ``renamed``."""
    return (FIXTURES / f"{granule}.granule-mods-api.xml").read_bytes().replace(granule.encode(), renamed.encode())


def _read(granule: str, body: bytes | None = None) -> RecordSpeechDocument:
    return parse_record_speeches(
        _body(granule) if body is None else body,
        _mods(granule),
        granule,
        max_html_bytes=BOUND,
        max_mods_bytes=BOUND,
    )


def _dropped(line: str) -> bool:
    """A line upstream leaves out of an item's text, spelled with str methods rather than its patterns."""
    stripped = line.strip()
    return (line != "" and stripped == "") or stripped.startswith(("{time}", "[[Page "))


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every read here is offline; any connection or name lookup fails the test."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("record speeches must be read offline")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


# --- the three fixtures ------------------------------------------------------


@needs_parser
def test_kiggans_one_minute_is_one_speech_beside_an_item_upstream_leaves_unknown() -> None:
    """The House granule reads as the review recorded: an Unknown parenthetical, one speech by K000399, a rule."""
    document = _read(KIGGANS)
    assert (document.parse_status, document.parse_error, document.lines_exhausted) == ("complete", None, True)
    assert (document.package_id, document.vol, document.num, document.chamber, document.pages) == (
        "CREC-2026-09-16",
        "172",
        "146",
        "House",
        "H5835",
    )
    assert document.extension is False
    assert document.title == document.doc_title == "RECOGNIZING COMMANDER MICHELLE CAPONIGRO"
    assert [(item.kind, item.turn, item.speaker, item.speaker_bioguide) for item in document.items] == [
        ("Unknown", None, "Unknown", None),
        ("speech", 0, "Mrs. KIGGANS of Virginia", "K000399"),
        ("linebreak", None, None, None),
    ]
    assert document.items[0].text.startswith("  (Mrs. KIGGANS of Virginia asked and was given permission")
    assert "speaker_bioguide" not in document.items[0].source_item


@needs_parser
def test_the_pledge_is_procedural_with_no_person_id() -> None:
    """The Speaker pro tempore leading the Pledge carries no bioguide id, as the review recorded."""
    document = _read(PLEDGE)
    assert document.parse_status == "complete"
    assert [(item.kind, item.speaker, item.speaker_bioguide) for item in document.items] == [
        ("speech", "The SPEAKER pro tempore", None),
        ("linebreak", None, None),
    ]
    assert document.title == "PLEDGE OF ALLEGIANCE"


@needs_parser
def test_the_senate_granule_has_fifty_six_turns_and_no_presiding_officer_id() -> None:
    """The Senate granule: 66 items, 56 speech turns in order, and the MODS-stated id per speaker."""
    document = _read(SENATE)
    assert (document.parse_status, document.chamber, document.pages) == ("complete", "Senate", "S4765-S4774")
    assert Counter(item.kind for item in document.items) == {"speech": 56, "recorder": 5, "title": 3, "linebreak": 2}
    speeches = [item for item in document.items if item.kind == "speech"]
    assert [item.turn for item in speeches] == list(range(56))
    assert {item.speaker: item.speaker_bioguide for item in speeches} == {
        "The PRESIDING OFFICER": None,
        "The PRESIDING OFFICER (Mr. Hagerty)": None,
        "The PRESIDING OFFICER (Mr. Husted)": None,
        "The PRESIDING OFFICER (Mr. Schmitt)": None,
        "The PRESIDING OFFICER (Mr. Sheehy)": None,
        "Mr. GRASSLEY": "G000386",
        "Mr. THUNE": "T000250",
        "Mr. BARRASSO": "B001261",
        "Mr. SCHUMER": "S000148",
        "Mr. DURBIN": "D000563",
        "Ms. CANTWELL": "C000127",
        "Mr. BOOKER": "B001288",
        "Mr. MORENO": "M001242",
    }
    assert [dict(bill) for bill in document.related_bills] == [
        {"congress": "119", "context": "OTHER", "number": "4668", "type": "S"}
    ]
    assert document.related_laws == document.related_usc == document.related_statute == ()


@needs_parser
def test_a_granule_of_a_suffixed_issue_reads_under_its_packages_id() -> None:
    """Its id carries the issue date but not ``-i46``; the host its own MODS names is the package id."""
    issue = read_record_issue(_mods(SUFFIXED), max_mods_bytes=BOUND)
    assert (issue.package_id, issue.granule_id) == (SUFFIXED_PACKAGE, SUFFIXED)
    document = issue.speeches(_body(SUFFIXED), SUFFIXED, max_html_bytes=BOUND)
    assert (document.package_id, document.parse_status, document.vol, document.num, document.pages) == (
        SUFFIXED_PACKAGE,
        "complete",
        "171",
        "46",
        "S1677",
    )
    assert [(item.kind, item.speaker, item.speaker_bioguide) for item in document.items] == [
        ("speech", "Mr. THUNE", "T000250"),
        ("speech", "The ACTING PRESIDENT pro tempore", None),
        ("linebreak", None, None),
    ]


@needs_parser
def test_a_suffixed_issues_package_mods_admits_its_date_and_leaves_membership_to_the_mods() -> None:
    """The prefix is ``CREC-{date}-``: another date refuses by name, and this date reaches upstream's lookup."""
    issue = read_record_issue(_mods_xml(SUFFIXED_PACKAGE), max_mods_bytes=BOUND)
    assert (issue.package_id, issue.granule_id) == (SUFFIXED_PACKAGE, None)
    other_day = SUFFIXED.replace("2025-03-11", "2025-03-12")
    with pytest.raises(RecordSpeechesError, match=f"granule {other_day} is not a granule of {SUFFIXED_PACKAGE}"):
        issue.speeches(_body(SUFFIXED), other_day, max_html_bytes=BOUND)
    with pytest.raises(RecordSpeechesError, match=f"granule {SUFFIXED} is not in the {SUFFIXED_PACKAGE} MODS"):
        issue.speeches(_body(SUFFIXED), SUFFIXED, max_html_bytes=BOUND)


@needs_parser
def test_a_1994_granule_whose_header_states_no_page_reads_under_its_section() -> None:
    """GovInfo states no page number in 1994: the header's ``H`` is compared with the id's section only."""
    document = _read(ERA_1994)
    assert (document.package_id, document.parse_status, document.unaccounted_lines) == (
        "CREC-1994-03-25",
        "complete",
        (),
    )
    assert (document.vol, document.num, document.chamber, document.pages) == ("140", "36", "House", "H")
    assert [(item.speaker, item.speaker_bioguide) for item in document.items if item.kind == "speech"] == [
        ("Mr. NICKLES", "N000102"),
        ("The PRESIDING OFFICER", None),
        ("Mrs. KASSEBAUM", "K000017"),
    ]


@needs_parser
@pytest.mark.parametrize("granule", GRANULES)
def test_every_item_is_located_on_the_lines_its_text_came_from(granule: str) -> None:
    """Spans increase without overlap; each span's kept lines join to the text; only dropped lines lie between."""
    document = _read(granule)
    lines = document.source_lines
    assert document.items
    assert document.unaccounted_lines == ()
    previous = None
    for item in document.items:
        assert item.coordinates_status == LOCATED
        assert item.line_start is not None and item.line_end is not None
        if previous is None:
            header = lines[: item.line_start]
            assert all(
                line == "" or line.startswith(("[", "From the Congressional Record")) or line.strip() in document.title
                for line in header
            ), header
        else:
            assert item.line_start > previous
            assert all(_dropped(line) for line in lines[previous + 1 : item.line_start])
        assert item.line_end >= item.line_start
        kept = [
            lines[item.line_start],
            *(line for line in lines[item.line_start + 1 : item.line_end + 1] if not _dropped(line)),
        ]
        assert "\n".join(kept) == item.text
        previous = item.line_end
    assert previous == len(lines) - 1


@needs_parser
def test_the_senate_spans_step_over_page_markers_and_blank_lines() -> None:
    """The fixture exercises the dropped lines: page markers and whitespace-only lines sit inside spans."""
    document = _read(SENATE)
    inside = Counter(
        "page" if line.strip().startswith("[[Page ") else "blank"
        for item in document.items
        for line in document.source_lines[item.line_start + 1 : item.line_end + 1]
        if _dropped(line)
    )
    assert inside == {"page": 9, "blank": 3}


@needs_parser
def test_one_issue_reads_each_of_its_granules() -> None:
    """The MODS is parsed once and both 09-17 granules read against it, matching the one-shot reading."""
    issue = read_record_issue(_mods(PLEDGE), max_mods_bytes=BOUND)
    assert issue.package_id == "CREC-2026-09-17"
    for granule in (PLEDGE, SENATE):
        assert issue.speeches(_body(granule), granule, max_html_bytes=BOUND) == _read(granule)


@needs_parser
@pytest.mark.parametrize("name", GRANULE_MODS)
def test_a_granules_own_mods_reads_as_the_package_mods_does(name: str) -> None:
    """The granule's own MODS gives the package-MODS reading of that granule, apart from the MODS digest."""
    import hashlib

    mods = (FIXTURES / name).read_bytes()
    issue = read_record_issue(mods, max_mods_bytes=BOUND)
    assert (issue.package_id, issue.granule_id) == ("CREC-2026-09-16", KIGGANS)
    own = issue.speeches(_body(KIGGANS), KIGGANS, max_html_bytes=BOUND)
    assert own.mods_sha256 == "sha256:" + hashlib.sha256(mods).hexdigest()
    assert own == replace(_read(KIGGANS), mods_sha256=own.mods_sha256)
    assert read_record_issue(_mods(KIGGANS), max_mods_bytes=BOUND).granule_id is None


@needs_parser
def test_a_granules_own_mods_reads_no_other_granule() -> None:
    """It describes one granule; another of the same issue refuses by name before upstream looks."""
    issue = read_record_issue((FIXTURES / GRANULE_MODS[0]).read_bytes(), max_mods_bytes=BOUND)
    other = "CREC-2026-09-16-pt1-PgH5835-7"
    with pytest.raises(RecordSpeechesError, match=f"{other} is not the granule this MODS describes, {KIGGANS}"):
        issue.speeches(_body(KIGGANS), other, max_html_bytes=BOUND)


@needs_parser
def test_provenance_fields_name_the_inputs_and_the_pin() -> None:
    """Digests are ``sha256:`` over the exact bytes given, and the pin is the fork commit."""
    import hashlib

    document = _read(KIGGANS)
    assert document.html_sha256 == "sha256:" + hashlib.sha256(_body(KIGGANS)).hexdigest()
    assert document.mods_sha256 == "sha256:" + hashlib.sha256(_mods(KIGGANS)).hexdigest()
    assert document.parser_pin == PARSER_PIN
    with pytest.raises(TypeError):
        document.items[1].source_item["kind"] = "changed"


def test_fixtures_are_the_bytes_their_provenance_states() -> None:
    """Every fixture matches its recorded digest; each MODS excerpt is composed exactly as its method says.

    The kept elements' digests were taken from the original file, so a match
    shows each kept ``<relatedItem>`` is byte-identical to the publisher's.
    """
    import hashlib
    import json

    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    for entry in provenance["fixtures"]:
        data = (FIXTURES / entry["fixture"]).read_bytes()
        assert (len(data), hashlib.sha256(data).hexdigest()) == (entry["bytes"], entry["sha256"])
        if "kept" not in entry:
            continue
        separator = entry["separator"].encode()
        position = entry["prefix_end"]
        for index, kept in enumerate(entry["kept"]):
            start, end = kept["original_byte_range"]
            position += len(separator) if index else 0
            assert hashlib.sha256(data[position : position + end - start]).hexdigest() == kept["sha256"]
            position += end - start
        assert len(data) - position == entry["original_bytes"] - entry["tail_start"]


# --- partial parses ------------------------------------------------------------


@needs_parser
def test_an_item_failing_before_any_item_is_partial_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upstream catches the item's exception; the document says partial and keeps its error, not a clean empty."""
    from congressionalrecord.govinfo import cr_parser

    def refuse(_parser: object) -> None:
        raise ValueError("bad item")

    monkeypatch.setattr(cr_parser, "crItem", refuse)
    document = _read(SENATE)
    assert (document.parse_status, document.items, document.lines_exhausted) == ("partial", (), False)
    assert dict(document.parse_error) == {
        "type": "ValueError",
        "message": "bad item",
        "line": document.source_lines[-1],
    }
    # The line it failed on belongs to no item.
    assert document.unaccounted_lines == (len(document.source_lines) - 1,)


@needs_parser
def test_an_item_failing_after_one_item_keeps_that_item_located(monkeypatch: pytest.MonkeyPatch) -> None:
    """The item before the failure survives with its span; the document is still partial."""
    from congressionalrecord.govinfo import cr_parser

    complete = _read(SENATE)
    original = cr_parser.crItem
    calls = 0

    def fail_second(parser: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("second item refused")
        return original(parser)

    monkeypatch.setattr(cr_parser, "crItem", fail_second)
    document = _read(SENATE)
    assert (document.parse_status, document.lines_exhausted) == ("partial", False)
    assert document.parse_error is not None and document.parse_error["type"] == "ValueError"
    assert document.items == complete.items[:1]
    assert document.items[0].coordinates_status == LOCATED
    assert document.unaccounted_lines == (len(document.source_lines) - 1,)
    assert complete.unaccounted_lines == ()


def _altered(monkeypatch: pytest.MonkeyPatch, call: int, text: str) -> None:
    """Make the ``call``-th item upstream builds carry ``text`` instead of the lines it read."""
    from congressionalrecord.govinfo import cr_parser

    original = cr_parser.crItem
    calls = 0

    def alter(parser: object) -> object:
        nonlocal calls
        calls += 1
        made = original(parser)
        if calls == call:
            made.item["text"] = text
        return made

    monkeypatch.setattr(cr_parser, "crItem", alter)


@needs_parser
def test_an_item_whose_text_is_printed_only_further_on_is_unlocated_and_so_is_everything_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coordinates are never guessed: the rule line is printed later, but not after only dropped lines."""
    rule = [item.text.split("\n")[0] for item in _read(SENATE).items if item.kind == "linebreak"][-1]
    _altered(monkeypatch, 3, rule)
    document = _read(SENATE)
    statuses = [item.coordinates_status for item in document.items]
    assert statuses[:2] == [LOCATED, LOCATED]
    assert set(statuses[2:]) == {UNLOCATED}
    assert all(item.line_start is None and item.line_end is None for item in document.items[2:])
    # The unlocated items' lines are reported, apart from whole dropped lines.
    after = range(document.items[1].line_end + 1, len(document.source_lines))
    assert document.unaccounted_lines == tuple(i for i in after if not _dropped(document.source_lines[i]))
    assert document.unaccounted_lines


def _blank_before_first_item() -> bytes:
    """The Kiggans body with a whitespace-only line where the title scan stops."""
    return _body(KIGGANS).replace(b"CAPONIGRO\n\n", b"CAPONIGRO\n\n   \n", 1)


@needs_parser
def test_the_first_item_starts_on_the_line_the_title_scan_stopped_on() -> None:
    """A whitespace-only line ends the title scan, so upstream begins its first item with it."""
    document = _read(KIGGANS, _blank_before_first_item())
    first = document.items[0]
    assert (first.kind, first.line_start, document.source_lines[first.line_start]) == ("empty_line", 11, "   ")
    assert first.text.startswith("   \n  (Mrs. KIGGANS of Virginia asked")


@needs_parser
def test_the_first_item_is_never_moved_off_that_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Were the first item's text to start one line on, skipping the blank to reach it would be a guess."""
    first = _read(KIGGANS, _blank_before_first_item()).items[0]
    _altered(monkeypatch, 1, first.text.split("\n", 1)[1])
    assert _read(KIGGANS, _blank_before_first_item()).items[0].coordinates_status == UNLOCATED


@needs_parser
def test_a_parser_without_parse_status_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """An installed build lacking the fork's completion field cannot show a partial parse, so it is refused."""
    from congressionalrecord.govinfo import cr_parser

    original = cr_parser.ParseCRFile.write_page

    def unreported(self: object) -> None:
        original(self)
        self.crdoc.pop("parse_status")

    monkeypatch.setattr(cr_parser.ParseCRFile, "write_page", unreported)
    with pytest.raises(RecordSpeechesError, match="does not report parse completion"):
        _read(KIGGANS)


# --- lines nothing accounts for, and the page the header states -------------


@needs_parser
def test_a_skipped_line_that_carries_text_is_reported() -> None:
    """Upstream skips any line that starts like a page marker; the text after the marker is not in any item."""
    marker = next(line for line in _read(SENATE).source_lines if line.startswith("[[Page "))
    document = _read(SENATE, _body(SENATE).replace(marker.encode(), marker.encode() + b" and a sentence", 1))
    assert document.parse_status == "complete"
    assert {item.coordinates_status for item in document.items} == {LOCATED}
    (index,) = document.unaccounted_lines
    assert document.source_lines[index] == f"{marker} and a sentence"
    assert all("and a sentence" not in item.text for item in document.items)


@needs_parser
def test_a_body_whose_header_names_another_section_refuses() -> None:
    """The 09-17 MODS holds both granules, so only the header shows the House body is not the Senate granule."""
    with pytest.raises(RecordSpeechesError, match=f"granule {SENATE} names page S4765, but .* pages 'H5987'"):
        parse_record_speeches(_body(PLEDGE), _mods(SENATE), SENATE, max_html_bytes=BOUND, max_mods_bytes=BOUND)


@needs_parser
def test_a_body_whose_header_names_another_page_of_the_section_refuses() -> None:
    """The Kiggans body starts on H5835, so it is not the granule that starts on H5836."""
    other = "CREC-2026-09-16-pt1-PgH5836"
    issue = read_record_issue(_own_mods_renamed(KIGGANS, other), max_mods_bytes=BOUND)
    with pytest.raises(RecordSpeechesError, match=f"granule {other} names page H5836, but .* pages 'H5835'"):
        issue.speeches(_body(KIGGANS), other, max_html_bytes=BOUND)


@needs_parser
def test_a_header_whose_pages_name_no_section_refuses() -> None:
    """Upstream reads ``[Page 5835]`` as pages '5835'; with no section there is nothing to hold the id to."""
    body = _body(KIGGANS).replace(b"[Page H5835]", b"[Page 5835]", 1)
    with pytest.raises(RecordSpeechesError, match=f"granule {KIGGANS} names page H5835, but .* pages '5835'"):
        _read(KIGGANS, body)


@needs_parser
@pytest.mark.parametrize(
    ("granule", "renamed", "refused"),
    [
        (KIGGANS, "CREC-2026-09-16-pt1-PgH-FrontMatter", None),
        (KIGGANS, "CREC-2026-09-16-pt1-PgS-FrontMatter", "names section S, but .* pages 'H5835'"),
        (ERA_1994, "CREC-1994-03-25-pt1-PgH", None),
        (ERA_1994, "CREC-1994-03-25-pt1-PgS10", "names page S10, but .* pages 'H'"),
    ],
    ids=["front-matter", "front-matter-other-section", "1994-section-id", "1994-other-section"],
)
def test_an_id_or_header_without_a_page_number_is_held_to_its_section(
    granule: str, renamed: str, refused: str | None
) -> None:
    """``-PgH-FrontMatter`` and 1994's ``-PgH`` name no page, and 1994's ``[Page H]`` states none: sections only."""
    issue = read_record_issue(_own_mods_renamed(granule, renamed), max_mods_bytes=BOUND)
    if refused:
        with pytest.raises(RecordSpeechesError, match=f"granule {renamed} {refused}"):
            issue.speeches(_body(granule), renamed, max_html_bytes=BOUND)
    else:
        assert issue.speeches(_body(granule), renamed, max_html_bytes=BOUND).pages == _read(granule).pages


@needs_parser
@pytest.mark.parametrize(
    ("body", "granule", "stated"),
    [
        (ERA_1994, KIGGANS, "volume 140, number 36"),
        (PLEDGE, "CREC-2026-09-16-pt1-PgH-FrontMatter", "volume 172, number 147"),
    ],
    ids=["1994-body-under-a-2026-id", "next-issues-body-under-a-front-matter-id"],
)
def test_a_body_of_another_issue_refuses_under_this_granules_mods(body: str, granule: str, stated: str) -> None:
    """Held only to the section, a body of another issue passes the page check; its volume and number do not.

    One front-matter id is in two packages (CREC-2025-03-11-pt1-PgS-FrontMatter, Nos. 45 and 46), so the id alone
    cannot tell the two bodies apart. Upstream reads the MODS record's own volume and number from its searchTitle.
    """
    issue = read_record_issue(_own_mods_renamed(KIGGANS, granule), max_mods_bytes=BOUND)
    with pytest.raises(
        RecordSpeechesError,
        match=f"granule {granule}'s MODS record is volume 172, number 146, but its body's header states {stated}",
    ):
        issue.speeches(_body(body), granule, max_html_bytes=BOUND)


@needs_parser
def test_a_mods_record_that_states_no_issue_leaves_the_header_uncompared() -> None:
    """A searchTitle without the volume suffix gives upstream no volume or number, so the check has none to hold."""
    untitled = _own_mods_renamed(KIGGANS, KIGGANS).replace(b"; Congressional Record Vol. 172, No. 146<", b"<", 1)
    document = read_record_issue(untitled, max_mods_bytes=BOUND).speeches(_body(KIGGANS), KIGGANS, max_html_bytes=BOUND)
    assert (document.parse_status, document.doc_title, document.vol, document.num) == ("complete", None, "172", "146")


# --- refusals ------------------------------------------------------------------


@needs_parser
def test_a_granule_absent_from_the_mods_refuses_by_name() -> None:
    """Upstream's RuntimeError for a missing accessId becomes this package's refusal, naming the granule."""
    absent = "CREC-2026-09-17-pt1-PgH5987-4"
    with pytest.raises(RecordSpeechesError, match=f"granule {absent} is not in the CREC-2026-09-17 MODS") as caught:
        parse_record_speeches(_body(PLEDGE), _mods(PLEDGE), absent, max_html_bytes=BOUND, max_mods_bytes=BOUND)
    assert isinstance(caught.value.__cause__, RuntimeError)


@needs_parser
def test_a_body_upstream_cannot_read_refuses_rather_than_raising_upstreams_error() -> None:
    """No ``<pre>``: upstream's own exception reaches the caller as a refusal naming the granule."""
    with pytest.raises(RecordSpeechesError, match=f"could not read granule {KIGGANS}: AttributeError") as caught:
        _read(KIGGANS, b"<html><body>no preformatted text</body></html>")
    assert isinstance(caught.value.__cause__, AttributeError)


def _truncated_after_volume_line() -> bytes:
    """The Kiggans body cut off at the end of its volume line, as a short retained body would be."""
    body = _body(KIGGANS)
    return body[: body.index(b"\n[House]")]


@needs_parser
@pytest.mark.parametrize(
    ("body", "stated"),
    [
        (_truncated_after_volume_line, "ends before its header's chamber line"),
        (lambda: _body(KIGGANS).replace(b"Number 146 (", b"No. 146 (", 1), "the header's volume line does not match"),
    ],
    ids=["cut-short", "astray"],
)
def test_a_header_upstream_cannot_read_refuses_through_its_named_error(body: object, stated: str) -> None:
    """Upstream raises ``CRParseError`` for a header cut short or astray; the refusal wraps it and says which."""
    from congressionalrecord.govinfo import cr_parser

    with pytest.raises(
        RecordSpeechesError, match=f"granule {KIGGANS} has no header the parser can read: .*{stated}"
    ) as caught:
        _read(KIGGANS, body())
    assert isinstance(caught.value.__cause__, cr_parser.CRParseError)


@needs_parser
def test_a_parser_that_returns_no_header_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pin refuses an unreadable header itself, so a build that returns none is not this pin, and refuses."""
    from congressionalrecord.govinfo import cr_parser

    original = cr_parser.ParseCRFile.write_header

    def headless(self: object) -> None:
        original(self)
        self.crdoc["header"] = False

    monkeypatch.setattr(cr_parser.ParseCRFile, "write_header", headless)
    with pytest.raises(RecordSpeechesError, match=f"read no header for {KIGGANS}"):
        _read(KIGGANS)


@needs_parser
@pytest.mark.parametrize(
    ("granule", "message"),
    [
        (SENATE, "not a granule of CREC-2026-09-16"),
        ("CREC-2026-09-16-pt1-PgH5835.8", "contains a dot"),
        ("CREC-2026-09-16-pt1-H5835-8", "names no page"),
        ("../CREC-2026-09-16-pt1-PgH5835-8", "not a GovInfo granule id"),
        ("", "not a GovInfo granule id"),
    ],
)
def test_a_granule_id_the_issue_cannot_hold_refuses(granule: str, message: str) -> None:
    """The id becomes a file name upstream reads the accessId from, so only this issue's plain ids pass."""
    issue = read_record_issue(_mods(KIGGANS), max_mods_bytes=BOUND)
    with pytest.raises(RecordSpeechesError, match=message):
        issue.speeches(_body(KIGGANS), granule, max_html_bytes=BOUND)


@pytest.mark.parametrize(
    ("html", "mods", "html_bound", "mods_bound", "message"),
    [
        (b"x" * 11, b"<mods/>", 10, BOUND, "CREC granule HTML exceeds its 10-byte bound"),
        (b"", b"<mods/>", BOUND, BOUND, "CREC granule HTML is empty"),
        ("text", b"<mods/>", BOUND, BOUND, "CREC granule HTML must be exact bytes"),
        (b"<pre/>", b"x" * 11, BOUND, 10, "CREC MODS exceeds its 10-byte bound"),
        (b"<pre/>", b"", BOUND, BOUND, "CREC MODS is empty"),
        (b"<pre/>", b"<mods/>", BOUND, True, "CREC MODS byte bound must be a positive integer"),
    ],
)
def test_byte_bounds_refuse_before_anything_is_parsed(
    monkeypatch: pytest.MonkeyPatch, html: object, mods: object, html_bound: object, mods_bound: object, message: str
) -> None:
    """A bound, emptiness or type refusal comes first: neither the XML gate nor the parser is reached."""

    def unreachable(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("parsed before the bounds were checked")

    monkeypatch.setattr(record_speeches, "_parser_module", unreachable)
    monkeypatch.setattr(record_speeches, "parse_govinfo_mods", unreachable)
    with pytest.raises(RecordSpeechesError, match=message):
        parse_record_speeches(html, mods, KIGGANS, max_html_bytes=html_bound, max_mods_bytes=mods_bound)


def _mods_xml(own: str, *hosts: str) -> bytes:
    """A minimal MODS stating ``own`` in its root extension and each of ``hosts`` in a host relatedItem."""
    related = "".join(
        f"<relatedItem type='host'><extension><accessId>{host}</accessId></extension></relatedItem>" for host in hosts
    )
    return (
        f"<mods xmlns='http://www.loc.gov/mods/v3'><extension><accessId>{own}</accessId></extension>{related}</mods>"
    ).encode()


@needs_parser
@pytest.mark.parametrize(
    ("mods", "message"),
    [
        (
            b'<!DOCTYPE mods [<!ENTITY x "y">]><mods/>',
            "unreadable: GovInfo MODS permits only an inert external DOCTYPE",
        ),
        (b"<mods xmlns='http://www.loc.gov/mods/v3'/>", r"must state exactly one accessId; it states \[\]"),
        (b"<other/>", "unreadable: GovInfo MODS requires root"),
        (b"<mods", "unreadable: GovInfo MODS is malformed"),
        (_mods_xml("CRPT-119hrpt1"), "names CRPT-119hrpt1, not a Congressional Record issue"),
        (_mods_xml(KIGGANS), "does not name a package"),
        (_mods_xml(KIGGANS, "CRPT-119hrpt1"), "names CRPT-119hrpt1, not a Congressional Record issue"),
        (
            _mods_xml(PLEDGE, "CREC-2026-09-16"),
            f"describes {PLEDGE}, which is not a granule of its host CREC-2026-09-16",
        ),
        (
            _mods_xml(KIGGANS, "CREC-2026-09-16", "CREC-2026-09-17"),
            "must state exactly one host package",
        ),
        (
            _mods_xml(SUFFIXED.replace("2025-03-11", "2025-03-12"), SUFFIXED_PACKAGE),
            f"which is not a granule of its host {SUFFIXED_PACKAGE}",
        ),
    ],
)
def test_the_mods_passes_the_bounded_gate_and_its_shape_is_read_from_the_document(mods: bytes, message: str) -> None:
    """Read by this repository's MODS mapping first; a host relatedItem makes it a granule's own, else a package's."""
    with pytest.raises(RecordSpeechesError, match=message):
        read_record_issue(mods, max_mods_bytes=BOUND)


@needs_parser
def test_a_body_that_is_not_utf8_refuses() -> None:
    with pytest.raises(RecordSpeechesError, match="CREC granule HTML is not UTF-8"):
        _read(KIGGANS, _body(KIGGANS).replace(b"Commander", b"Comm\xe4nder", 1))


@needs_parser
def test_a_carriage_return_refuses_because_upstream_would_read_different_lines() -> None:
    """Universal newlines would fold CRLF, so upstream's lines would not be the retained bytes' lines."""
    with pytest.raises(RecordSpeechesError, match="does not read back unchanged"):
        _read(KIGGANS, _body(KIGGANS).replace(b"\n", b"\r\n"))


@needs_parser
@utf8_locale
def test_non_ascii_text_reaches_the_parser_unchanged() -> None:
    """Written in the locale encoding upstream reads, an accented name survives into the item text."""
    document = _read(KIGGANS, _body(KIGGANS).replace(b"Caponigro for 20", "Capónigro for 20".encode(), 1))
    assert "Capónigro for 20" in document.items[1].text


@needs_parser
@utf8_locale
@pytest.mark.parametrize(
    ("encoding", "message"),
    [
        ("ascii", "cannot be written in the locale encoding ascii"),
        ("latin-1", "does not read back unchanged"),
    ],
)
def test_text_the_locale_cannot_carry_refuses(monkeypatch: pytest.MonkeyPatch, encoding: str, message: str) -> None:
    """A locale that cannot encode the text, or that disagrees with upstream's own open(), refuses."""
    body = _body(KIGGANS).replace(b"Caponigro for 20", "Capónigro for 20".encode(), 1)
    issue = read_record_issue(_mods(KIGGANS), max_mods_bytes=BOUND)
    monkeypatch.setattr(record_speeches.locale, "getpreferredencoding", lambda _do_setlocale=True: encoding)
    with pytest.raises(RecordSpeechesError, match=message):
        issue.speeches(body, KIGGANS, max_html_bytes=BOUND)


# --- the extra, the pin and threads ------------------------------------------


def test_without_the_extra_every_entry_point_refuses_by_naming_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the package unimportable, availability is False and reading refuses with the install command."""
    for name in [name for name in sys.modules if name.split(".")[0] == "congressionalrecord"] + ["congressionalrecord"]:
        monkeypatch.setitem(sys.modules, name, None)
    assert not parser_available()
    assert "uv sync --frozen --extra record-speeches" in EXTRA_REQUIRED
    with pytest.raises(RecordSpeechesError, match="'record-speeches' extra"):
        read_record_issue(_mods(KIGGANS), max_mods_bytes=BOUND)
    with pytest.raises(RecordSpeechesError, match="'record-speeches' extra"):
        _read(KIGGANS)


def test_the_pin_constant_is_the_revision_pyproject_pins_and_the_lock_resolves() -> None:
    """Moving the pin in one place without the others fails here."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    source = project["tool"]["uv"]["sources"]["congressionalrecord"]
    assert (source["git"], source["rev"]) == ("https://github.com/mikewolfd/congressional-record", PARSER_PIN)
    extras = project["project"]["optional-dependencies"]
    assert extras["record-speeches"] == ["congressionalrecord==2.3.0", "beautifulsoup4==4.14.3"]
    # The parser's reader is held at the version the html extra pins, so a host resolves the one tested.
    assert set(extras["record-speeches"]) & set(extras["html"]) == {"beautifulsoup4==4.14.3"}
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    (package,) = [package for package in lock["package"] if package["name"] == "congressionalrecord"]
    assert package["source"]["git"].endswith(f"?rev={PARSER_PIN}#{PARSER_PIN}")


@needs_parser
def test_a_parse_leaves_the_class_line_kind_table_unchanged() -> None:
    """Upstream copies ``item_types`` per document, so parsing writes no speaker pattern into the class's table."""
    from congressionalrecord.govinfo import cr_parser

    table = cr_parser.ParseCRFile.item_types
    before = copy.deepcopy(table)
    for granule in GRANULES:
        _read(granule)
        assert cr_parser.ParseCRFile.item_types is table
        assert table == before


def _speaker_only_the_mods_names() -> tuple[bytes, bytes]:
    """The Kiggans body and her own MODS with the speaker spelled ``Mr. de LUGO`` in both.

    #90's speaker pattern takes a surname of capitals after an optional
    capitalized particle, so a lower-case ``de`` puts the line outside it: only
    the MODS speaker list, which upstream writes into the line-kind table per
    document, makes it a speech.
    """
    body = _body(KIGGANS).replace(b"  Mrs. KIGGANS of Virginia. Mr. Speaker", b"  Mr. de LUGO. Mr. Speaker", 1)
    mods = (FIXTURES / GRANULE_MODS[1]).read_bytes()
    return body, mods.replace(b">Mrs. KIGGANS of Virginia</name>", b">Mr. de LUGO</name>", 1)


@needs_parser
def test_a_read_interrupted_by_another_keeps_the_speaker_only_its_mods_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Another document read between this one's table write and its items leaves this reading as it was alone.

    That is the interleaving two threads can produce. Upstream copies the table
    per document; were it the class's, the Senate read would replace the speaker
    pattern and this speech would fold into the item before it, as it does when
    the MODS does not name the speaker.
    """
    from congressionalrecord.govinfo import cr_parser

    body, mods = _speaker_only_the_mods_names()
    issue = read_record_issue(mods, max_mods_bytes=BOUND)
    alone = issue.speeches(body, KIGGANS, max_html_bytes=BOUND)
    assert [(item.kind, item.speaker, item.speaker_bioguide) for item in alone.items] == [
        ("Unknown", "Unknown", None),
        ("speech", "Mr. de LUGO", "K000399"),
        ("linebreak", None, None),
    ]
    unnamed = read_record_issue((FIXTURES / GRANULE_MODS[1]).read_bytes(), max_mods_bytes=BOUND)
    assert [item.kind for item in unnamed.speeches(body, KIGGANS, max_html_bytes=BOUND).items] == [
        "Unknown",
        "linebreak",
    ]

    original = cr_parser.ParseCRFile.gen_file_metadata
    others: list[RecordSpeechDocument | None] = []

    def interrupted(parser: object) -> None:
        original(parser)
        if not others:
            others.append(None)
            others[0] = _read(SENATE)

    monkeypatch.setattr(cr_parser.ParseCRFile, "gen_file_metadata", interrupted)
    assert issue.speeches(body, KIGGANS, max_html_bytes=BOUND) == alone
    assert others and others[0] is not None and others[0].granule_id == SENATE


class _SharedTable:
    """``item_types`` as upstream kept it before #94: every document reads and writes one table."""

    def __init__(self, table: dict) -> None:
        self.table = table

    def __get__(self, instance: object, owner: type | None = None) -> dict:
        return self.table

    def __set__(self, instance: object, value: object) -> None:
        pass


@pytest.fixture
def install_record() -> Iterator[None]:
    """The installed commit is read once per process; a test that fakes the install reads it afresh, and after."""
    record_speeches._installed_commit.cache_clear()
    yield
    record_speeches._installed_commit.cache_clear()


def _installed_as(monkeypatch: pytest.MonkeyPatch, root: Path, direct_url: dict) -> None:
    """Put a ``congressionalrecord`` distribution recording ``direct_url`` first on the metadata path."""
    info = root / "congressionalrecord-2.3.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: congressionalrecord\nVersion: 2.3.0\n")
    (info / "direct_url.json").write_text(json.dumps(direct_url))
    monkeypatch.syspath_prepend(str(root))


@needs_parser
def test_a_git_install_of_another_fork_commit_refuses_naming_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, install_record: None
) -> None:
    """Every fork revision installs as 2.3.0, so the commit a git install records is what tells them apart."""
    other = "6bb521b11b498f2e8dbac614a4394c703c6773ac"  # the previous pin, which still returned the string "None"
    _installed_as(
        monkeypatch,
        tmp_path,
        {"url": "https://github.com/mikewolfd/congressional-record", "vcs_info": {"vcs": "git", "commit_id": other}},
    )
    with pytest.raises(RecordSpeechesError, match=f"is commit {other}, not the pinned {PARSER_PIN}"):
        _read(KIGGANS)


@needs_parser
def test_a_wheel_install_records_no_commit_and_is_held_to_the_forks_surface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, install_record: None
) -> None:
    """A vendored wheel's install records an archive, not a commit: it reads, held to the fork's surface alone."""
    _installed_as(
        monkeypatch, tmp_path, {"url": "file:///vendor/congressionalrecord-2.3.0-py3-none-any.whl", "archive_info": {}}
    )
    assert record_speeches._installed_commit() is None
    assert _read(KIGGANS).parse_status == "complete"
    from congressionalrecord.govinfo import cr_parser

    monkeypatch.delattr(cr_parser, "CRParseError")
    with pytest.raises(RecordSpeechesError, match="has no CRParseError; .*'record-speeches' extra"):
        _read(KIGGANS)


@needs_parser
def test_a_parser_that_shares_one_line_kind_table_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A build that writes each document's speaker pattern into the class's table is not the pin, and refuses."""
    from congressionalrecord.govinfo import cr_parser

    shared = _SharedTable(copy.deepcopy(cr_parser.ParseCRFile.item_types))
    monkeypatch.setattr(cr_parser.ParseCRFile, "item_types", shared)
    with pytest.raises(RecordSpeechesError, match=f"shares one line-kind table across documents; {EXTRA_REQUIRED}"):
        _read(KIGGANS)
