"""Match a reader's interest-area keywords against bill section bodies.

Publisher fact in: parsed bill sections (heading and body) as the published
section table holds them.

Interpretation out: a ``SectionMatch`` per hit, naming the area, the keywords
that matched, the rule that fired and a fixed-length excerpt.

Only the matching half of ``BillTrax/src/lib/interest-areas.ts`` is here. The
CRUD half (:23-81) stores per-user rows and belongs to a UI, not to shared
logic; the keyword list is a user's own and is never a sealed vocabulary.

**What this cannot reproduce, stated rather than assumed.** BillTrax matched
with ``MATCH(bs.body) AGAINST(? IN BOOLEAN MODE)`` over a space-joined keyword
string. Outside MySQL that operator does not exist, and re-implementing it
changes results in ways worth naming: MySQL boolean mode drops words shorter
than ``innodb_ft_min_token_size`` (3 by default), drops stopwords, and orders
by its own relevance. This implementation reproduces the part that is a
decision -- a row matches when it contains **any** keyword token, which is
what an operator-free boolean-mode query means -- and reproduces neither the
length floor, the stopword list nor the relevance order, which are engine
behaviour. It returns sections in the order given, and any comparison against
the MySQL results is a measurement still owed, not an assumption made here.

The limit is applied twice, per area and again over the whole result, because
that is what the original did and the two bounds are not the same bound.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from spicy_docs.interpretation.bill_signals import normalize_for_comparison

EXCERPT_CHARS = 200
DEFAULT_LIMIT = 20
INTEREST_AREA_RULES: tuple[str, ...] = ("keyword_any",)


@dataclass(frozen=True, slots=True)
class InterestArea:
    """One reader's named keyword list. The keywords are theirs, not a vocabulary."""

    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Section:
    """One published bill-section row."""

    section_id: str
    version_id: str
    bill_id: str
    body: str
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class SectionMatch:
    section_id: str
    version_id: str
    bill_id: str
    heading: str | None
    excerpt: str
    area_name: str
    rule: str
    keywords: tuple[str, ...]


def keyword_tokens(keyword: str) -> frozenset[str]:
    """A keyword's normalized tokens; a multi-word keyword contributes each word."""
    return frozenset(normalize_for_comparison(keyword).split())


def find_matching_sections(
    areas: Iterable[InterestArea], sections: Sequence[Section], *, limit: int = DEFAULT_LIMIT
) -> tuple[SectionMatch, ...]:
    """Match every area against every section in one normalization pass over the bodies.

    Each body is normalized once, not once per area, so the cost is O(total
    body bytes) plus O(areas x sections) set intersections, against the
    original's one full-text scan per area.
    """
    if limit < 0:
        raise ValueError("limit must be non-negative")
    body_tokens = [frozenset(normalize_for_comparison(section.body).split()) for section in sections]

    results: list[SectionMatch] = []
    for area in areas:
        if not area.keywords:
            continue
        per_area = 0
        for section, tokens in zip(sections, body_tokens, strict=True):
            if per_area >= limit:
                break
            matched = tuple(keyword for keyword in area.keywords if keyword_tokens(keyword) & tokens)
            if not matched:
                continue
            per_area += 1
            results.append(
                SectionMatch(
                    section_id=section.section_id,
                    version_id=section.version_id,
                    bill_id=section.bill_id,
                    heading=section.heading,
                    excerpt=section.body[:EXCERPT_CHARS],
                    area_name=area.name,
                    rule="keyword_any",
                    keywords=matched,
                )
            )
    return tuple(results[:limit])


__all__ = [
    "DEFAULT_LIMIT",
    "EXCERPT_CHARS",
    "INTEREST_AREA_RULES",
    "InterestArea",
    "Section",
    "SectionMatch",
    "find_matching_sections",
    "keyword_tokens",
]
