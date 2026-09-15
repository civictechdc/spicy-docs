"""Source AUTH notes and their structural context from retained eCFR XML.

Selection, citation interpretation and legal meaning belong to the caller.
Callbacks are provisional until the scan succeeds; malformed trailing XML can
refuse after earlier observations were delivered.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from spicy_docs.reading.xml_observations import XmlElement, XmlObservationScan

from .models import DEFAULT_MAX_BYTES, CfrSourceError, _limit

_DIVISIONS = frozenset(f"DIV{number}" for number in range(1, 10))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _part(tag: str, attributes: dict[str, str]) -> bool:
    return _local(tag) == "DIV5" and attributes.get("TYPE") == "PART"


@dataclass(frozen=True, slots=True)
class EcfrPartObservation:
    """An actual DIV5 TYPE=PART, including unnamed parts and parts without AUTH."""

    element: XmlElement
    ancestors: tuple[XmlElement, ...]


@dataclass(frozen=True, slots=True)
class EcfrTextObservation:
    """One AUTH, SOURCE, or direct DIV1–DIV9 HEAD with literal decoded text.

    ``text_runs`` separate text at element boundaries, never at parser feed or
    entity boundaries. Joining without a separator reproduces ``text``. XML
    decoding and newline rules apply; these strings are not original XML bytes.
    ``ancestors`` excludes this element and runs from root to parent.
    """

    element: XmlElement
    ancestors: tuple[XmlElement, ...]
    text: str
    text_runs: tuple[str, ...]

    @property
    def nearest_division(self) -> XmlElement | None:
        return next((item for item in reversed(self.ancestors) if _local(item.tag) in _DIVISIONS), None)

    @property
    def nearest_part(self) -> XmlElement | None:
        return next((item for item in reversed(self.ancestors) if _part(item.tag, item.attributes)), None)


@dataclass(frozen=True, slots=True)
class EcfrAuthorityScan:
    """Input pin and counts for a complete scan, including unrequested fields."""

    input_sha256: str
    input_bytes: int
    root_tag: str
    parts: int
    authorities: int
    headings: int
    sources: int


@dataclass(slots=True)
class _Text:
    ancestry: tuple[XmlElement, ...]
    callback: Callable[[EcfrTextObservation], object]
    runs: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    characters: int = 0

    def boundary(self) -> None:
        if self.pending:
            self.runs.append("".join(self.pending))
            self.pending.clear()


class _AuthorityScan(XmlObservationScan):
    def __init__(
        self,
        on_part: Callable[[EcfrPartObservation], object] | None,
        callbacks: dict[str, Callable[[EcfrTextObservation], object] | None],
        max_observations: int,
        max_text_characters: int,
        max_depth: int,
    ) -> None:
        super().__init__(error_type=CfrSourceError, label="eCFR XML", max_depth=max_depth)
        self.on_part = on_part
        self.callbacks = callbacks
        self.max_observations = max_observations
        self.max_text_characters = max_text_characters
        self.counts = dict.fromkeys(("PART", "AUTH", "HEAD", "SOURCE"), 0)
        self.active: list[_Text] = []
        self.active_characters = 0
        self.root = ""

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        if len(self.stack) == 1:
            self.root = tag
        for capture in self.active:
            capture.boundary()
        local = _local(tag)
        if _part(tag, attributes):
            kind = "PART"
        elif local in ("AUTH", "HEAD", "SOURCE"):
            kind = local
        else:
            return
        if kind == "HEAD" and (len(self.stack) < 2 or _local(self.stack[-2].tag) not in _DIVISIONS):
            return
        self.counts[kind] += 1
        if sum(self.counts.values()) > self.max_observations:
            raise CfrSourceError("eCFR XML exceeds max_observations")
        if kind == "PART":
            if self.on_part is not None:
                ancestry = self.snapshot()
                self.emit(self.on_part, EcfrPartObservation(ancestry[-1], ancestry[:-1]))
        elif (callback := self.callbacks[kind]) is not None:
            self.active.append(_Text(self.snapshot(), callback))

    def observe_text(self, text: str) -> None:
        self.active_characters += len(text) * len(self.active)
        if self.active_characters > self.max_text_characters:
            raise CfrSourceError("eCFR metadata text exceeds max_text_characters")
        for capture in self.active:
            capture.pending.append(text)
            capture.characters += len(text)

    def observe_end(self, tag: str) -> None:
        for capture in self.active:
            capture.boundary()
        if self.active and len(self.active[-1].ancestry) == len(self.stack):
            capture = self.active.pop()
            self.active_characters -= capture.characters
            self.emit(
                capture.callback,
                EcfrTextObservation(
                    capture.ancestry[-1], capture.ancestry[:-1], "".join(capture.runs), tuple(capture.runs)
                ),
            )


def scan_ecfr_authority_notes(
    xml: bytes,
    *,
    on_part: Callable[[EcfrPartObservation], object] | None = None,
    on_authority: Callable[[EcfrTextObservation], object] | None = None,
    on_heading: Callable[[EcfrTextObservation], object] | None = None,
    on_source: Callable[[EcfrTextObservation], object] | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_observations: int = 1_000_000,
    max_text_characters: int = 4 * 1024 * 1024,
    max_depth: int = 256,
) -> EcfrAuthorityScan:
    """Read AUTH, SOURCE, direct structural HEAD, and every DIV5 TYPE=PART once.

    Parts arrive at element start; text arrives at element close. All AUTH and
    SOURCE elements survive, including empty, nested and orphan observations.
    PARAUTH and SECAUTH are separate source forms outside this reader's scope.
    This reader accepts retained fragments; acquisition checks title identity.

    Selection uses local element names and unqualified TYPE attributes. Expanded
    names survive in observations. An unnamed nearest part is not replaced by
    an outer part. XML comments and processing instructions contribute no text
    and do not split runs; this is source text, not an HTML rendering algorithm.

    ``max_observations`` bounds the four counts together. Text limits apply to
    all simultaneously buffered requested fields, counting nested duplication.
    Unrequested text is not buffered. Callback storage and input bytes are
    outside that memory budget. Retain the input with the returned SHA-256 to
    replay element-only XPath locations; those paths are never byte offsets.
    """
    _limit(max_bytes)
    for name, value in (("max_observations", max_observations), ("max_text_characters", max_text_characters)):
        if type(value) is not int or value <= 0:
            raise CfrSourceError(f"{name} must be a positive integer")
    callbacks = {"AUTH": on_authority, "HEAD": on_heading, "SOURCE": on_source}
    if any(callback is not None and not callable(callback) for callback in (on_part, *callbacks.values())):
        raise CfrSourceError("eCFR metadata callbacks must be callable")
    scan = _AuthorityScan(on_part, callbacks, max_observations, max_text_characters, max_depth)
    scan.read(xml, max_bytes=max_bytes)
    return EcfrAuthorityScan(
        hashlib.sha256(xml).hexdigest(),
        len(xml),
        scan.root,
        scan.counts["PART"],
        scan.counts["AUTH"],
        scan.counts["HEAD"],
        scan.counts["SOURCE"],
    )
