"""Literal rows from the mutable, undocumented FederalRegister.gov topics API."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from spicy_docs.reading.json_input import load_bounded_json
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
)

if TYPE_CHECKING:
    import httpx

FR_TOPICS_URL = "https://www.federalregister.gov/api/v1/topics.json"
DEFAULT_MAX_BYTES = 16 * 1024**2
_COLLECTIONS = ("thesaurus", "ad_hoc")


class FrTopicsSourceError(ValueError):
    """The input cannot establish the expected topics response shape."""


@dataclass(frozen=True, slots=True)
class FrTopicLink:
    name: str
    slug: str
    raw: Mapping[str, Any]
    source_path: str


@dataclass(frozen=True, slots=True)
class FrTopicCfrReference:
    raw: Any
    source_path: str


@dataclass(frozen=True, slots=True)
class FrTopicRow:
    collection: str
    source_ordinal: int
    name: str
    slug: str
    see: tuple[FrTopicLink, ...]
    see_also: tuple[FrTopicLink, ...]
    cfr_references: tuple[FrTopicCfrReference, ...]
    raw: Mapping[str, Any]
    source_path: str


@dataclass(frozen=True, slots=True)
class FrTopicCollection:
    name: str
    rows: tuple[FrTopicRow, ...]
    raw: list[Any]
    source_path: str


@dataclass(frozen=True, slots=True)
class FrTopicsRead:
    input_sha256: str
    input_bytes: int
    raw: Mapping[str, Any]
    collections: tuple[FrTopicCollection, ...]
    declared_counts: Mapping[str, int]
    observed_counts: Mapping[str, int]


def _field(raw: Mapping[str, Any], name: str, expected: type, path: str) -> Any:
    if name not in raw or not isinstance(raw[name], expected):
        raise FrTopicsSourceError(f"{path}.{name} must be present with type {expected.__name__}")
    return raw[name]


def _object(raw: object, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FrTopicsSourceError(f"{path} must be an object")
    return raw


def _links(raw: list[Any], path: str) -> tuple[FrTopicLink, ...]:
    result = []
    for index, value in enumerate(raw):
        location = f"{path}[{index}]"
        item = _object(value, location)
        result.append(
            FrTopicLink(_field(item, "name", str, location), _field(item, "slug", str, location), item, location)
        )
    return tuple(result)


def _rows(raw: list[Any], collection: str, path: str) -> tuple[FrTopicRow, ...]:
    result = []
    for index, value in enumerate(raw):
        location = f"{path}[{index}]"
        item = _object(value, location)
        references = _field(item, "cfr_references", list, location)
        result.append(
            FrTopicRow(
                collection=collection,
                source_ordinal=index,
                name=_field(item, "name", str, location),
                slug=_field(item, "slug", str, location),
                see=_links(_field(item, "see", list, location), f"{location}.see"),
                see_also=_links(_field(item, "see_also", list, location), f"{location}.see_also"),
                cfr_references=tuple(
                    FrTopicCfrReference(reference, f"{location}.cfr_references[{ordinal}]")
                    for ordinal, reference in enumerate(references)
                ),
                raw=item,
                source_path=location,
            )
        )
    return tuple(result)


def read_fr_topics(
    payload: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_nodes: int = 500_000,
    max_depth: int = 64,
) -> FrTopicsRead:
    """Read known containers and retain every unknown field in the raw JSON.

    This is an observed endpoint shape, not a formal publisher schema. Known
    keys must exist with their observed types. Empty strings/arrays, duplicate
    slugs and count disagreement survive. Collections and rows keep source
    order; indices are zero-based JSON paths. Unknown collections remain raw.
    CFR references are arbitrary finite JSON values, never interpreted here.

    Limits cover the entire input, including unknown fields. JSON integers and
    finite binary floats match Python's normal JSON value model; the input pin
    binds original number spelling and bytes. No canonical row digest, stable
    topic identity, cross-capture matching or vocabulary selection is created.
    """
    raw = _object(
        load_bounded_json(
            payload,
            source="Federal Register topics",
            error_type=FrTopicsSourceError,
            number_policy="finite-float",
            max_bytes=max_bytes,
            max_nodes=max_nodes,
            max_depth=max_depth,
        ),
        "$",
    )
    meta = _field(raw, "meta", dict, "$")
    counts = _field(meta, "count", dict, "$.meta")
    results = _field(raw, "results", dict, "$")
    for name in (*_COLLECTIONS, "total"):
        if name not in counts or type(counts[name]) is not int:
            raise FrTopicsSourceError(f"$.meta.count.{name} must be an integer")
    for name in _COLLECTIONS:
        _field(results, name, list, "$.results")
    collections = tuple(
        FrTopicCollection(name, _rows(rows, name, f"$.results.{name}"), rows, f"$.results.{name}")
        for name, rows in results.items()
        if name in _COLLECTIONS
    )
    observed = {collection.name: len(collection.rows) for collection in collections}
    observed["total"] = sum(observed.values())
    return FrTopicsRead(
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        raw,
        collections,
        {name: value for name, value in counts.items() if name in (*_COLLECTIONS, "total")},
        observed,
    )


class FrTopicsUnavailableError(FrTopicsSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"Federal Register topics answered HTTP {capture.status_code}")
        self.capture = capture


@dataclass(frozen=True, slots=True)
class FrTopicsBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", 64 * 1024**2)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class FrTopicsAcquisition:
    capture: CapturedBodyResponse
    topics: FrTopicsRead
    request_count: int
    budget: FrTopicsBudget


class FrTopicsAcquirer(SourceAcquirer):
    """Explicit bounded capture; the caller owns storage and capture history."""

    def __init__(self, *, budget: FrTopicsBudget, transport: httpx.BaseTransport | None = None) -> None:
        if not isinstance(budget, FrTopicsBudget):
            raise TypeError("budget must be a FrTopicsBudget")
        self.budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-fr-topics/1.0",
            label="Federal Register topics",
            error_type=FrTopicsSourceError,
            context_key="fr_topics_acquisition",
            transport=transport,
            headers={"Accept": "application/json"},
            keyless=True,
        )

    def acquire_topics(self) -> FrTopicsAcquisition:
        topics, capture = self.capture_validated(
            FR_TOPICS_URL,
            media_types=("application/json",),
            parse=lambda response, bound: read_fr_topics(response.body, max_bytes=bound),
            max_bytes=self.budget.max_bytes,
            unavailable=FrTopicsUnavailableError,
            context={"operation": "topics"},
        )
        return FrTopicsAcquisition(capture, topics, self.request_count, self.budget)
