"""The congressionalrecord adapter: the seam, not the parser.

Upstream's own suite tests its segmentation. These test what this repository
adds around it: bounded UTF-8 inputs, refusals in this package's terms, a
partial parse reported as partial, and a line span for every item, checked
against the fixtures with a line test written independently of upstream's
patterns. The expected readings are the 2026-09-28 review's
(``docs/unitedstates-review-2026-09-28/validation/legal-record/current-record-probe.json``
in the workspace), reproduced here through the adapter.
"""

from __future__ import annotations

import socket
import sys
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
# Upstream calls ``find(text=...)`` (cr_parser.py:239), which bs4 4.13+ deprecates.
pytestmark = pytest.mark.filterwarnings("ignore:The 'text' argument to find:DeprecationWarning")

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "record_speeches"
BOUND = 1024 * 1024
KIGGANS = "CREC-2026-09-16-pt1-PgH5835-8"
PLEDGE = "CREC-2026-09-17-pt1-PgH5987-5"
SENATE = "CREC-2026-09-17-pt1-PgS4765-6"
GRANULES = (KIGGANS, PLEDGE, SENATE)


def _body(granule: str) -> bytes:
    return (FIXTURES / f"{granule}.htm").read_bytes()


def _mods(granule: str) -> bytes:
    """The issue MODS excerpt for a granule; the package id is the granule id's first 15 characters."""
    return (FIXTURES / f"{granule[:15]}.mods.excerpt.xml").read_bytes()


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
        ("linebreak", None, "None", None),
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
        ("linebreak", "None", None),
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
@pytest.mark.parametrize("granule", GRANULES)
def test_every_item_is_located_on_the_lines_its_text_came_from(granule: str) -> None:
    """Spans increase without overlap; each span's kept lines join to the text; only dropped lines lie between."""
    document = _read(granule)
    lines = document.source_lines
    assert document.items
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
def test_the_string_none_bioguide_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upstream writes ``"None"`` for a member the MODS gives no bioguide id; the item says ``None``."""
    from congressionalrecord.govinfo import cr_parser

    original = cr_parser.crItem

    def unstated(parser: object) -> object:
        made = original(parser)
        if made.item["kind"] == "speech":
            made.item["speaker_bioguide"] = "None"
        return made

    monkeypatch.setattr(cr_parser, "crItem", unstated)
    speech = next(item for item in _read(KIGGANS).items if item.kind == "speech")
    assert (speech.speaker_bioguide, speech.source_item["speaker_bioguide"]) == (None, "None")


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


# --- refusals ------------------------------------------------------------------


@needs_parser
def test_a_granule_absent_from_the_mods_refuses_by_name() -> None:
    """Upstream's RuntimeError for a missing accessId becomes this package's refusal, naming the granule."""
    absent = "CREC-2026-09-17-pt1-PgH5987-4"
    with pytest.raises(RecordSpeechesError, match=f"granule {absent} is not in the CREC-2026-09-17 MODS") as caught:
        parse_record_speeches(_body(PLEDGE), _mods(PLEDGE), absent, max_html_bytes=BOUND, max_mods_bytes=BOUND)
    assert isinstance(caught.value.__cause__, RuntimeError)


@needs_parser
@pytest.mark.parametrize(
    ("body", "raised"),
    [
        (b"<html><body>no preformatted text</body></html>", "AttributeError"),
        (
            b"<html><body><pre>\n[Congressional Record Volume 172, Number 146 (Wednesday, September 16, 2026)]</pre>",
            "StopIteration",
        ),
    ],
)
def test_a_body_upstream_cannot_read_refuses_rather_than_raising_upstreams_error(body: bytes, raised: str) -> None:
    """No ``<pre>``, or a header cut short: upstream's own exception reaches the caller as a refusal naming the granule."""
    with pytest.raises(RecordSpeechesError, match=f"could not read granule {KIGGANS}: {raised}"):
        _read(KIGGANS, body)


@needs_parser
@pytest.mark.parametrize(
    ("granule", "message"),
    [
        (SENATE, "not a granule of CREC-2026-09-16"),
        ("CREC-2026-09-16-pt1-PgH5835.8", "contains a dot"),
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
        (b"<pre/>", b"x" * 11, BOUND, 10, "CREC package MODS exceeds its 10-byte bound"),
        (b"<pre/>", b"", BOUND, BOUND, "CREC package MODS is empty"),
        (b"<pre/>", b"<mods/>", BOUND, True, "CREC package MODS byte bound must be a positive integer"),
    ],
)
def test_byte_bounds_refuse_before_anything_is_parsed(
    monkeypatch: pytest.MonkeyPatch, html: object, mods: object, html_bound: object, mods_bound: object, message: str
) -> None:
    """A bound, emptiness or type refusal comes first: neither the XML gate nor the parser is reached."""

    def unreachable(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("parsed before the bounds were checked")

    monkeypatch.setattr(record_speeches, "_parser_module", unreachable)
    monkeypatch.setattr(record_speeches, "scan_xml", unreachable)
    with pytest.raises(RecordSpeechesError, match=message):
        parse_record_speeches(html, mods, KIGGANS, max_html_bytes=html_bound, max_mods_bytes=mods_bound)


@needs_parser
@pytest.mark.parametrize(
    ("mods", "message"),
    [
        (b'<!DOCTYPE mods [<!ENTITY x "y">]><mods/>', "permits only an inert external DOCTYPE"),
        (b"<mods xmlns='http://www.loc.gov/mods/v3'/>", r"must state exactly one package accessId; it states \[\]"),
        (b"<other/>", "root is not a MODS record"),
        (
            b"<mods xmlns='http://www.loc.gov/mods/v3'><extension><accessId>CRPT-119hrpt1</accessId></extension></mods>",
            "names CRPT-119hrpt1, not a Congressional Record issue",
        ),
        (b"<mods", "is malformed"),
    ],
)
def test_the_mods_passes_the_bounded_xml_gate_and_names_a_record_issue(mods: bytes, message: str) -> None:
    """The MODS is read by this repository's inert XML scan before upstream sees it."""
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
    assert project["project"]["optional-dependencies"]["record-speeches"] == ["congressionalrecord==2.3.0"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    (package,) = [package for package in lock["package"] if package["name"] == "congressionalrecord"]
    assert package["source"]["git"].endswith(f"?rev={PARSER_PIN}#{PARSER_PIN}")


@needs_parser
def test_upstream_shares_its_speaker_pattern_across_documents_so_parses_are_serialized() -> None:
    """The reason for the lock: upstream's line-kind table is one class-level dict each parse rewrites."""
    from congressionalrecord.govinfo import cr_parser

    _read(KIGGANS)
    assert "KIGGANS" in cr_parser.ParseCRFile.item_types["speech"]["patterns"][0]
    _read(PLEDGE)
    assert "KIGGANS" not in cr_parser.ParseCRFile.item_types["speech"]["patterns"][0]


@needs_parser
def test_concurrent_reads_equal_sequential_reads() -> None:
    """Granules with different speaker tables, read from several threads, read as they do one at a time."""
    expected = {granule: _read(granule) for granule in GRANULES}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda granule: (granule, _read(granule)), GRANULES * 8))
    assert all(document == expected[granule] for granule, document in results)
