"""Read the RIN a House executive communication states in its report nature.

Reads ``reportNature`` from the Congress.gov ``house-communication`` detail
route and returns a :class:`RinFinding` naming the RIN, the rule that fired and
the exact matched text, so a hosted row carries its own audit trail beside the
value. The rule -- a ``RIN`` label, an optional colon, optional whitespace,
then ``nnnn-XXnn`` -- is the measured form: on 18 of the 25 newest House
communications of the 119th Congress the 12 rulemakings state a RIN under it,
no non-rulemaking does, and a relaxed validator-shaped rule found nothing
more. The pattern is searched, not anchored, because the label sits
mid-sentence inside parentheses; a report nature naming two RINs would yield
the first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The measured label rule.  Group 1 is the RIN as the publisher spelled it.
REPORT_NATURE_RIN = re.compile(r"RIN:?\s*(\d{4}-[A-Z]{2}\d{2})")

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
