"""Read the RINs a House executive communication states in its report nature.

Reads ``reportNature`` from the Congress.gov ``house-communication`` detail
route. :func:`rin_occurrences_from_report_nature` lists every RIN the shared
``rin`` citation rule reads there; :func:`rin_from_report_nature` names the
one RIN a row publishes as its scalar, with the rule that fired and the exact
text, so a hosted row carries its own audit trail beside the value.

The scalar is the first listed RIN that a ``RIN`` label -- the word, an
optional colon, optional whitespace -- directly precedes. The label is the
measured form: on 18 of the 25 newest House communications of the 119th
Congress the 12 rulemakings state a RIN under it, no non-rulemaking does, and
a relaxed validator-shaped rule found nothing more. Before 0.50.1 the scalar
was its own pattern, which read ASCII hyphens and capitals only and no right
edge, so it could read a RIN the list does not (``RIN: 0648-XE368`` as
``0648-XE36``) and miss one it does (``RIN: 2120-Aa64``). Built from the list,
it cannot disagree with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The label the scalar requires directly before a listed RIN, searched with its end at the RIN's first character.
RIN_LABEL = re.compile(r"RIN:?\s*\Z")

#: The rule a scalar RIN is read under. ``/2`` since 0.50.1, when the scalar became the first labelled occurrence of
#: the shared ``rin`` rule; rows read by 0.50.0 and earlier name ``report_nature_rin_label``.
RIN_LABEL_RULE = "report_nature_rin_label/2"
RIN_RULES: tuple[str, ...] = (RIN_LABEL_RULE, "unmatched")


@dataclass(frozen=True, slots=True)
class RinOccurrence:
    """One RIN span in the supplied reportNature text; repeated mentions remain separate."""

    rin: str
    ordinal: int
    matched_text: str
    span_start: int
    span_end: int
    field_sha256: str
    rule: str
    rule_version: str


def rin_occurrences_from_report_nature(report_nature: str | None) -> tuple[RinOccurrence, ...]:
    """Every RIN the shared ``rin`` citation rule reads in the field, in text order.

    House communication 119-EC-1278 states ``(RIN: 3235-AK79; 3235-AK80)``
    (fixture in tests/fixtures/record_communications): one label introduces a
    list, so no member needs a label of its own. The list therefore holds more
    than the scalar: later list members, later labelled RINs, and RINs under a
    plural ``RINs:``, a spelled-out ``Regulation Identification Number`` or a
    misspelled ``IRN:`` label. ``rin`` is the key with the Unicode dashes and
    letter case folded (``RIN: 2120-Aa64`` lists ``2120-AA64``);
    ``matched_text`` is the text as printed.

    Every occurrence is keyed through ``published_rin``, so a damaged or
    placeholder RIN (``1625-AAOO``) or a longer token (``0648-XE368``,
    ``2060-AV12–A``) is not listed, nor is a RIN the shared reader does not
    separate from its neighbour (``RIN2060-AV12``, ``2060-AV12/2060-AV13``).
    Offsets index the supplied field, not a whole communication.
    """
    import hashlib

    from spicy_docs.interpretation.citations import find_citations

    if report_nature is None:
        return ()
    if not isinstance(report_nature, str):
        raise TypeError(f"report_nature must be a string or None, not {type(report_nature).__name__}")
    digest = hashlib.sha256(report_nature.encode()).hexdigest()
    return tuple(
        RinOccurrence(
            finding.target_key,
            ordinal,
            finding.matched_text,
            finding.span_start,
            finding.span_end,
            digest,
            "report_nature/shared_rin",
            finding.rule_version,
        )
        for ordinal, finding in enumerate(find_citations(report_nature, kinds=("rin",)))
    )


@dataclass(frozen=True, slots=True)
class RinFinding:
    """One communication's RIN, or the record that no rule found one."""

    rin: str | None
    rule: str
    matched_text: str | None


def rin_from_report_nature(report_nature: str | None) -> RinFinding:
    """The first listed RIN the ``RIN`` label directly precedes, or an ``unmatched`` finding.

    ``rin`` is that occurrence's folded key and ``matched_text`` the label and
    the RIN as printed (``RIN: 2120-Aa64``), so every scalar RIN is in
    :func:`rin_occurrences_from_report_nature`'s list at the same span.
    ``None`` -- a communication with no ``reportNature`` at all -- is
    ``unmatched`` rather than an error: the rule ran and found nothing, and the
    row should say so. Raises ``TypeError`` for a non-string, non-``None``
    input.
    """
    occurrences = rin_occurrences_from_report_nature(report_nature)  # refuses a non-string first
    text = report_nature or ""
    for occurrence in occurrences:
        label = RIN_LABEL.search(text, 0, occurrence.span_start)
        if label is not None:
            return RinFinding(occurrence.rin, RIN_LABEL_RULE, text[label.start() : occurrence.span_end])
    return RinFinding(None, "unmatched", None)


__all__ = [
    "RIN_LABEL",
    "RIN_LABEL_RULE",
    "RIN_RULES",
    "RinFinding",
    "RinOccurrence",
    "rin_from_report_nature",
    "rin_occurrences_from_report_nature",
]
