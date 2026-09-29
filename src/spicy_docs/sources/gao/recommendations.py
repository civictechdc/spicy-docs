"""GAO's open-recommendations export: every recommendation GAO lists as open, in one CSV, read strictly.

GAO publishes no recommendations API. Its recommendations database exports the open ones as CSV at
``/open-recs2-csv?q=``, an empty query selecting all of them. Measured 2026-09-28
(``supply-2026-09-02/receipts/gao-recommendations-20260928/``): ``text/csv; charset=UTF-8``, 6,771,912 bytes, 5,379
records. A five-line CRLF preamble names the export and states "status as of <time> EST"; then comes the eleven-column
header (``Publication  Number`` has two spaces), then one LF-terminated record per recommendation per agency, the last
with no terminator. Five publication names hold a line break inside their quotes. Two captures twenty minutes apart were
byte-identical, as was a third six hours later, so the stamp says when GAO generated the export, not when it was read.

Ampersands are escaped: each of the export's 637 is spelled ``&amp;``, and it holds no other entity and no bare
ampersand. So exactly ``&amp;`` is read as ``&`` ("Centers for Medicare & Medicaid Services", the spelling ``gao_reports``
titles use); any other ampersand, or an ``&amp;`` left after that (a doubled escape), refuses. The retained bytes keep
GAO's spelling.

GAO numbers each recommendation within its product and states the number at the end of the text: "(Recommendation 4)",
"(Matter for Consideration 1)", "(Matter for Congressional Consideration 2)", and on about twenty records a variant such
as "(Matter 1)", "[Recommendation 1]", "(Recommendations 5)", "(recommendation 1)", "(Recommendation 1.)",
"(Recommendation 19-01)" or an unclosed "(Recommendation 9". :func:`stated_number` reads it; 4,892 of the 5,379 records
state one, and the key is built on it (``schemas/gao_recommendation_tables.py``).

GAO labels the stamp EST year round, but it is Eastern local time: the export captured at 19:05:49 EDT states 7:05 PM,
which as EST would be an hour after the capture. Only the stamp's date is read; the stamp itself is kept verbatim.

Only open recommendations are listed, so an export is a snapshot and a closed recommendation drops out of it. A header,
preamble, status or priority this reader does not know refuses the whole export, because each would change what a
record means; so does a repeated key (:func:`~spicy_docs.schemas.gao_recommendation_tables.gao_recommendation_id`).
A cut export refuses where its bytes can show it: GAO writes no final terminator, so a body ending in CR or LF was cut
at a record boundary; a cut inside a quoted field leaves the CSV unterminated; and an export of no records refuses. A
cut exactly before a record's terminator is only visible against a stated Content-Length, which the Zyte transport
forwards when a target sends one; GAO sent none for this export on 2026-09-29, so that one cut stays unseen here.

The director's phone is a GAO staff number and is never read into a record (owner decision, 2026-09-28: the name
only). The retained bytes keep it as GAO prints it, so anything published from them goes through
:func:`redact_director_phone` first.

``www.gao.gov`` refuses plain clients, so the export comes through Zyte, as product and listing pages do. ``robots.txt``
does not disallow this path (it disallows the database's search page), and one read a day is far inside its 420-second
crawl delay.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from spicy_docs.schemas.gao_recommendation_tables import NUMBER_KINDS, gao_recommendation_id
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import SourceAcquirer, check_byte_bound, check_payload, check_timing, utc_now

if TYPE_CHECKING:
    import httpx

    from spicy_docs.transport.zyte import ZyteProxyRecord

EXPORT_URL: Final = "https://www.gao.gov/open-recs2-csv?q="
MEDIA_TYPES: Final = ("text/csv",)
#: The export's header, spelled as GAO spells it on 2026-09-28; any other header refuses.
HEADER: Final = (
    "Publication Name",
    "Publication  Number",
    "Date Publication Issued",
    "Director Name",
    "Director Phone",
    "Agency",
    "Recommendation",
    "Status",
    "Priority",
    "Comments",
    "Topics",
)
PHONE_COLUMN: Final = "Director Phone"
#: The statuses an open recommendation carries; a closed one leaves the export rather than taking a closed status.
STATUSES: Final = ("Open", "Open--Partially Addressed")
_PRIORITIES: Final = {"Yes": True, "No": False}
#: The export measured 6.46 MiB on 2026-09-28.
DEFAULT_MAX_BYTES: Final = 32 * 1024 * 1024
MAX_BYTES: Final = 128 * 1024 * 1024
_LABEL: Final = "GAO recommendations export"
_MONTHS: Final = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DATE: Final = rf"(?P<month>{'|'.join(_MONTHS)}) (?P<day>\d{{1,2}}), (?P<year>\d{{4}})"
_ISSUED = re.compile(_DATE)
_STAMP = re.compile(rf"{_DATE} at \d{{1,2}}:\d{{2}} [AP]M E[SD]T")
#: The preamble, trailing commas and all; the Source line closes its quote before a space.
_PREAMBLE = re.compile(
    r'"Title: Download of GAO Recommendation Results",*\r?\n'
    r'"Prepared by: GAO",*\r?\n'
    r'"Source: GAO recommendations database, status as of (?P<stamp>[^"\r\n]*)" ?,*\r?\n'
    r"(?:,*\r?\n){2}"
)
#: The number GAO states at the end of a recommendation's text, every spelling the 2026-09-28 export uses.
_STATED_NUMBER = re.compile(
    r"[(\[]\s*(?P<kind>recommendations?|matters?(?: for (?:congressional )?consideration)?)\s*"
    r"(?P<number>\d+(?:-\d+)?)\.?\s*[)\]]?\s*\.?\s*\Z",
    re.IGNORECASE,
)
#: An ampersand that does not open ``&amp;``: another entity, or a bare one the export has never held.
_OTHER_AMPERSAND = re.compile(r"&(?!amp;)")
#: One CSV field and what ends it, over the raw bytes: a quoted field (with anything GAO leaves after its closing
#: quote, as the preamble's ``"Source: ..." ,`` does) or an unquoted one; then a comma, a line end or the end.
_RAW_FIELD = re.compile(rb'("(?:[^"]|"")*"[^,\r\n"]*|[^,\r\n"]*)(,|\r?\n|\Z)')


class GaoRecommendationsSourceError(ValueError):
    """The bytes cannot establish the recommendations GAO lists as open."""


class GaoRecommendationsUnavailableError(GaoRecommendationsSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"{_LABEL} answered HTTP {capture.status_code}")
        self.capture = capture


@dataclass(frozen=True, slots=True)
class GaoRecommendation:
    """One record, unescaped: a recommendation to one agency, at its zero-based ``position`` among the records.

    The director's phone is not read (owner decision, 2026-09-28); the retained bytes keep it."""

    position: int
    publication_title: str
    publication_number: str
    publication_date: date
    director_name: str | None
    agency: str
    recommendation: str
    #: ``recommendation`` or ``matter`` and the number, where the text states one (:func:`stated_number`).
    number_kind: str | None
    number: str | None
    status: str
    priority: bool
    comments: str | None
    topics: str | None

    @property
    def report_id(self) -> str:
        """The GAO product id: the publication number lowercased, as ``gao-26-108061``."""
        return self.publication_number.lower()


@dataclass(frozen=True, slots=True)
class GaoRecommendationsExport:
    """One export: its stamp verbatim, the date the stamp states, and its records in export order."""

    status_as_of: str
    as_of: date
    recommendations: tuple[GaoRecommendation, ...]


def _date(match: re.Match[str]) -> date:
    return date(int(match["year"]), _MONTHS.index(match["month"]) + 1, int(match["day"]))


def stated_number(text: str) -> tuple[str, str] | None:
    """The kind (``recommendation`` or ``matter``) and number GAO states at the end of ``text``, or None.

    Every matter spelling is one kind, since a product numbers its matters in one series, and the number is kept as
    GAO writes it ("19-01"), less a stray period.
    """
    match = _STATED_NUMBER.search(text)
    if match is None:
        return None
    kind = NUMBER_KINDS[0] if match["kind"].lower().startswith("rec") else NUMBER_KINDS[1]
    return kind, match["number"]


def _unescaped(value: str, where: str) -> str:
    """``value`` with each ``&amp;`` read as ``&``; any other ampersand, or one still escaped after, refuses."""
    if _OTHER_AMPERSAND.search(value):
        raise GaoRecommendationsSourceError(f"{where} holds an ampersand not spelled &amp;")
    unescaped = value.replace("&amp;", "&")
    if "&amp;" in unescaped:
        raise GaoRecommendationsSourceError(f"{where} holds a doubled &amp; escape")
    return unescaped


def _record(position: int, cells: list[str]) -> GaoRecommendation:
    where = f"{_LABEL} record {position}"
    if len(cells) != len(HEADER):
        raise GaoRecommendationsSourceError(f"{where} has {len(cells)} fields, not {len(HEADER)}")
    # The director's phone is a staff work number; by owner decision (2026-09-28) it is not read into a record.
    title, number, issued, director, _phone, agency, text, status, priority, comments, topics = (
        _unescaped(cell, where) for cell in cells
    )
    if re.fullmatch(r"\S+", number) is None:
        raise GaoRecommendationsSourceError(f"{where}: publication number {number!r} is not one unspaced word")
    match = _ISSUED.fullmatch(issued)
    try:
        published = None if match is None else _date(match)
    except ValueError:
        published = None
    if published is None:
        raise GaoRecommendationsSourceError(f"{where}: issue date {issued!r} is not a date like 'Sep 28, 2026'")
    for name, value in (("agency", agency), ("recommendation", text)):
        if not value.strip():
            raise GaoRecommendationsSourceError(f"{where}: {name} is empty")
    if status not in STATUSES:
        raise GaoRecommendationsSourceError(f"{where}: status {status!r} is not one of {STATUSES}")
    if priority not in _PRIORITIES:
        raise GaoRecommendationsSourceError(f"{where}: priority {priority!r} is not Yes or No")
    kind, stated = stated_number(text) or (None, None)
    return GaoRecommendation(
        position=position,
        publication_title=title,
        publication_number=number,
        publication_date=published,
        director_name=director or None,
        agency=agency,
        recommendation=text,
        number_kind=kind,
        number=stated,
        status=status,
        priority=_PRIORITIES[priority],
        comments=comments or None,
        topics=topics or None,
    )


def parse_recommendations_export(body: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> GaoRecommendationsExport:
    """Read one export whole, or refuse it whole: no record is dropped and no partial export returned."""
    payload = check_payload(body, max_bytes, label=_LABEL, error_type=GaoRecommendationsSourceError, allow_empty=False)
    if payload.endswith((b"\r", b"\n")):
        raise GaoRecommendationsSourceError(f"{_LABEL} ends in a line break GAO never writes: it was cut")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise GaoRecommendationsSourceError(f"{_LABEL} is not UTF-8") from None
    preamble = _PREAMBLE.match(text)
    if preamble is None:
        raise GaoRecommendationsSourceError(f"{_LABEL} preamble differs from the one measured")
    stamp = _STAMP.fullmatch(preamble["stamp"])
    if stamp is None:
        raise GaoRecommendationsSourceError(f"{_LABEL} status as of {preamble['stamp']!r} is not a stamp this reads")
    try:
        rows = list(csv.reader(io.StringIO(text[preamble.end() :], newline=""), strict=True))
    except csv.Error as error:
        raise GaoRecommendationsSourceError(f"{_LABEL} is not well-formed CSV: {error}") from None
    if not rows or tuple(rows[0]) != HEADER:
        raise GaoRecommendationsSourceError(f"{_LABEL} header differs from the one measured: {rows[:1]!r}")
    recommendations = tuple(_record(position, cells) for position, cells in enumerate(rows[1:]))
    if not recommendations:
        raise GaoRecommendationsSourceError(f"{_LABEL} holds no record; GAO lists thousands open")
    keys: dict[str, int] = {}
    for item in recommendations:
        key = gao_recommendation_id(
            item.report_id, item.agency, item.recommendation, kind=item.number_kind, number=item.number
        )
        if (first := keys.setdefault(key, item.position)) != item.position:
            raise GaoRecommendationsSourceError(f"{_LABEL} record {item.position} repeats the key of record {first}")
    return GaoRecommendationsExport(preamble["stamp"], _date(stamp), recommendations)


def redact_director_phone(body: bytes) -> tuple[bytes, int]:
    """``body`` with every Director Phone field emptied and every other byte kept, and how many held a value.

    The header is the first record naming :data:`PHONE_COLUMN`, found by name so that a refused export whose header
    moved can still be redacted; the preamble before it is kept whole. An emptied field is spelled as GAO spells an
    empty one, nothing between its commas. Bytes that are not CSV, or name no such column, refuse, since then no field
    can be proved to be the phone; so does a record whose field count differs from the header's, since the phone is
    found by position and a wrong width would blank another field and keep it.
    """
    pieces: list[bytes] = []
    kept_from = position = index = emptied = ordinal = 0
    column: int | None = None
    width = 0
    names: list[bytes] = []
    while position < len(body):
        match = _RAW_FIELD.match(body, position)
        if match is None:
            raise GaoRecommendationsSourceError(f"{_LABEL} is not CSV at byte {position}; no phone can be found")
        field, separator = match.group(1), match.group(2)
        if column is None:
            names.append(field.strip(b'"'))
        elif index == column and field:
            pieces.append(body[kept_from : match.start(1)])
            kept_from = match.end(1)
            emptied += field != b'""'
        index += 1
        if separator != b",":
            if column is None and PHONE_COLUMN.encode() in names:
                column, width = names.index(PHONE_COLUMN.encode()), len(names)
            elif column is not None:
                if index != width:
                    raise GaoRecommendationsSourceError(
                        f"{_LABEL} record {ordinal} holds {index} fields, not the header's {width}; "
                        "no field can be proved to be the phone"
                    )
                ordinal += 1
            names, index = [], 0
        position = match.end()
    if column is None:
        raise GaoRecommendationsSourceError(f"{_LABEL} names no {PHONE_COLUMN!r} column; no phone can be found")
    pieces.append(body[kept_from:])
    return b"".join(pieces), emptied


@dataclass(frozen=True, slots=True)
class GaoRecommendationsBudget:
    """Bounds for the one capture; the Zyte spend is the transport's own ``ZyteBudget``."""

    max_bytes: int = DEFAULT_MAX_BYTES
    timeout_seconds: float = 240.0

    def __post_init__(self) -> None:
        check_byte_bound(self.max_bytes, "max_bytes", MAX_BYTES)
        check_timing(self.timeout_seconds, 0)


class GaoRecommendationsAcquirer(SourceAcquirer):
    """One request for the whole export; the transport is Zyte's, injected by the caller."""

    def __init__(
        self,
        *,
        budget: GaoRecommendationsBudget,
        transport: httpx.BaseTransport,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, GaoRecommendationsBudget):
            raise TypeError("budget must be a GaoRecommendationsBudget")
        self.budget = budget
        super().__init__(
            max_requests=1,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=0,
            user_agent="spicy-docs-gao-recommendations/1.0",
            label=_LABEL,
            error_type=GaoRecommendationsSourceError,
            context_key="gao_recommendations_acquisition",
            transport=transport,
            clock=clock,
        )

    def acquire_export(self) -> tuple[GaoRecommendationsExport, CapturedBodyResponse]:
        def parse(response: CapturedBodyResponse, limit: int) -> GaoRecommendationsExport:
            if response.status_code != 200:
                raise GaoRecommendationsSourceError(f"{_LABEL} answered HTTP {response.status_code}")
            return parse_recommendations_export(response.body, max_bytes=limit)

        return self.capture_validated(
            EXPORT_URL,
            media_types=MEDIA_TYPES,
            parse=parse,
            max_bytes=self.budget.max_bytes,
            unavailable=GaoRecommendationsUnavailableError,
            context={"operation": "open-recommendations-export", "url": EXPORT_URL},
        )


def fetch_export(
    *,
    store: Path,
    receipts: Path,
    budget: GaoRecommendationsBudget,
    transport: httpx.BaseTransport,
    proxy_record: Callable[[str], ZyteProxyRecord | None] = lambda _url: None,
    credential: str = "",
    clock: Callable[[], datetime] = utc_now,
) -> int:
    """Capture the export into ``store`` and append one receipt row to ``receipts``; 0 when read, 1 when refused.

    A refusal is a ``failed`` row carrying any refused bytes, which ``store`` keeps too; ``credential`` is scrubbed
    from every row. ``proxy_record`` is the Zyte transport's ``record_for``, naming the provider request. The store
    keeps GAO's bytes whole, director phones included: it is an operator's local evidence, not a publication.
    """
    from rulespec_artifacts import LocalBlobWriter

    from spicy_docs.reading.refusals import retain_refused_response
    from spicy_docs.transport.credentials import scrub_credential

    run_id = str(uuid4())
    with receipts.open("a", encoding="utf-8") as sink:

        def emit(kind: str, **value: object) -> None:
            row = json.dumps({"kind": kind, "run_id": run_id, **value}, ensure_ascii=False)
            sink.write(scrub_credential(row, credential) + "\n")

        try:
            with GaoRecommendationsAcquirer(budget=budget, transport=transport, clock=clock) as acquirer:
                export, capture = acquirer.acquire_export()
            stored = LocalBlobWriter(store).put(
                [capture.body], max_bytes=budget.max_bytes, expected_digest=capture.sha256
            )
        except Exception as error:  # noqa: BLE001 - recorded with its evidence; the next run tries again
            detail: dict[str, object] = {
                "request_url": EXPORT_URL,
                "error_type": type(error).__name__,
                # Scrub before truncating, or a credential's prefix could survive.
                "error": scrub_credential(str(error), credential)[:1000],
            }
            refused = retain_refused_response(error, store=store, max_bytes=budget.max_bytes, credential=credential)
            if refused is not None:
                detail["refused_evidence"] = refused
            emit("failed", **detail)
            return 1
        record = proxy_record(capture.requested_url)
        emit(
            "export",
            request_url=capture.requested_url,
            resolved_url=capture.resolved_url,
            status=capture.status_code,
            content_type=capture.content_type,
            observed_at=capture.observed_at,
            bytes=capture.byte_size,
            sha256=capture.sha256,
            blob_path=stored.object_key,
            proxied_client=None if record is None else record.proxied_client,
            proxy_mode=None if record is None else record.mode,
            zyte_request_id=None if record is None else record.zyte_request_id,
            status_as_of=export.status_as_of,
            as_of=export.as_of.isoformat(),
            recommendations=len(export.recommendations),
        )
    return 0


def read_export(
    *, receipts: Path, store: Path, max_bytes: int = MAX_BYTES
) -> tuple[GaoRecommendationsExport, CapturedBodyResponse]:
    """Re-read the latest retained export offline: its bytes must equal its receipt, then they are parsed again.

    The store refuses bytes that differ from their content address, so the receipt's digest is proved on open; its
    size and request URL are checked here.
    """
    from rulespec_artifacts import LocalBlobSource

    rows = [json.loads(line) for line in receipts.read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next((row for row in reversed(rows) if row.get("kind") == "export"), None)
    if row is None:
        raise GaoRecommendationsSourceError(f"{receipts} holds no retained export")
    with LocalBlobSource(store).open(row["sha256"]) as stream:
        body = stream.read(max_bytes + 1)
    capture = CapturedBodyResponse(
        requested_url=row["request_url"],
        resolved_url=row["resolved_url"],
        status_code=row["status"],
        content_type=row["content_type"],
        observed_at=row["observed_at"],
        body=body,
    )
    if capture.byte_size != row["bytes"]:
        raise GaoRecommendationsSourceError("retained export differs from its receipt")
    if capture.requested_url != EXPORT_URL:
        raise GaoRecommendationsSourceError("retained export was requested at another URL")
    return parse_recommendations_export(body, max_bytes=max_bytes), capture


def _fetch(args: argparse.Namespace) -> int:
    from spicy_docs.sources.zyte import ZyteHttpFetcher, require_zyte_token_from_environment
    from spicy_docs.transport.credentials import scrub_credential
    from spicy_docs.transport.zyte import ZyteBudget, ZyteTransport

    token = ""
    try:
        budget = GaoRecommendationsBudget(max_bytes=args.max_bytes, timeout_seconds=args.timeout_seconds)
        token = require_zyte_token_from_environment()
        transport = ZyteTransport(
            ZyteHttpFetcher(token=token),
            max_bytes=budget.max_bytes,
            timeout_seconds=budget.timeout_seconds,
            budget=ZyteBudget(1),
        )
        return fetch_export(
            store=args.store,
            receipts=args.receipts,
            budget=budget,
            transport=transport,
            proxy_record=transport.record_for,
            credential=token,
        )
    except (ValueError, OSError) as error:
        print(scrub_credential(str(error), token), file=sys.stderr)
        return 1


def _read(args: argparse.Namespace) -> int:
    export, capture = read_export(receipts=args.receipts, store=args.store)
    with args.output.open("x", encoding="utf-8") if args.output else nullcontext(sys.stdout) as out:
        for item in export.recommendations:
            out.write(json.dumps(asdict(item), ensure_ascii=False, default=date.isoformat) + "\n")
    summary = {
        "sha256": capture.sha256,
        "status_as_of": export.status_as_of,
        "recommendations": len(export.recommendations),
        "statuses": Counter(item.status for item in export.recommendations),
        "priority": sum(item.priority for item in export.recommendations),
    }
    print(json.dumps(summary), file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture or re-read GAO's open-recommendations export")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Capture the export through Zyte (one request) with a receipt")
    fetch.add_argument("--store", type=Path, required=True, help="Content-addressed blob store")
    fetch.add_argument("--receipts", type=Path, required=True, help="JSONL receipts, appended")
    fetch.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    fetch.add_argument("--timeout-seconds", type=float, default=240.0)
    read = commands.add_parser("read", help="Verify the latest retained export offline and print its records as JSONL")
    read.add_argument("--store", type=Path, required=True)
    read.add_argument("--receipts", type=Path, required=True)
    read.add_argument("--output", type=Path, help="Create a new JSONL file; defaults to stdout")
    args = parser.parse_args(argv)
    return _fetch(args) if args.command == "fetch" else _read(args)


__all__ = [
    "DEFAULT_MAX_BYTES",
    "EXPORT_URL",
    "HEADER",
    "MAX_BYTES",
    "PHONE_COLUMN",
    "STATUSES",
    "GaoRecommendation",
    "GaoRecommendationsAcquirer",
    "GaoRecommendationsBudget",
    "GaoRecommendationsExport",
    "GaoRecommendationsSourceError",
    "GaoRecommendationsUnavailableError",
    "fetch_export",
    "parse_recommendations_export",
    "read_export",
    "redact_director_phone",
    "stated_number",
]


if __name__ == "__main__":
    raise SystemExit(main())
