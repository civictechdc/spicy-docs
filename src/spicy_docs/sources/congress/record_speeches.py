"""Read one Congressional Record granule's speech turns with the @unitedstates parser, offline.

The parser is ``congressionalrecord`` (https://github.com/unitedstates/congressional-record),
installed at a pinned fork commit by the ``record-speeches`` extra; nothing here
reimplements it. This module supplies what it leaves to its caller: bounded
UTF-8 inputs written into the directory layout it reads, a refusal in this
package's terms wherever it raises, a document that reports a partial parse as
partial, and a source line span for each item it emits, which it does not
record. Nothing here imports the parser at module scope, so the rest of
``spicy_docs`` imports without it.

The MODS is either the issue's package MODS or the granule's own, which is
what ``GovInfoBodyAcquirer.acquire_granule`` retains; upstream reads the
granule's record the same way from both. It is parsed once
(:func:`read_record_issue`) and granules are read against it
(:meth:`RecordIssue.speeches`). Upstream reads the MODS with BeautifulSoup:
measured on 2026-09-28, 0.4-0.7 s for the 3.6 MB CREC-2026-09-16 package MODS
against 1-9 ms per granule, so a loop over one issue's granules reads its
package MODS once, and a granule's own MODS (a few kilobytes) avoids that cost.
"""

from __future__ import annotations

import hashlib
import locale
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any

from spicy_docs.sources.govinfo.bodies import GovInfoBodySourceError, parse_granule_identity, parse_package_id
from spicy_docs.sources.govinfo.mods import GovInfoModsError, parse_govinfo_mods
from spicy_docs.transport.source_acquirer import check_payload

#: The fork commit ``pyproject.toml`` pins and ``uv.lock`` resolves; a test holds the three together.
PARSER_PIN = "7949151e91d2a33bcde572864952789f741be2c7"
EXTRA_REQUIRED = (
    "Congressional Record speech turns need the 'record-speeches' extra: uv sync --frozen --extra record-speeches"
)
LOCATED = "located"
UNLOCATED = "unlocated"

_MODS_LABEL = "CREC MODS"
_HTML_LABEL = "CREC granule HTML"
# validate_package_mods's element bound; the 3.6 MB CREC-2026-09-16 package
# MODS holds 35,978 elements (measured 2026-09-28).
_MAX_MODS_ELEMENTS = 200_000
# What upstream raises from a document it cannot read: a missing accessId
# (RuntimeError), a missing <pre>, searchTitle or granuleClass (AttributeError),
# a body too short for its header (StopIteration), an unmatched date or time
# (AttributeError, TypeError, ValueError, LookupError). Named rather than
# ``Exception``, so a failure of any other kind propagates as itself.
_UPSTREAM_FAILURES = (AttributeError, LookupError, RuntimeError, StopIteration, TypeError, ValueError)
# Upstream keeps its line-kind table on the class and writes each document's
# speaker pattern into it (cr_parser.py:259), which crItem then reads while it
# parses (subclasses.py:21-26). Two parses in two threads would read each
# other's speakers, so one parse runs at a time.
_PARSE_LOCK = threading.Lock()


class RecordSpeechesError(ValueError):
    """A granule and its MODS cannot be read into speech turns as given."""


def _parser_module() -> Any:
    """Upstream's ``cr_parser``, or a refusal naming the extra that supplies it."""
    try:
        from congressionalrecord.govinfo import cr_parser
    except ModuleNotFoundError as error:
        raise RecordSpeechesError(EXTRA_REQUIRED) from error
    return cr_parser


def parser_available() -> bool:
    """Whether the ``record-speeches`` extra is installed. Tests skip on this rather than fail."""
    try:
        _parser_module()
    except RecordSpeechesError:
        return False
    return True


def _frozen(value: object) -> Any:
    """The same value, read-only all the way down: mappings become proxies and lists tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_frozen(item) for item in value)
    return value


def _stated(value: object) -> Any:
    """Upstream spells an absent value as the string ``"None"``; this is ``None`` for both spellings."""
    return None if value is None or value == "None" else value


@dataclass(frozen=True, slots=True)
class RecordSpeechItem:
    """One item upstream emitted, with the source lines it came from.

    ``speaker`` is upstream's value exactly, including its ``"Unknown"`` and
    ``"None"`` placeholders; ``speaker_bioguide`` is the id the MODS states for
    that speaker, ``None`` where it states none. ``turn`` is upstream's speech
    counter and ``None`` on every other kind. ``source_item`` is the whole item
    as upstream emitted it.

    ``line_start``/``line_end`` are 0-based, inclusive indexes into
    :attr:`RecordSpeechDocument.source_lines`. Upstream drops whitespace-only,
    ``{time}`` and ``[[Page]]`` lines from an item's text, so the span can hold
    lines the text does not; every other line in it is a line of the text, in
    order. Both are ``None`` when ``coordinates_status`` is ``unlocated``.
    """

    item_index: int
    kind: str
    turn: int | None
    speaker: str
    speaker_bioguide: str | None
    text: str | None
    line_start: int | None
    line_end: int | None
    coordinates_status: str
    source_item: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RecordSpeechDocument:
    """One granule as upstream read it, and this repository's account of the bytes.

    ``parse_status`` is upstream's own: ``partial`` means an item raised, the
    items before it are kept, and ``parse_error`` holds the exception's type,
    message and the line being read. ``lines_exhausted`` says whether upstream
    read to the end of the text. ``header`` is upstream's header mapping, or
    ``None`` where the granule's first lines did not match it; ``vol``, ``num``,
    ``chamber``, ``pages`` and ``extension`` read from it. ``related_*`` are the
    bill, law, U.S. Code and Statutes at Large references upstream read from
    the granule's MODS record, unmodified. ``source_lines`` is the granule's
    ``<pre>`` text split the way upstream split it, up to the last line it read.
    """

    granule_id: str
    package_id: str
    parse_status: str
    parse_error: Mapping[str, object] | None
    lines_exhausted: bool
    header: Mapping[str, object] | None
    title: str | None
    doc_title: str | None
    related_bills: tuple[Mapping[str, object], ...]
    related_laws: tuple[Mapping[str, object], ...]
    related_usc: tuple[Mapping[str, object], ...]
    related_statute: tuple[Mapping[str, object], ...]
    items: tuple[RecordSpeechItem, ...]
    source_lines: tuple[str, ...]
    html_sha256: str
    mods_sha256: str
    parser_pin: str

    def _header(self, key: str) -> Any:
        return None if self.header is None else self.header.get(key)

    @property
    def vol(self) -> str | None:
        return self._header("vol")

    @property
    def num(self) -> str | None:
        return self._header("num")

    @property
    def chamber(self) -> str | None:
        return self._header("chamber")

    @property
    def pages(self) -> str | None:
        return self._header("pages")

    @property
    def extension(self) -> bool | None:
        return self._header("extension")


def _decoded(body: bytes, *, label: str) -> str:
    """GovInfo serves both inputs as UTF-8 with no declaration saying otherwise; anything else refuses."""
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RecordSpeechesError(f"{label} is not UTF-8") from error


def _write_for_upstream(path: Path, text: str, *, label: str) -> None:
    """Write ``text`` where upstream will ``open(path, "r")`` it, and prove it reads back unchanged.

    Upstream opens both files in text mode with no encoding, which reads the
    locale's encoding with universal newlines. Writing in that encoding is what
    makes its reading the retained text; reading back through the same call is
    the proof. A character the locale cannot encode, or a carriage return that
    universal newlines would fold, refuses rather than reaching the parser as
    different text. Every CREC body and MODS the supply corpus retained on
    2026-09-28 is ASCII with no carriage return, so neither refusal has been
    observed (``docs/sources/congressional-record-speeches.md``).
    """
    encoding = locale.getpreferredencoding(False)
    try:
        path.write_text(text, encoding=encoding)
    except UnicodeEncodeError as error:
        raise RecordSpeechesError(f"{label} cannot be written in the locale encoding {encoding}") from error
    try:
        # No encoding and no newline argument: upstream's own call (cr_parser.py:18 and :277).
        with open(path) as readback:
            unchanged = readback.read() == text
    except UnicodeDecodeError:
        unchanged = False
    if not unchanged:
        raise RecordSpeechesError(f"{label} does not read back unchanged through the parser's text-mode open")


def _crec_package(value: str) -> str:
    try:
        identity = parse_package_id(value)
    except GovInfoBodySourceError as error:
        raise RecordSpeechesError(f"{_MODS_LABEL} does not name a package: {error}") from error
    if identity.collection != "CREC":
        raise RecordSpeechesError(f"{_MODS_LABEL} names {identity.package_id}, not a Congressional Record issue")
    return identity.package_id


def _mods_identity(mods: bytes, *, max_bytes: int) -> tuple[str, str | None]:
    """The package id, and the granule id when this is a granule's own MODS, read as the body routes read them.

    Both shapes state their own accessId in the root's ``extension``. A
    granule's MODS also states its host package in a ``relatedItem
    type="host"``, and that is how the shape is told from the document: with a
    host, the root names a granule of it; without one, the root names the
    package. The read goes through this repository's bounded, entity-refusing
    MODS mapping before upstream's parser sees the bytes.
    """
    try:
        record = parse_govinfo_mods(mods, max_bytes=max_bytes, max_elements=_MAX_MODS_ELEMENTS).package
    except GovInfoModsError as error:
        raise RecordSpeechesError(f"{_MODS_LABEL} is unreadable: {error}") from error
    stated, hosts = set(record.access_ids), set(record.host_access_ids)
    if len(stated) != 1:
        raise RecordSpeechesError(f"{_MODS_LABEL} must state exactly one accessId; it states {sorted(stated)}")
    (own,) = stated
    if not hosts:
        return _crec_package(own), None
    if len(hosts) != 1:
        raise RecordSpeechesError(f"{_MODS_LABEL} must state exactly one host package; it states {sorted(hosts)}")
    package = _crec_package(hosts.pop())
    if not own.startswith(f"{package}-"):
        raise RecordSpeechesError(f"{_MODS_LABEL} describes {own}, which is not a granule of its host {package}")
    return package, own


def _line_recording(parse_file: Any) -> Any:
    """Upstream's file parser, recording the lines it reads and the line its first item starts on.

    Both hooks call upstream's own method and only watch it: ``read_htm_file``
    is upstream's reader, so the lines are the ones it split rather than a
    second reading, and ``get_title`` is where upstream stops consuming header
    and title lines -- the line it stopped on is the first item's first line.
    """

    class LineRecordingParse(parse_file):
        def read_htm_file(self) -> Iterator[str]:
            self.lines_read = []
            for line in super().read_htm_file():
                self.lines_read.append(line)
                yield line

        def get_title(self) -> Any:
            title = super().get_title()
            self.first_item_line = len(self.lines_read) - 1 if self.lines_remaining else None
            return title

    return LineRecordingParse


def _span(
    lines: Sequence[str], wanted: Sequence[str], cursor: int, *, skipped: Callable[[str], bool], exact: bool
) -> tuple[int, int] | None:
    """Where ``wanted`` sits from ``cursor`` on, passing over only lines upstream drops, or ``None``.

    Upstream builds an item from the line that ended the previous one and then
    every following line up to the next break, dropping the lines its skip
    patterns match. So between two lines of one item, and between one item's
    last line and the next item's first, only dropped lines can occur. A
    dropped line is decided by its content alone, so no dropped line equals a
    kept one and the first equal line is the one upstream read. ``exact`` holds
    the first item to the line upstream's title scan stopped on.
    """
    position = cursor
    start: int | None = None
    for line in wanted:
        while not exact and position < len(lines) and lines[position] != line and skipped(lines[position]):
            position += 1
        if position == len(lines) or lines[position] != line:
            return None
        if start is None:
            start = position
        exact = False
        position += 1
    return None if start is None else (start, position - 1)


def _locate(
    lines: Sequence[str], items: Sequence[Mapping[str, Any]], anchor: int | None, skipped: Callable[[str], bool]
) -> list[tuple[int, int] | None]:
    """Each item's span, in order and never backtracking; once one is not found, none after it is guessed."""
    spans: list[tuple[int, int] | None] = []
    cursor = anchor
    for index, item in enumerate(items):
        text = item.get("text")
        span = None
        if cursor is not None and isinstance(text, str):
            span = _span(lines, text.split("\n"), cursor, skipped=skipped, exact=index == 0)
        spans.append(span)
        cursor = None if span is None else span[1] + 1
    return spans


class RecordIssue:
    """One MODS, parsed once by upstream, against which granules of its issue are read.

    ``granule_id`` is the granule a granule's own MODS describes, the only one
    it can read, and ``None`` for a package MODS, which reads any of its issue's.
    """

    __slots__ = ("_directory", "granule_id", "mods_sha256", "package_id")

    def __init__(self, package_id: str, granule_id: str | None, mods_sha256: str, directory: Any) -> None:
        self.package_id = package_id
        self.granule_id = granule_id
        self.mods_sha256 = mods_sha256
        self._directory = directory

    def _granule_id(self, granule_id: object) -> str:
        try:
            identity = parse_granule_identity(self.package_id, granule_id)
        except GovInfoBodySourceError as error:
            raise RecordSpeechesError(f"granule id is not a GovInfo granule id: {error}") from error
        value = identity.granule_id
        if not value.startswith(f"{self.package_id}-"):
            raise RecordSpeechesError(f"granule {value} is not a granule of {self.package_id}")
        if self.granule_id is not None and value != self.granule_id:
            raise RecordSpeechesError(f"granule {value} is not the granule this MODS describes, {self.granule_id}")
        # Upstream takes the accessId it looks up from the file name, up to the
        # first dot (cr_parser.py:525); a dotted id would be looked up truncated.
        if "." in value:
            raise RecordSpeechesError(f"granule {value} contains a dot, which the parser cannot address")
        return value

    def speeches(self, granule_html: bytes, granule_id: str, *, max_html_bytes: int) -> RecordSpeechDocument:
        """Read one granule's retained HTML body into a :class:`RecordSpeechDocument`."""
        body = check_payload(
            granule_html, max_html_bytes, label=_HTML_LABEL, error_type=RecordSpeechesError, allow_empty=False
        )
        granule = self._granule_id(granule_id)
        text = _decoded(body, label=_HTML_LABEL)
        parser_class = _line_recording(_parser_module().ParseCRFile)
        with TemporaryDirectory(prefix="spicy-docs-record-speeches-") as directory:
            path = Path(directory) / f"{granule}.htm"
            _write_for_upstream(path, text, label=_HTML_LABEL)
            with _PARSE_LOCK:
                try:
                    parser = parser_class(str(path), self._directory)
                except _UPSTREAM_FAILURES as error:
                    if isinstance(error, RuntimeError) and str(error) == f"{granule} doesn't have accessid tag":
                        raise RecordSpeechesError(f"granule {granule} is not in the {self.package_id} MODS") from error
                    raise RecordSpeechesError(
                        f"the parser could not read granule {granule}: {type(error).__name__}: {error}"
                    ) from error
        return self._document(parser, granule, body)

    def _document(self, parser: Any, granule: str, body: bytes) -> RecordSpeechDocument:
        crdoc = parser.crdoc
        status = crdoc.get("parse_status")
        error = crdoc.get("parse_error")
        # Without this field a partial parse looks complete; it is the fork's
        # change, so its absence means some other build is installed.
        if status not in ("complete", "partial"):
            raise RecordSpeechesError(
                f"the installed parser does not report parse completion for {granule}; {EXTRA_REQUIRED}"
            )
        if (status == "partial") != isinstance(error, Mapping):
            raise RecordSpeechesError(f"the parser reports {status} for {granule} with parse_error {error!r}")
        patterns = tuple(parser.skip_items)

        def skipped(line: str) -> bool:
            return any(re.match(pattern, line) for pattern in patterns)

        lines = tuple(parser.lines_read)
        content = crdoc["content"]
        spans = _locate(lines, content, parser.first_item_line, skipped)
        items = tuple(
            RecordSpeechItem(
                item_index=index,
                kind=item["kind"],
                turn=item["turn"] if item["kind"] == "speech" else None,
                speaker=item["speaker"],
                speaker_bioguide=_stated(item.get("speaker_bioguide")),
                text=item["text"],
                line_start=None if span is None else span[0],
                line_end=None if span is None else span[1],
                coordinates_status=UNLOCATED if span is None else LOCATED,
                source_item=_frozen(item),
            )
            for index, (item, span) in enumerate(zip(content, spans, strict=True))
        )
        header = crdoc.get("header")
        return RecordSpeechDocument(
            granule_id=granule,
            package_id=self.package_id,
            parse_status=status,
            parse_error=None if error is None else _frozen(error),
            lines_exhausted=not parser.lines_remaining,
            header=_frozen(header) if header else None,
            title=crdoc.get("title"),
            doc_title=_stated(crdoc.get("doc_title")),
            related_bills=_frozen(crdoc.get("related_bills", ())),
            related_laws=_frozen(crdoc.get("related_laws", ())),
            related_usc=_frozen(crdoc.get("related_usc", ())),
            related_statute=_frozen(crdoc.get("related_statute", ())),
            items=items,
            source_lines=lines,
            html_sha256="sha256:" + hashlib.sha256(body).hexdigest(),
            mods_sha256=self.mods_sha256,
            parser_pin=PARSER_PIN,
        )


def read_record_issue(mods: bytes, *, max_mods_bytes: int) -> RecordIssue:
    """Parse one CREC MODS once: an issue's package MODS, for any of its granules, or one granule's own."""
    exact = check_payload(mods, max_mods_bytes, label=_MODS_LABEL, error_type=RecordSpeechesError, allow_empty=False)
    cr_parser = _parser_module()
    package_id, granule_id = _mods_identity(exact, max_bytes=max_mods_bytes)
    text = _decoded(exact, label=_MODS_LABEL)
    with TemporaryDirectory(prefix="spicy-docs-record-issue-") as directory:
        _write_for_upstream(Path(directory) / "mods.xml", text, label=_MODS_LABEL)
        try:
            # Upstream reads the file once, in the constructor, and keeps only
            # the parsed tree, so the directory can go when this block ends.
            parsed = cr_parser.ParseCRDir(directory)
        except _UPSTREAM_FAILURES as error:
            raise RecordSpeechesError(f"the parser could not read {_MODS_LABEL} {package_id}: {error}") from error
    return RecordIssue(package_id, granule_id, "sha256:" + hashlib.sha256(exact).hexdigest(), parsed)


def parse_record_speeches(
    granule_html: bytes,
    mods: bytes,
    granule_id: str,
    *,
    max_html_bytes: int,
    max_mods_bytes: int,
) -> RecordSpeechDocument:
    """Read one granule against its issue's package MODS or its own MODS; both bounds are checked first.

    Reading many granules of one issue against its package MODS, call
    :func:`read_record_issue` once and :meth:`RecordIssue.speeches` per granule.
    """
    check_payload(granule_html, max_html_bytes, label=_HTML_LABEL, error_type=RecordSpeechesError, allow_empty=False)
    issue = read_record_issue(mods, max_mods_bytes=max_mods_bytes)
    return issue.speeches(granule_html, granule_id, max_html_bytes=max_html_bytes)


__all__ = [
    "EXTRA_REQUIRED",
    "LOCATED",
    "PARSER_PIN",
    "UNLOCATED",
    "RecordIssue",
    "RecordSpeechDocument",
    "RecordSpeechItem",
    "RecordSpeechesError",
    "parse_record_speeches",
    "parser_available",
    "read_record_issue",
]
