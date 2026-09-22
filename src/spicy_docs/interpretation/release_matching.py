"""Join a committee press release to the bill it names.

Reads RSS items from the House and Senate appropriations committees (``title``,
and ``description`` only where the publisher sends one) and the bill identities
in the catalog, and returns a ``ReleaseMatch`` per release naming the bill, the
rule, which field the mention was found in and the exact text that matched.
``compile_bill_patterns`` compiles one pattern per bill for callers that need
them; ``match_releases`` itself scans each field once with a single alternation
pattern and resolves mentions through a bill index, so matching costs one regex
pass per field rather than one pattern search per bill.
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

# Most specific spelling first, so "H.J.Res." cannot be read as an H.Res.
# or H.R. mention; the same order drives the alternation and the group scan.
_MENTION_TYPE_ORDER: tuple[str, ...] = ("hjres", "hconres", "hres", "hr", "sjres", "sconres", "sres", "s")

# One compiled alternation for every type spelling, with the same boundaries
# each per-bill pattern carries: no letter/digit/dot or possessive apostrophe
# immediately before, no digit immediately after the number.
_MENTION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.])(?<!\w['’])"
    + "(?:"
    + "|".join(
        rf"(?P<{bill_type}>{BILL_TYPE_PROSE[bill_type]})\s*(?P<{bill_type}_num>\d+)"
        for bill_type in _MENTION_TYPE_ORDER
    )
    + ")"
    + r"(?![0-9])",
    re.IGNORECASE,
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
    # as Senate bill 5. A word's possessive suffix is not a Senate prefix,
    # while a quoted 'S. 5' can still name one. The right bound excludes "50".
    return rf"(?<![A-Za-z0-9.])(?<!\w['’]){prose}\s*{re.escape(str(bill.number))}(?![0-9])"


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


def _bill_index(patterns: Sequence[BillPattern]) -> dict[tuple[str, str], tuple[int, BillPattern]]:
    """Bill lookup by ``(bill_type, number-as-written)``, keeping the first of any duplicates.

    The catalog position is kept so a field naming two bills resolves to the
    one earlier in ``patterns``, exactly as the per-bill scan did.
    """
    index: dict[tuple[str, str], tuple[int, BillPattern]] = {}
    for position, entry in enumerate(patterns):
        key = (entry.bill.bill_type, str(entry.bill.number))
        if key not in index:
            index[key] = (position, entry)
    return index


def _mentioned_bills(value: str, index: dict[tuple[str, str], tuple[int, BillPattern]]) -> dict[tuple[str, str], str]:
    """Every indexed bill a field mentions, to its first mention's exact text.

    One regex pass finds all mentions; each is looked up by the number exactly
    as written, so a zero-padded ``005`` does not name bill ``5``.
    """
    mentions: dict[tuple[str, str], str] = {}
    for mention in _MENTION_PATTERN.finditer(value):
        groups = mention.groupdict()
        for bill_type in _MENTION_TYPE_ORDER:
            if groups.get(bill_type) is not None:
                key = (bill_type, groups[f"{bill_type}_num"])
                if key in index and key not in mentions:
                    mentions[key] = mention.group(0)
                break
    return mentions


def match_releases(
    releases: Iterable[object], patterns: Sequence[BillPattern], *, fields: Sequence[str] = MATCH_FIELDS
) -> tuple[ReleaseMatch, ...]:
    """Scan each release against the compiled bills, field by field, first hit wins.

    Cost is one regex pass per nonempty field (``O(releases x fields x text)``)
    plus one index build over the bills, with no compilation and no per-bill
    search in the loop. When a field names several bills, the one earlier in
    ``patterns`` wins and its own first mention is the matched text.
    """
    index = _bill_index(patterns)
    matches: list[ReleaseMatch] = []
    for release in releases:
        release_id, values = _release_fields(release)
        match = ReleaseMatch(release_id, None, "unmatched")
        for field in fields:
            value = values.get(field)
            if not value:
                continue
            mentions = _mentioned_bills(value, index)
            if mentions:
                key = min(mentions, key=lambda candidate: index[candidate][0])
                entry = index[key][1]
                match = ReleaseMatch(release_id, entry.bill, f"bill_number_in_{field}", field, mentions[key])
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
