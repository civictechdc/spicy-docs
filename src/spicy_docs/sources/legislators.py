"""Community legislators crosswalk: bioguide, Senate LIS and FEC candidate ids.

``unitedstates/congress-legislators`` is a civil-society project, not a
publisher, so a capture's pin is what was actually read (bytes, SHA-256,
observed time), never a stated release; see ``docs/sources/legislators.md``
for the full measurement basis, the civil-society caveat and the cadence
check. Two keyless files matter here:

- ``legislators-current.json`` -- everyone serving today.
- ``legislators-historical.json`` -- everyone who has left, and the only
  route this package has to a *former* senator's LIS id (see
  ``docs/decisions.md``, "Congress.gov and GovInfo collections are each one
  family", final paragraph).

FEC candidate ids come in two real shapes: a congressional id embeds the
member's state (``S8WA00194``), a presidential id does not
(``P80003023`` -- Mark Warner, a *sitting* senator in the current file).
``_fec_id_shape_ok`` accepts both; accepting only the first would refuse
every record of anyone who ever filed for President.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from spicy_docs.reading.json_input import load_bounded_json
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    import httpx

LEGISLATORS_CURRENT_URL = "https://unitedstates.github.io/congress-legislators/legislators-current.json"
LEGISLATORS_HISTORICAL_URL = "https://unitedstates.github.io/congress-legislators/legislators-historical.json"

# Measured 2026-09-19: current is 1,468,926 bytes / 539 records; historical is
# 13,483,039 bytes / 12,231 records (522,454 JSON nodes). Defaults keep
# headroom over the measured size; MAX_HISTORICAL_BYTES is the 16 MiB bound
# this source is scoped to (docs/sources/legislators.md), not just a default.
DEFAULT_MAX_CURRENT_BYTES = 4 * 1024**2
MAX_CURRENT_BYTES = 8 * 1024**2
DEFAULT_MAX_HISTORICAL_BYTES = 16 * 1024**2
MAX_HISTORICAL_BYTES = 16 * 1024**2
DEFAULT_MAX_RECORDS = 20_000
MAX_RECORDS_CAP = 50_000
_MAX_JSON_NODES = 1_000_000
_MAX_JSON_DEPTH = 16

MEDIA_TYPES = ("application/json",)

_LIS_ID = re.compile(r"S\d{3}")
# Congressional: office letter, decade digit, state postal abbreviation, 5-digit sequence (e.g. S8WA00194).
_FEC_CONGRESSIONAL_ID = re.compile(r"[HS]\d[A-Z]{2}\d{5}")
# Presidential: no state, so no letters after the office letter (e.g. P80003023).
_FEC_PRESIDENTIAL_ID = re.compile(r"P\d{8}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TERM_TYPES = ("rep", "sen")
_ID_INT_FIELDS = ("icpsr", "govtrack")

# Shape rules for simple scalar string fields: (key, required, pattern-or-None-for-"just non-empty", message).
_ID_STRING_RULES = (
    ("bioguide", True, None, "needs a non-empty id.bioguide"),
    ("lis", False, _LIS_ID, "has an id.lis not shaped like S###"),
    ("opensecrets", False, None, "has a non-string id.opensecrets"),
    ("wikidata", False, None, "has a non-string id.wikidata"),
)
_NAME_STRING_RULES = (
    ("first", True, None, "needs a non-empty name.first"),
    ("last", True, None, "needs a non-empty name.last"),
)
_TERM_STRING_RULES = (
    ("start", True, _ISO_DATE, "terms[{i}].start must be an ISO date"),
    ("end", True, _ISO_DATE, "terms[{i}].end must be an ISO date"),
    ("state", True, None, "terms[{i}] needs a non-empty state"),
    ("party", False, None, "terms[{i}] has a non-string party"),
)


class LegislatorsSourceError(ValueError):
    """The response cannot establish a community legislators crosswalk file."""


class LegislatorsUnavailableError(LegislatorsSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"community legislators source answered HTTP {capture.status_code}")
        self.capture = capture


@dataclass(frozen=True, slots=True)
class Term:
    """One publisher term row. ``party`` is ``None`` for the party-less 1st Congress, a real value."""

    type: str
    start: str
    end: str
    state: str
    party: str | None


@dataclass(frozen=True, slots=True)
class Legislator:
    """One crosswalked person. ``fec`` keeps the publisher's list order and can hold both id shapes."""

    bioguide: str
    lis: str | None
    fec: tuple[str, ...]
    icpsr: int | None
    govtrack: int | None
    opensecrets: str | None
    wikidata: str | None
    name_first: str
    name_last: str
    terms: tuple[Term, ...]


@dataclass(frozen=True, slots=True)
class LegislatorsFile:
    """Records in file order, plus lookup indexes. An FEC id or LIS id names at most one record here."""

    records: tuple[Legislator, ...]
    by_bioguide: Mapping[str, Legislator]
    by_lis: Mapping[str, Legislator]
    by_fec: Mapping[str, Legislator]


def _fec_id_shape_ok(value: str) -> bool:
    """Accept both real FEC candidate id shapes this crosswalk carries; see module docstring."""
    return bool(_FEC_CONGRESSIONAL_ID.fullmatch(value) or _FEC_PRESIDENTIAL_ID.fullmatch(value))


def _string(
    container: dict, key: str, message: str, *, required: bool, pattern: re.Pattern[str] | None, index: int
) -> str | None:
    """Apply one (key, required, pattern, message) shape rule; ``None`` passes through when not required."""
    value = container.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or (pattern is not None and not pattern.fullmatch(value)):
        raise LegislatorsSourceError(f"community legislators record {index} {message}: {value!r}")
    return value


def _optional_int(value: object, index: int, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise LegislatorsSourceError(f"community legislators record {index} has a non-integer id.{field}: {value!r}")
    return value


def _read_fec(value: object, index: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LegislatorsSourceError(
            f"community legislators record {index} has an id.fec that is not a list of strings"
        )
    for fec_id in value:
        if not _fec_id_shape_ok(fec_id):
            raise LegislatorsSourceError(
                f"community legislators record {index} has an id.fec entry with an unrecognized FEC candidate id "
                f"shape: {fec_id!r}"
            )
    return tuple(value)


def _read_term(term: object, record_index: int, term_index: int) -> Term:
    if not isinstance(term, dict):
        raise LegislatorsSourceError(
            f"community legislators record {record_index} terms[{term_index}] must be an object"
        )
    term_type = term.get("type")
    if term_type not in _TERM_TYPES:
        raise LegislatorsSourceError(
            f"community legislators record {record_index} terms[{term_index}].type must be 'rep' or 'sen', "
            f"got {term_type!r}"
        )
    values = {
        key: _string(term, key, message.format(i=term_index), required=required, pattern=pattern, index=record_index)
        for key, required, pattern, message in _TERM_STRING_RULES
    }
    return Term(type=term_type, start=values["start"], end=values["end"], state=values["state"], party=values["party"])


def _read_record(row: object, index: int) -> Legislator:
    if not isinstance(row, dict):
        raise LegislatorsSourceError(f"community legislators record {index} must be a JSON object")
    identifiers = row.get("id")
    if not isinstance(identifiers, dict):
        raise LegislatorsSourceError(f"community legislators record {index} is missing id")
    name = row.get("name")
    if not isinstance(name, dict):
        raise LegislatorsSourceError(f"community legislators record {index} is missing name")
    terms_raw = row.get("terms")
    if not isinstance(terms_raw, list) or not terms_raw:
        raise LegislatorsSourceError(f"community legislators record {index} needs a non-empty terms list")

    ids = {
        key: _string(identifiers, key, message, required=required, pattern=pattern, index=index)
        for key, required, pattern, message in _ID_STRING_RULES
    }
    fec = _read_fec(identifiers.get("fec", []), index)
    names = {
        key: _string(name, key, message, required=required, pattern=pattern, index=index)
        for key, required, pattern, message in _NAME_STRING_RULES
    }
    ints = {key: _optional_int(identifiers.get(key), index, key) for key in _ID_INT_FIELDS}
    terms = tuple(_read_term(term, index, ordinal) for ordinal, term in enumerate(terms_raw))

    return Legislator(
        bioguide=ids["bioguide"],
        lis=ids["lis"],
        fec=fec,
        icpsr=ints["icpsr"],
        govtrack=ints["govtrack"],
        opensecrets=ids["opensecrets"],
        wikidata=ids["wikidata"],
        name_first=names["first"],
        name_last=names["last"],
        terms=terms,
    )


def parse_legislators(body: bytes, *, max_bytes: int, max_records: int = DEFAULT_MAX_RECORDS) -> LegislatorsFile:
    """Read a ``legislators-{current,historical}.json`` file with every shape rule enforced.

    A file must be a JSON list; every record's shape is checked against the
    rule tables above (id and name fields, FEC id shapes, non-empty ``terms``
    with ISO dates and a ``rep``/``sen`` type). Any violation refuses the
    whole file, naming the offending record's position. A repeated
    ``id.bioguide``, ``id.lis`` or FEC id anywhere in the file is also a
    refusal, named at the record that repeats it -- this crosswalk promises
    each id names at most one person.
    """
    if isinstance(max_records, bool) or not isinstance(max_records, int) or not 1 <= max_records <= MAX_RECORDS_CAP:
        raise LegislatorsSourceError(f"max_records must be a positive integer no greater than {MAX_RECORDS_CAP}")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_HISTORICAL_BYTES:
        raise LegislatorsSourceError(f"max_bytes must be a positive integer no greater than {MAX_HISTORICAL_BYTES}")

    raw = load_bounded_json(
        body,
        source="community legislators",
        error_type=LegislatorsSourceError,
        number_policy="integer",
        max_bytes=max_bytes,
        max_nodes=_MAX_JSON_NODES,
        max_depth=_MAX_JSON_DEPTH,
    )
    if not isinstance(raw, list):
        raise LegislatorsSourceError("community legislators file must be a JSON list")
    if len(raw) > max_records:
        raise LegislatorsSourceError(f"community legislators file lists more than max_records ({max_records}) records")

    records: list[Legislator] = []
    by_bioguide: dict[str, Legislator] = {}
    by_lis: dict[str, Legislator] = {}
    by_fec: dict[str, Legislator] = {}
    for index, row in enumerate(raw):
        legislator = _read_record(row, index)
        if legislator.bioguide in by_bioguide:
            raise LegislatorsSourceError(
                f"community legislators record {index} repeats bioguide id {legislator.bioguide!r}"
            )
        by_bioguide[legislator.bioguide] = legislator
        if legislator.lis is not None:
            if legislator.lis in by_lis:
                raise LegislatorsSourceError(f"community legislators record {index} repeats LIS id {legislator.lis!r}")
            by_lis[legislator.lis] = legislator
        for fec_id in legislator.fec:
            if fec_id in by_fec:
                raise LegislatorsSourceError(f"community legislators record {index} repeats FEC id {fec_id!r}")
            by_fec[fec_id] = legislator
        records.append(legislator)

    return LegislatorsFile(
        records=tuple(records),
        by_bioguide=MappingProxyType(by_bioguide),
        by_lis=MappingProxyType(by_lis),
        by_fec=MappingProxyType(by_fec),
    )


@dataclass(frozen=True, slots=True)
class LegislatorsBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float
    max_historical_bytes: int = DEFAULT_MAX_HISTORICAL_BYTES

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_CURRENT_BYTES)
        check_byte_bound(self.max_historical_bytes, "max_historical_bytes", MAX_HISTORICAL_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class LegislatorsAcquisition:
    file: LegislatorsFile
    capture: CapturedBodyResponse
    request_count: int
    budget: LegislatorsBudget


class LegislatorsAcquirer(SourceAcquirer):
    """Keyless capture of the two community legislators crosswalk files.

    Neither route needs a credential; GitHub Pages can still answer 403 (for
    example when rate limited), so this stays a ``keyless`` acquirer like
    ``CboAcquirer`` -- a refusal body is evidence to retain, not a credential
    being rejected.
    """

    def __init__(
        self,
        *,
        budget: LegislatorsBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, LegislatorsBudget):
            raise TypeError("budget must be a LegislatorsBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-legislators/1.0",
            label="community legislators",
            error_type=LegislatorsSourceError,
            context_key="legislators_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> LegislatorsBudget:
        return self._budget

    def _acquire(self, url: str, operation: str, max_bytes: int) -> LegislatorsAcquisition:
        legislators_file, capture = self.capture_validated(
            url,
            media_types=MEDIA_TYPES,
            parse=lambda response, allowance: parse_legislators(response.body, max_bytes=allowance),
            max_bytes=max_bytes,
            unavailable=LegislatorsUnavailableError,
            context={"operation": operation, "url": url},
        )
        return LegislatorsAcquisition(legislators_file, capture, self.request_count, self.budget)

    def acquire_current(self, *, max_bytes: int | None = None) -> LegislatorsAcquisition:
        """Everyone serving today. Measured 2026-09-19: 539 records, 1,468,926 bytes."""
        return self._acquire(LEGISLATORS_CURRENT_URL, "current", narrow_byte_limit(self.budget.max_bytes, max_bytes))

    def acquire_historical(self, *, max_bytes: int | None = None) -> LegislatorsAcquisition:
        """Everyone who has left; the only route to a former senator's LIS id.

        Measured 2026-09-18: 12,231 records, 13,483,039 bytes (unchanged when
        re-measured 2026-09-19).
        """
        limit = narrow_byte_limit(self.budget.max_historical_bytes, max_bytes)
        return self._acquire(LEGISLATORS_HISTORICAL_URL, "historical", limit)
