"""Which CRPT package is a committee activity report, by its index title.

An end-of-Congress activity report is an ordinary ``CRPT`` package -- nothing in
its id, its ``docClass`` or its MODS says it is one -- so the rule reads its own
title and requires the word ``committee`` or the fixed phrase ``activity
report``, never the bare word ``activit``, which takes in ordinary reports whose
subject is an agency's activities. Measured 2026-09-20 over the 71 ``CRPT``
packages a ``published`` walk served for 2025-01-01..2025-03-31: the bare word
matched 20 titles and the phrase 15, refusing three resolutions and missing the
two activity reports that name a Congress and no committee; the rule is not
widened to reach them because dropping the committee clause readmits the three,
so the miss is a recorded floor. The phrase, the rejected alternative and
:data:`ACTIVITY_REPORT_RULE_VERSION`'s digest over both live here because the
analysis tools must import the rule rather than restate it.
"""

from __future__ import annotations

import hashlib
import re

#: The package-id prefix an activity report carries. A ``published`` walk
#: scoped to one collection still serves neighbours (3 of 3,000 CRPT-scoped ids
#: measured 2026-09-19), so :func:`is_activity_report` checks the row's own id
#: rather than trusting the request.
ACTIVITY_REPORT_COLLECTION = "CRPT"

#: The rule. Four clauses, all requiring a committee or the fixed phrase:
#: ``activities … committee``, ``committee … activities``, ``activity report``
#: and ``report on activities``. ``[^.]{0,80}`` keeps the two words inside one
#: sentence and within a title's own span, so a committee named a paragraph
#: away from the word does not count.
ACTIVITY_REPORT_TITLE = re.compile(
    r"(?i)activit(?:y|ies)\b[^.]{0,80}\bcommittee\b"
    r"|\bcommittee\b[^.]{0,80}\bactivit(?:y|ies)\b"
    r"|\bactivity report\b"
    r"|\breport on activities\b"
)

#: The rejected alternative, kept beside the rule rather than described in
#: prose: the bare word this rule refuses to be. It is the denominator of the
#: 20-against-15 measurement above, so a caller re-deriving that precision uses
#: the same object the rule was chosen against instead of writing its own.
ACTIVITY_WORD = re.compile(r"(?i)activit")

#: A digest over both patterns, so a version cannot be left behind by an edit
#: to the rule it names. The device ``interpretation.citations`` uses for its
#: own rule set. This is published on nothing yet; it exists so that when a
#: hosted row does carry it, the row names the rule that selected it.
ACTIVITY_REPORT_RULE_VERSION = hashlib.sha256(
    f"{ACTIVITY_REPORT_TITLE.pattern}\n{ACTIVITY_WORD.pattern}".encode()
).hexdigest()[:12]


def is_activity_report(package_id: str, title: str) -> bool:
    """Whether this ``published`` row is a committee activity report.

    Both halves are checked against the row itself: the id must carry the
    ``CRPT-`` prefix, because a collection-scoped walk serves neighbouring
    collections' ids, and the title must match :data:`ACTIVITY_REPORT_TITLE`.
    A non-string on either side is not a match rather than an error -- a
    publisher row with a missing field is a row to skip, not a run to stop.
    """
    if not isinstance(package_id, str) or not isinstance(title, str):
        return False
    return package_id.startswith(f"{ACTIVITY_REPORT_COLLECTION}-") and ACTIVITY_REPORT_TITLE.search(title) is not None


def names_activity(title: str) -> bool:
    """Whether the title contains the bare word -- the rejected rule's answer.

    The measurement's denominator, exposed so a caller reporting this rule's
    precision counts the same way the rule was chosen.
    """
    return isinstance(title, str) and ACTIVITY_WORD.search(title) is not None


__all__ = [
    "ACTIVITY_REPORT_COLLECTION",
    "ACTIVITY_REPORT_RULE_VERSION",
    "ACTIVITY_REPORT_TITLE",
    "ACTIVITY_WORD",
    "is_activity_report",
    "names_activity",
]
