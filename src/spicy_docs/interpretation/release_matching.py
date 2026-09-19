"""Join a committee press release to the bill it names.

Publisher fact in: RSS items from the House and Senate appropriations
committees (``title``, and ``description`` only where the publisher sends one)
and the bill identities in the catalog.

Interpretation out: a ``ReleaseMatch`` per release naming the bill, the rule
that fired, which field the mention was found in and the exact text that
matched.

Two corrections to ``BillTrax/src/lib/press-releases.ts:131-160``:

* **One compiled pattern per bill, built once.** The original built a fresh
  ``new RegExp`` inside a nested loop over 500 releases and 1,000 bills -- up
  to 500,000 compilations per run for 1,000 distinct patterns.
  ``compile_bill_patterns`` is the only place this module compiles anything,
  and it compiles exactly one pattern per bill.
* **The pattern is built from the bill's own type, and the number is
  escaped.** The original tried ``H.R.`` and ``S.`` against every bill
  whatever its type, and then offered the bare, unescaped number as a third
  alternative -- so a bill numbered ``1`` matched any ``1`` anywhere in any
  release title. Here each bill gets the prose spelling of its own type,
  bounded on both sides, and nothing matches a bare number.

``matched_field`` is reported because the two feeds are not shaped alike: the
Senate feed's items carry ``title``, ``link``, ``author``, ``pubDate`` and
``guid`` and **no** ``<description>`` at all (measured 2026-09-19), so an
excerpt is permanently empty there and every Senate match is a title match.
Matching therefore runs field by field -- title first -- rather than over a
concatenation, so a stored row says what the match was actually made of.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from spicy_docs.sources.congress.bill_status import BillIdentity

# The prose spelling of each bill type, as a committee release writes it.
BILL_TYPE_PROSE: Mapping[str, str] = MappingProxyType(
    {
        "hr": r"H\.?\s*R\.?",
        "s": r"S\.?",
        "hjres": r"H\.?\s*J\.?\s*Res\.?",
        "sjres": r"S\.?\s*J\.?\s*Res\.?",
        "hconres": r"H\.?\s*Con\.?\s*Res\.?",
        "sconres": r"S\.?\s*Con\.?\s*Res\.?",
        "hres": r"H\.?\s*Res\.?",
        "sres": r"S\.?\s*Res\.?",
    }
)

MATCH_FIELDS: tuple[str, ...] = ("title", "excerpt")
RELEASE_MATCH_RULES: tuple[str, ...] = ("bill_number_in_title", "bill_number_in_excerpt", "unmatched")


class ReleaseMatchError(ValueError):
    """A bill or release cannot be read into the shape this matcher needs."""


@dataclass(frozen=True, slots=True)
class BillPattern:
    """One bill and the single compiled pattern that recognises a mention of it."""

    bill: BillIdentity
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class Release:
    """``excerpt`` is ``None`` on a feed whose items carry no description."""

    release_id: str
    title: str
    excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class ReleaseMatch:
    """``bill`` is ``None`` and ``rule`` is ``unmatched`` when no bill was named."""

    release_id: str
    bill: BillIdentity | None
    rule: str
    matched_field: str | None = None
    matched_text: str | None = None


def bill_mention_pattern(bill: BillIdentity) -> str:
    """The source of the one pattern compiled per bill, bounded on both sides."""
    prose = BILL_TYPE_PROSE.get(bill.bill_type)
    if prose is None:
        raise ReleaseMatchError(f"no prose spelling for bill type {bill.bill_type!r}")
    # The left boundary also excludes a preceding dot so "U.S. 5" is not read
    # as Senate bill 5; the right one keeps bill 5 out of "50".
    return rf"(?<![A-Za-z0-9.]){prose}\s*{re.escape(str(bill.number))}(?![0-9])"


def compile_bill_patterns(bills: Iterable[BillIdentity]) -> tuple[BillPattern, ...]:
    """Compile exactly one pattern per bill. The only compilation this module performs."""
    return tuple(BillPattern(bill, re.compile(bill_mention_pattern(bill), re.IGNORECASE)) for bill in bills)


def _release_fields(release: object) -> tuple[str, Mapping[str, str | None]]:
    if isinstance(release, Release):
        return release.release_id, {"title": release.title, "excerpt": release.excerpt}
    if isinstance(release, Mapping):
        identifier = release.get("release_id") or release.get("id")
        if not isinstance(identifier, str):
            raise ReleaseMatchError("a release must carry a string release_id")
        return identifier, {field: release.get(field) for field in MATCH_FIELDS}
    raise ReleaseMatchError("a release must be a Release or a mapping")


def match_releases(
    releases: Iterable[object], patterns: Sequence[BillPattern], *, fields: Sequence[str] = MATCH_FIELDS
) -> tuple[ReleaseMatch, ...]:
    """Scan each release against the precompiled patterns, field by field, first hit wins.

    Cost is one pass over the releases times the patterns, with no compilation
    in the loop: O(releases x bills) comparisons and O(bills) compilations,
    against the original's O(releases x bills) compilations.
    """
    matches: list[ReleaseMatch] = []
    for release in releases:
        release_id, values = _release_fields(release)
        match = ReleaseMatch(release_id, None, "unmatched")
        for field in fields:
            value = values.get(field)
            if not value:
                continue
            hit = None
            for entry in patterns:
                hit = entry.pattern.search(value)
                if hit is not None:
                    match = ReleaseMatch(release_id, entry.bill, f"bill_number_in_{field}", field, hit.group(0))
                    break
            if hit is not None:
                break
        matches.append(match)
    return tuple(matches)


__all__ = [
    "BILL_TYPE_PROSE",
    "MATCH_FIELDS",
    "RELEASE_MATCH_RULES",
    "BillPattern",
    "Release",
    "ReleaseMatch",
    "ReleaseMatchError",
    "bill_mention_pattern",
    "compile_bill_patterns",
    "match_releases",
]
