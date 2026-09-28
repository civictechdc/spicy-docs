"""Read the RIN a House executive communication states in its report nature.

Reads ``reportNature`` from the Congress.gov ``house-communication`` detail
route and returns a :class:`RinFinding` naming the RIN, the rule that fired and
the exact matched text, so a hosted row carries its own audit trail beside the
value. The rule -- a ``RIN`` label, an optional colon, optional whitespace,
then ``nnnn-XXnn`` ending there -- is the measured form: on 18 of the 25 newest
House communications of the 119th Congress the 12 rulemakings state a RIN under
it, no non-rulemaking does, and a relaxed validator-shaped rule found nothing
more. The pattern is searched, not anchored, because the label sits
mid-sentence inside parentheses; a report nature naming two RINs would yield
the first. Since 0.50.1 the RIN must end where the shape does: NOAA's
five-character suffix (``RIN: 0648-XE368``) is outside the published shape,
and the rule used to publish its first eight characters (``0648-XE36``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from spicy_docs.interpretation.identifier_shapes import PUBLISHED_RIN

#: The measured label rule.  Group 1 is the RIN as the publisher spelled it,
#: in the one shape a published RIN key takes (``identifier_shapes``), and no
#: letter, digit, hyphen or underscore may follow it -- the right edge the
#: shared identifier reader also requires, so a longer token is not cut short.
REPORT_NATURE_RIN = re.compile(rf"RIN:?\s*({PUBLISHED_RIN})(?![A-Za-z0-9_-])")

RIN_RULES: tuple[str, ...] = ("report_nature_rin_label", "unmatched")


@dataclass(frozen=True, slots=True)
class RinFinding:
    """One communication's RIN, or the record that no rule found one."""

    rin: str | None
    rule: str
    matched_text: str | None


def rin_from_report_nature(report_nature: str | None) -> RinFinding:
    """The RIN a report nature states, or an ``unmatched`` finding.

    ``None`` -- a communication with no ``reportNature`` at all -- is
    ``unmatched`` rather than an error: the rule ran and found nothing, and the
    row should say so. Raises ``TypeError`` for a non-string, non-``None``
    input.
    """
    if report_nature is None:
        return RinFinding(None, "unmatched", None)
    if not isinstance(report_nature, str):
        raise TypeError(f"report_nature must be a string or None, not {type(report_nature).__name__}")
    match = REPORT_NATURE_RIN.search(report_nature)
    if match is None:
        return RinFinding(None, "unmatched", None)
    return RinFinding(match[1], "report_nature_rin_label", match[0])


__all__ = ["REPORT_NATURE_RIN", "RIN_RULES", "RinFinding", "rin_from_report_nature"]


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
    list, so no member needs a label of its own. The list and the scalar
    :func:`rin_from_report_nature` differ in two ways, both by design:

    - **Label.** The scalar reads the first RIN the exact label ``RIN``
      (optional colon) immediately precedes; the list reads every RIN: later
      list members, later labelled RINs, and RINs under a plural ``RINs:``, a
      spelled-out ``Regulation Identification Number`` or a misspelled
      ``IRN:`` label.
    - **Dashes and case.** The list folds the Unicode dashes and letter case
      to the published key, so ``RIN: 2120-Aa64`` lists ``2120-AA64``; the
      scalar reads only an ASCII hyphen-minus and capitals, the spelling its
      measurement saw. ``rin`` is the folded key, ``matched_text`` the text
      as printed.

    Where the scalar reads a RIN, an occurrence at the same span holds the
    same value. Every occurrence is keyed through ``published_rin``, so a
    damaged or placeholder RIN (``1625-AAOO``) or a longer token
    (``0648-XE368``) is not listed. Offsets index the supplied field, not a
    whole communication.
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


__all__ += ["RinOccurrence", "rin_occurrences_from_report_nature"]
