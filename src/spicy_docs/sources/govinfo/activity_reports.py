"""Which CRPT package is a committee activity report, by its index title.

An end-of-Congress committee activity report is an ordinary ``CRPT`` package:
nothing in its id, its ``docClass`` or its MODS says it is one. The only
publisher statement that separates it from every other committee report in the
same collection walk is **its own title**, so this rule reads that title and
nothing else. It is a selection rule over the ``published`` listing row, not an
interpretation of a body: the collection walk lives in ``discovery.py``, the
body fetch in ``bodies.py``, and the tables the selected packages fill in
``schemas/document_citation_tables.py``.

**The phrase, never the bare word.** ``activit`` alone takes in ordinary
committee reports whose subject happens to be an agency's activities. Measured
2026-09-20 over the 71 ``CRPT`` packages GovInfo's ``published`` walk served
for 2025-01-01..2025-03-31 (receipt
``activity-report-title-rule-2026-09-20/``, re-derived request-free from the
index page that walk retained):

===============================================  ====
Packages walked                                    71
Titles containing ``activit``                      20
Titles :data:`ACTIVITY_REPORT_TITLE` matches       15
===============================================  ====

The five the phrase rejects are both classes this rule is answerable for:

- **Three are the false positives it exists to reject** -- two
  ``DIRECTING THE SECRETARY OF … RELATING TO … POLICIES AND ACTIVITIES …``
  resolutions and one ``PROVIDING FOR CONSIDERATION OF THE BILL (H.R. 471) …
  IMPROVE FOREST MANAGEMENT ACTIVITIES``. None is an activity report; all
  three match the bare word.
- **Two are activity reports this rule misses**: ``SUMMARY OF ACTIVITIES ONE
  HUNDRED EIGHTEENTH CONGRESS`` and ``REVIEW OF LEGISLATIVE ACTIVITY DURING
  THE 118TH CONGRESS``. Both name a Congress and no committee, and every
  clause here needs either the word ``committee`` or the fixed phrase
  ``activity report``. **The rule is not widened to reach them**, because
  dropping the committee requirement is exactly what readmits the three above;
  the miss is recorded here instead, so a caller reads a floor and knows why.

So what a caller gets is 15 of a titled 17 on the measured window, with the
two misses named. Widening this rule means measuring it again over a window
that separates the two classes, and moving
:data:`ACTIVITY_REPORT_RULE_VERSION` with it.

**Why this lives in the package.** It was written in
``tools/analysis/pdf_family_rollup.py`` and the wheel does not ship ``tools/``,
so the first host to build these tables had to restate the regex --
`spicy-regs`'s ``transforms/build_print_citations.py``, whose own docstring
calls it "the one selection rule in this module that is a copy rather than an
import". **spicy-regs imports this module now and that restatement can be
deleted there.** The two analysis tools import it too, so the measurement and
the product cannot drift apart -- the same reason
``interpretation/citations.py`` owns the citation rules both run.

The committee-name vocabulary did *not* move with it: the builder
(``interpretation.citations.committee_vocabulary``) is already in the package,
and what is tools-side is only which pinned roster fixtures the measurement
feeds it, which a package must not depend on.

``O(T)`` in the title's length; no request, no file, no state.
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
