"""Read the RIN a House executive communication states in its report nature.

Publisher fact in: ``reportNature`` from the Congress.gov ``house-communication``
detail route -- prose such as ``The Administration's final rule - Termination
of Excess Insurance Coverage (RIN: 3133-AF97) received August 25, 2026.``

Interpretation out: a :class:`RinFinding` naming the RIN, the rule that fired
and the exact text it matched, so a hosted row carries its own audit trail
beside the value, the way ``press_releases`` carries its match.

The rule is the one the legislative data map measured on 2026-09-18
(the ``communication-typing`` and ``communication→federal-register`` edges in
``tools/analysis/legislative_data_map.py``): a ``RIN`` label, an optional
colon, optional whitespace, then ``nnnn-XXnn``.  Re-measured 2026-09-19 on 18
of the 25 newest House communications of the 119th Congress, inside the
day's request budget (receipt ``house-communications-rin-2026-09-19/``): 12
are rulemakings, the same 12 state a RIN under this rule, no non-rulemaking
does, and every RIN this rule finds is also found by a relaxed rule shaped
like the Federal Register source's own validator (``nnnn-XXXX``, letters or
digits after the first letter; ``sources/federal_register/native.py``).  The
narrower measured form is kept because it is what was measured; the relaxed
form found nothing more, so it is not a second rule.

The pattern is searched, not anchored: the label sits mid-sentence inside
parentheses.  A ``reportNature`` naming two RINs would yield the first; none
of the 18 sampled named two.
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

    ``None`` -- a communication with no ``reportNature`` at all, which the
    publisher's memorials and some reports are -- is ``unmatched`` rather than
    an error: the rule ran and found nothing, and the row should say so.
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
