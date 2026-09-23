"""Join a committee press release to the bill it names.

Reads RSS items from the House and Senate appropriations committees (``title``,
and ``description`` only where the publisher sends one) and the bill identities
in the catalog, and returns a ``ReleaseMatch`` per release naming the bill, the
rule, which field the mention was found in and the exact text that matched.
A mention is what the shared ``bill_number`` citation rule reads
(``interpretation.citations``: ``CONGRESS_CHAMBER`` and
``bill_type_and_number``), so a release and a committee print read one bill
number one way; ``match_releases`` scans each field once and resolves
mentions through a bill index, so matching costs one regex pass per field
rather than one pattern search per bill.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from spicy_docs.interpretation.citations import CITATION_RULES_BY_NAME, bill_type_and_number
from spicy_docs.sources.congress.bill_status import BillIdentity

#: The bill-number reader every mention goes through, compiled once: the
#: shared citation rule, whose own ``version`` is what versions a mention.
#: It replaced this module's case-insensitive alternation of per-type
#: spellings on 2026-09-23 (consolidation item A9): it needs a separator after
#: the designator, so a Congressional Record page (``CR S4530``) or a U.S. Code
#: section (``U.S.C. S300f``) is not a Senate bill, and it takes the capitals
#: as its evidence, so neither ``President's 2027`` nor a lower-case ``s 2027``
#: nor an unspaced ``HR1234`` names one. No bill link on the 28 retained press
#: rows moved. ``press_releases`` carries no version column, so a re-run is
#: what re-reads a row (its merge prefers the newest ``observed_at``).
_BILL_MENTION = CITATION_RULES_BY_NAME["bill_number"].compiled()

MATCH_FIELDS: tuple[str, ...] = ("title", "excerpt")
RELEASE_MATCH_RULES: tuple[str, ...] = ("bill_number_in_title", "bill_number_in_excerpt", "unmatched")


class ReleaseMatchError(ValueError):
    """A bill or release cannot be read into the shape this matcher needs."""


@dataclass(frozen=True, slots=True)
class BillPattern:
    """One catalog bill a release may name.

    The name is kept from when each bill carried its own compiled pattern,
    because spicy-regs' press-release transform imports it; mentions are now
    read once per field by the shared bill-number rule and looked up here.
    """

    bill: BillIdentity


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


def compile_bill_patterns(bills: Iterable[BillIdentity]) -> tuple[BillPattern, ...]:
    """One entry per bill, in catalog order, which is the order a tie is settled in.

    Nothing is compiled per bill any more. The name stays for its callers;
    ``BillIdentity`` already refuses a type the bill-number rule cannot spell.
    """
    return tuple(BillPattern(bill) for bill in bills)


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
    for mention in _BILL_MENTION.finditer(value):
        key = bill_type_and_number(mention.group(0))
        if key in index and key not in mentions:
            mentions[key] = mention.group(0)
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
    "MATCH_FIELDS",
    "RELEASE_MATCH_RULES",
    "BillPattern",
    "Release",
    "ReleaseMatch",
    "ReleaseMatchError",
    "compile_bill_patterns",
    "match_releases",
]
