"""Resolve a sponsor or voter reference to one member of Congress.

Reads a bioguide id where the publisher states one, a Senate LIS id where a
Senate vote states one, or a sponsor display string such as ``Rep. Griffith,
H. Morgan [R-VA-9]``, plus the community legislators crosswalk and the
published members rows, and returns a ``MemberMatch`` naming the bioguide id,
the rule and a score. Rule order is the point -- bioguide, then LIS through
the crosswalk, then name -- because reaching for a name when an id is present
is what the original did and this removes; only name matching can be wrong, so
its score is the only one below 1.0 and is always exposed for a consumer to
threshold. The name path strips the honorific and the bracketed
party/state/district block and prefers a surname before a comma, and
``last_name_of`` here is deliberately not
``bill_signals.sponsor_last_name_of``: this parses the publisher's structured
display name and is free to improve, while that one is sealed as half of a
stored identification score.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from spicy_docs.interpretation.bill_signals import normalize_for_comparison, token_jaccard

MEMBER_MATCH_RULES: tuple[str, ...] = ("bioguide", "lis", "name_exact", "name_last", "unmatched")
MIN_LAST_NAME_CHARS = 3

_HONORIFIC = re.compile(r"^(Rep|Sen|Representative|Senator|Del|Delegate|Commissioner)\.?\s*", re.IGNORECASE)
_BRACKETED = re.compile(r"\[[^\]]*\]")


@dataclass(frozen=True, slots=True)
class MemberQuery:
    """Whatever the caller holds. Every field is optional; the rules take them in order."""

    bioguide: str | None = None
    lis: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class MemberRow:
    """One published members row. ``end_date`` is ``None`` for a serving member."""

    bioguide: str
    name: str
    end_date: str | None = None


@dataclass(frozen=True, slots=True)
class MemberMatch:
    """``score`` is 1.0 for an identifier rule and a similarity for the name rules."""

    bioguide: str | None
    rule: str
    score: float
    query: MemberQuery
    matched_name: str | None = None


def last_name_of(name: str) -> str:
    """The surname in a publisher sponsor string, with honorific and bracket block removed."""
    stripped = _BRACKETED.sub(" ", _HONORIFIC.sub("", name.strip())).strip()
    if "," in stripped:
        head = stripped.split(",", 1)[0].strip()
        if head:
            return head.split()[-1]
    tokens = stripped.split()
    return tokens[-1] if tokens else ""


@dataclass(frozen=True, slots=True)
class MemberIndex:
    """Members normalized once, keyed both ways the name rules look them up.

    Built by ``index_members`` for the same reason ``compile_bill_patterns``
    exists next door: normalizing every member row inside the per-query loop
    would cost O(queries x members) normalizations of strings that never
    change, while built once a query costs two dictionary lookups.
    """

    by_name: Mapping[str, MemberRow]
    by_surname: Mapping[str, MemberRow]
    normalized: Mapping[str, str]


def index_members(members: Iterable[MemberRow]) -> MemberIndex:
    """Normalize each member row once. The only place this module normalizes a row.

    First row wins on a collision, so a stable input gives a stable answer.
    ``by_surname`` holds only serving members -- a row with an ``end_date`` was
    excluded from the last-name rule in the original's SQL and still is.
    """
    by_name: dict[str, MemberRow] = {}
    by_surname: dict[str, MemberRow] = {}
    normalized: dict[str, str] = {}
    for row in members:
        name = normalize_for_comparison(row.name)
        normalized.setdefault(row.bioguide, name)
        by_name.setdefault(name, row)
        if row.end_date is None:
            by_surname.setdefault(normalize_for_comparison(last_name_of(row.name)), row)
    return MemberIndex(by_name, by_surname, normalized)


def match_member(query: MemberQuery, *, crosswalk: object = None, members: MemberIndex | None = None) -> MemberMatch:
    """Take the identifier rules first; fall back to the name only when neither id resolves.

    ``crosswalk`` is a ``LegislatorsFile`` (anything carrying ``by_bioguide``
    and ``by_lis``) and ``members`` is an index built once by
    ``index_members``. With a crosswalk, an id it does not hold falls through
    rather than being asserted.
    """
    by_bioguide = getattr(crosswalk, "by_bioguide", None)
    by_lis = getattr(crosswalk, "by_lis", None)

    # With no crosswalk the publisher's own id stands; with one, an id the
    # crosswalk does not hold falls through rather than being asserted.
    if query.bioguide and (by_bioguide is None or query.bioguide in by_bioguide):
        return MemberMatch(query.bioguide, "bioguide", 1.0, query)

    if query.lis and isinstance(by_lis, Mapping):
        legislator = by_lis.get(query.lis)
        if legislator is not None:
            return MemberMatch(getattr(legislator, "bioguide", None), "lis", 1.0, query)

    if not query.name or members is None:
        return MemberMatch(None, "unmatched", 0.0, query)

    wanted = normalize_for_comparison(query.name)
    exact = members.by_name.get(wanted)
    if exact is not None:
        return MemberMatch(exact.bioguide, "name_exact", 1.0, query, exact.name)

    surname = last_name_of(query.name)
    if len(surname) < MIN_LAST_NAME_CHARS:
        return MemberMatch(None, "unmatched", 0.0, query)
    row = members.by_surname.get(normalize_for_comparison(surname))
    if row is not None:
        return MemberMatch(
            row.bioguide,
            "name_last",
            token_jaccard(wanted, members.normalized[row.bioguide]),
            query,
            row.name,
        )

    return MemberMatch(None, "unmatched", 0.0, query)


__all__ = [
    "MEMBER_MATCH_RULES",
    "MIN_LAST_NAME_CHARS",
    "MemberIndex",
    "MemberMatch",
    "MemberQuery",
    "MemberRow",
    "index_members",
    "last_name_of",
    "match_member",
]
