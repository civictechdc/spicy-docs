"""Literal U.S. Code references and source credits, without citation interpretation.

Callbacks stream observations from retained XML, including fragments. They are
provisional until the scan returns: malformed trailing XML can refuse after
earlier callbacks ran. Acquisition identity and output retention belong to the
caller; this reader neither fetches nor publishes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .uscode import DEFAULT_MAX_XML_BYTES, UsCodeSourceError
from .uscode_xml import UsCodeElement, UsCodeXmlScan


@dataclass(frozen=True, slots=True)
class UsCodeReference:
    """One element with unqualified ``href``, or ``ref`` without it, and ancestry.

    Expanded namespace names distinguish USLM ``ref`` from XHTML ``a`` and
    unknown markup. No href shape is filtered, normalized, resolved or typed.
    ``ancestors`` excludes the observed element, in root-to-parent order.
    """

    element: UsCodeElement
    ancestors: tuple[UsCodeElement, ...]

    @property
    def href(self) -> str | None:
        """The supplied href; ``None`` means absent and ``""`` means present empty."""
        return self.element.attributes.get("href")


@dataclass(frozen=True, slots=True)
class UsCodeSourceCredit:
    """A sourceCredit's descendant XML text, including whitespace and unknown prose.

    Text follows XML decoding and newline rules. It is neither original XML
    bytes nor a rendered-text layout. An empty or unidentified nearest section
    remains in ``ancestors``; it does not inherit an outer section identifier.
    """

    element: UsCodeElement
    ancestors: tuple[UsCodeElement, ...]
    text: str


@dataclass(frozen=True, slots=True)
class UsCodeReferenceScan:
    """Counts for a completely parsed input, including unrequested observations."""

    elements: int
    references: int
    source_credits: int


@dataclass(slots=True)
class _CreditText:
    ancestry: tuple[UsCodeElement, ...]
    parts: list[str] = field(default_factory=list)
    characters: int = 0


class _ReferenceScan(UsCodeXmlScan):
    def __init__(
        self,
        on_reference: Callable[[UsCodeReference], object] | None,
        on_source_credit: Callable[[UsCodeSourceCredit], object] | None,
        max_observations: int,
        max_text_characters: int,
        max_depth: int,
    ) -> None:
        super().__init__(max_depth=max_depth)
        self.on_reference = on_reference
        self.on_source_credit = on_source_credit
        self.max_observations = max_observations
        self.max_text_characters = max_text_characters
        self.elements = self.references = self.source_credits = 0
        self.active: list[_CreditText] = []
        self.active_characters = 0

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        self.elements += 1
        local = tag.rsplit("}", 1)[-1]
        reference = "href" in attributes or local == "ref"
        credit = local == "sourceCredit"
        self.references += reference
        self.source_credits += credit
        if self.references + self.source_credits > self.max_observations:
            raise UsCodeSourceError("U.S. Code XML exceeds max_observations")
        if reference and self.on_reference is not None:
            ancestry = self.snapshot()
            self.emit(self.on_reference, UsCodeReference(ancestry[-1], ancestry[:-1]))
        if credit and self.on_source_credit is not None:
            self.active.append(_CreditText(self.snapshot()))

    def observe_text(self, text: str) -> None:
        self.active_characters += len(text) * len(self.active)
        if self.active_characters > self.max_text_characters:
            raise UsCodeSourceError("U.S. Code source-credit text exceeds max_text_characters")
        for credit in self.active:
            credit.parts.append(text)
            credit.characters += len(text)

    def observe_end(self, tag: str) -> None:
        if tag.rsplit("}", 1)[-1] == "sourceCredit" and self.on_source_credit is not None:
            credit = self.active.pop()
            self.active_characters -= credit.characters
            self.emit(
                self.on_source_credit,
                UsCodeSourceCredit(credit.ancestry[-1], credit.ancestry[:-1], "".join(credit.parts)),
            )


def scan_uscode_references(
    xml: bytes,
    *,
    on_reference: Callable[[UsCodeReference], object] | None = None,
    on_source_credit: Callable[[UsCodeSourceCredit], object] | None = None,
    max_bytes: int = DEFAULT_MAX_XML_BYTES,
    max_observations: int = 1_000_000,
    max_text_characters: int = 4 * 1024 * 1024,
    max_depth: int = 256,
) -> UsCodeReferenceScan:
    """Read references at element start and credits at element end, without a DOM.

    The source byte/depth limits come from the shared XML scanner.
    ``max_observations`` bounds reference and source-credit records together;
    ``max_text_characters`` bounds text buffered by all open credits, including
    duplication when credits nest. Unrequested credit text is not buffered.
    Memory excludes input bytes and anything the caller keeps in callbacks.

    Element local names select ``ref`` and ``sourceCredit`` in any namespace;
    expanded names survive so callers can apply their own namespace rules.
    Element-only XPath positions locate markup, not bytes or text offsets.
    """
    for name, value in (("max_observations", max_observations), ("max_text_characters", max_text_characters)):
        if type(value) is not int or value <= 0:
            raise UsCodeSourceError(f"{name} must be a positive integer")
    scan = _ReferenceScan(on_reference, on_source_credit, max_observations, max_text_characters, max_depth)
    scan.read(xml, max_bytes=max_bytes)
    return UsCodeReferenceScan(scan.elements, scan.references, scan.source_credits)
