"""Which CRPT package is a committee activity report, and which Congress it says it reports on.

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

:func:`covered_congress` reads the Congress a report covers from the report's
own words, because neither index record states it: a Senate committee files
its report early in the *following* Congress, so the package id, the summary
and every MODS ``<bill>`` carry the filing Congress (CRPT-118srpt99 reports on
the 117th, and its MODS stamps H.R. 5376 as ``118``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

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


# --- the Congress a report covers -----------------------------------------------------

_BELOW_TWENTY = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
    "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
    "nineteenth",
)  # fmt: skip
_TENS = tuple(zip(("twent", "thirt", "fort", "fift", "sixt", "sevent", "eight", "ninet"), range(20, 100, 10)))
_ORDINAL_WORDS: dict[str, int] = {word: value for value, word in enumerate(_BELOW_TWENTY, start=1)} | {
    f"{stem}ieth": value for stem, value in _TENS
}
_CARDINAL_TENS: dict[str, int] = {f"{stem}y": value for stem, value in _TENS}

#: An ordinal Congress as a GPO cover or a GovInfo title spells it: ``117TH``,
#: GPO's ``102d``, ``ONE HUNDRED SEVENTEENTH``, ``One Hundred and Seventeenth``,
#: ``SEVENTY-FIFTH``. ``congres{2,3}`` reads the index's own ``118TH
#: CONGRESSS`` (CRPT-118hrpt953) and never ``Congressional``.
_ORDINAL = (
    r"(?:\d{1,3}(?:st|nd|rd|th|d)"
    r"|one\s+hundredth"
    r"|(?:one\s+hundred(?:\s+and)?\s+)?(?:(?:" + "|".join(_CARDINAL_TENS) + r")[\s-]+)?"
    r"(?:" + "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True)) + r"))"
)
_CONGRESS = rf"(?P<ordinal>{_ORDINAL})\s+congres{{2,3}}\b"

#: Any Congress a title names. A title is transcribed from the cover's title
#: block, which never carries the filing header, so no preposition is needed:
#: ``LEGISLATIVE AND OVERSIGHT ACTIVITIES of the COMMITTEE ON HOMELAND SECURITY
#: 118TH CONGRESS`` states its Congress with none.
TITLE_CONGRESS = re.compile(rf"(?i)\b{_CONGRESS}")

#: A Congress the print says it reports on: ``during``, ``for`` or ``in`` the
#: Congress. The preposition is what excludes the two other Congresses every
#: print states -- the filing header (``118TH CONGRESS 1st Session``, which on
#: CRPT-118srpt3 is set with ``REPORT`` between the two) and the current
#: roster's heading (CRPT-118srpt99 page II, ``COMMITTEE ON THE BUDGET ONE
#: HUNDRED EIGHTEENTH CONGRESS``, in a report on the 117th).
STATED_CONGRESS = re.compile(rf"(?i)\b(?:during|for|in)\s+the\s+{_CONGRESS}")

#: The GPO cover's closing line, so the cover is the text before it. Every one
#: of the 40 reports read 2026-09-26 sets it on page 1; CRPT-118hrpt962 prints
#: ``ordered to printed``.
COVER_END = re.compile(r"(?i)\bordered\s+to\s+(?:be\s+)?printed")

#: How far the front matter reaches: the cover, the letter of transmittal and
#: the contents. Measured 2026-09-26 over all 40 activity reports the
#: print-citations window holds (receipt ``fix-print-citations-2026-09-26/``):
#: the first five pages state exactly the covered Congress on every one --
#: including the three whose title and cover state none (CRPT-118hrpt941, -963,
#: -968, each in its transmittal letter) -- while eight pages already state
#: several on two (-961, -962), where the report turns to earlier Congresses.
FRONT_MATTER_PAGES = 5

#: The sources :func:`covered_congress` reads, strongest first. The first
#: that states any Congress decides; a weaker one is never consulted to break
#: a stronger one's tie.
COVERED_CONGRESS_SOURCES: tuple[str, ...] = ("title", "cover", "front_matter")

#: A digest over everything :func:`covered_congress` decides by, so a host can
#: tell a reading made under another rule from one made under this.
COVERED_CONGRESS_RULE_VERSION = hashlib.sha256(
    "\n".join(
        (
            TITLE_CONGRESS.pattern,
            STATED_CONGRESS.pattern,
            COVER_END.pattern,
            str(FRONT_MATTER_PAGES),
            *COVERED_CONGRESS_SOURCES,
        )
    ).encode()
).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class CoveredCongress:
    """The Congress a report says it reports on, and which of its own statements said so.

    ``congress`` is ``None`` when no source states one, and also when the first
    source that states any states several -- ``stated`` then lists them, so the
    refusal is readable rather than silent. ``source`` is ``None`` only when no
    source states a Congress at all.
    """

    congress: int | None
    source: str | None
    stated: tuple[int, ...] = ()


def ordinal_congress(spelled: str) -> int:
    """``117TH``, ``102d`` and ``One Hundred and Seventeenth`` are 117, 102 and 117."""
    words = re.sub(r"[\s-]+", " ", spelled.strip().lower())
    digits = re.fullmatch(r"(\d{1,3})(?:st|nd|rd|th|d)", words)
    if digits:
        return int(digits.group(1))
    if words == "one hundredth":
        return 100
    value = 0
    if words.startswith("one hundred "):
        value, words = 100, words.removeprefix("one hundred ").removeprefix("and ")
    tens, _, unit = words.rpartition(" ")
    return value + _CARDINAL_TENS.get(tens, 0) + _ORDINAL_WORDS[unit]


def covered_congress(title: str | None, pages: Sequence[str] | None) -> CoveredCongress:
    """Which Congress a report covers, by its title, then its cover, then its front matter.

    ``title`` is the index title (GovInfo's transcription of the cover's title
    block) and ``pages`` the print's per-page text. The cover is the text
    before the first :data:`COVER_END` inside the front matter, the first
    :data:`FRONT_MATTER_PAGES` pages. Neither index record is consulted: both
    state the filing Congress, which is the covered one for a House report and
    the next one for a Senate report. A report with no page split has no cover
    or front matter to read, so only its title can state one.
    """
    front = "\n".join(pages[:FRONT_MATTER_PAGES]) if pages else ""
    end = COVER_END.search(front)
    for source, span, pattern in (
        ("title", title or "", TITLE_CONGRESS),
        ("cover", front[: end.end()] if end else "", STATED_CONGRESS),
        ("front_matter", front, STATED_CONGRESS),
    ):
        stated = tuple(sorted({ordinal_congress(match.group("ordinal")) for match in pattern.finditer(span)}))
        if stated:
            return CoveredCongress(stated[0] if len(stated) == 1 else None, source, stated)
    return CoveredCongress(None, None)


__all__ = [
    "ACTIVITY_REPORT_COLLECTION",
    "ACTIVITY_REPORT_RULE_VERSION",
    "ACTIVITY_REPORT_TITLE",
    "ACTIVITY_WORD",
    "COVERED_CONGRESS_RULE_VERSION",
    "COVERED_CONGRESS_SOURCES",
    "COVER_END",
    "FRONT_MATTER_PAGES",
    "STATED_CONGRESS",
    "TITLE_CONGRESS",
    "CoveredCongress",
    "covered_congress",
    "is_activity_report",
    "names_activity",
    "ordinal_congress",
]
