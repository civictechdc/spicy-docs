"""Injected source semantics for the single source-native publisher."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO, Literal, Protocol

from rulespec_artifacts import BlobSource

from spicy_docs.releases.format import MAX_EVIDENCE_BYTES


class SourceNativePage(Protocol):
    @property
    def traversal_index(self) -> int: ...

    @property
    def page_index(self) -> int: ...

    @property
    def window_index(self) -> int: ...

    @property
    def window_page_index(self) -> int: ...

    @property
    def request_key(self) -> str: ...

    @property
    def source_cursor(self) -> str | None: ...

    @property
    def response_bytes(self) -> bytes | None: ...

    @property
    def evidence_media_type(self) -> str: ...


@dataclass(frozen=True, slots=True)
class SourceNativeBlobPage:
    """One retained original streamed from an injected store, with no byte copy in metadata."""

    page_index: int
    window_index: int
    request_key: str
    blob_ref: str
    byte_size: int
    blob_source: BlobSource
    evidence_media_type: str
    traversal_index: int = 0
    window_page_index: int = 0
    source_cursor: str | None = None
    response_bytes: None = None


class ParsePageStream(Protocol):
    def __call__(
        self,
        stream: BinaryIO,
        *,
        query_scope: Mapping[str, Any],
        request_key: str,
        evidence_ref: str,
        byte_size: int,
        media_type: str,
    ) -> Mapping[str, Any]: ...


class TraversalCheck(Protocol):
    def add(self, response: Mapping[str, Any], *, page_index: int) -> None: ...

    def finish(self) -> None: ...


class NextPage(Protocol):
    def __call__(
        self,
        response: Mapping[str, Any],
        *,
        seen_urls: set[str],
    ) -> str | None: ...


class WrapRecord(Protocol):
    def __call__(
        self,
        record: Mapping[str, Any],
        *,
        schema_digest: str,
    ) -> Mapping[str, Any]: ...


class ValidateRecordScope(Protocol):
    def __call__(
        self,
        record: Mapping[str, Any],
        *,
        query_scope: Mapping[str, Any],
        page_window: object | None,
    ) -> None: ...


class RecordsIncluded(Protocol):
    def __call__(
        self,
        response: Mapping[str, Any],
        *,
        query_scope: Mapping[str, Any],
        page_window: object | None,
    ) -> bool: ...


class AcquisitionCheck(Protocol):
    def add_window(
        self,
        response: Mapping[str, Any],
        *,
        page_window: object | None,
        records_included: bool,
        response_bytes: bytes | None,
    ) -> None: ...

    def finish(self, *, query_scope: Mapping[str, Any]) -> None: ...


class ObservationVersion(Protocol):
    """Return the exact source version used to select one public observation."""

    def __call__(self, record: Mapping[str, Any]) -> str | None: ...


@dataclass(frozen=True, slots=True)
class SourceNativeProfile:
    """Source-owned functions injected into common publication machinery."""

    name: str
    source_system_id: str
    source_system_version: str
    acquisition_policy_id: str
    acquisition_policy_version: str
    scope_id: str
    source_schema_key: str
    source_schema: Mapping[str, Any]
    record_stem: str
    max_traversals: int
    source_state_scope: Literal["complete-snapshot", "observed-crawl"]
    traversal_acceptance: Literal[
        "single-observed-traversal",
        "source-enumeration",
        "stable-consecutive-traversals",
    ]
    acquisition_policy: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    validate_query_scope: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    parse_page_response: Callable[[bytes], Mapping[str, Any]]
    next_page: NextPage
    traversal_check: Callable[[], TraversalCheck]
    classify_record: Callable[[object], Mapping[str, Any]]
    wrap_record: WrapRecord
    record_digest: Callable[[Mapping[str, Any]], str]
    rendition_rows: Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
    source_schema_declaration: Callable[[], Mapping[str, Any]]
    source_schema_digest: Callable[[], str]
    validate_record_scope: ValidateRecordScope
    records_included: RecordsIncluded
    acquisition_check: Callable[[], AcquisitionCheck]
    page_window: Callable[[str], object] | None = None
    observation_version: ObservationVersion | None = None
    refuse_equal_observation_versions: bool = False
    # Judges whether a same-instant tie is substantive or confined to fields
    # the source derives at read time (never carried by the record itself).
    # Used only to decide whether two observations collapse instead of
    # refusing as an unresolved tie -- its result is never published or
    # stored, and it must not change what record_digest covers.
    tie_comparison_digest: Callable[[Mapping[str, Any]], str] | None = None

    # Opt-in source rules for whole files; existing byte profiles keep their bound.
    parse_page_stream: ParsePageStream | None = None
    max_evidence_bytes: int = MAX_EVIDENCE_BYTES

    def __post_init__(self) -> None:
        if type(self.max_evidence_bytes) is not int or self.max_evidence_bytes < 1:
            raise ValueError("source evidence bound must be a positive integer")
        if self.parse_page_stream is None and self.max_evidence_bytes != MAX_EVIDENCE_BYTES:
            raise ValueError("only stream profiles may select a different evidence bound")
        if not self.name or not self.source_system_id or not self.source_system_version:
            raise ValueError("source-native profile identity must be nonempty")
        if not self.acquisition_policy_id or not self.acquisition_policy_version:
            raise ValueError("source-native acquisition policy identity must be nonempty")
        if not self.scope_id or not self.source_schema_key or not self.record_stem:
            raise ValueError("source-native profile member identity must be nonempty")
        if self.max_traversals < 1:
            raise ValueError("source-native profile traversal bound must be positive")
        if self.refuse_equal_observation_versions and self.observation_version is None:
            raise ValueError("equal observation versions can be refused only by a versioned profile")
        if self.tie_comparison_digest is not None and self.observation_version is None:
            raise ValueError("a tie comparison digest can only judge ties on a versioned profile")

        if self.source_state_scope == "complete-snapshot" and self.traversal_acceptance != "source-enumeration":
            raise ValueError("complete source state requires a source-enumeration acceptance proof")


__all__ = [
    "AcquisitionCheck",
    "ObservationVersion",
    "RecordsIncluded",
    "SourceNativeBlobPage",
    "SourceNativePage",
    "SourceNativeProfile",
    "TraversalCheck",
]
