"""Match a reader's interest-area keywords against bill section bodies.

Reads parsed bill sections (heading and body) as the published section table
holds them, and returns a ``SectionMatch`` per hit naming the area, the
keywords that matched, the rule, the relevance that ordered it and a
fixed-length excerpt. Only the matching half of
``BillTrax/src/lib/interest-areas.ts`` is here -- the keyword list is a user's
own and is never a sealed vocabulary -- and the InnoDB full-text defaults its
boolean-mode query ran under (token length 3-84, MySQL 8.4's default stopword
table) are applied to both sides, because a token outside them can never drive
a match. Relevance is an adopted deterministic ordering, not a reproduction of
BillTrax's: its query carried no ``ORDER BY``, so its rows arrived in storage
order, while this orders by count of distinct matched keywords with input
position breaking ties.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from spicy_docs.interpretation.bill_signals import normalize_for_comparison

EXCERPT_CHARS = 200
DEFAULT_LIMIT = 20
INTEREST_AREA_RULES: tuple[str, ...] = ("keyword_any",)

# MySQL 8.4 InnoDB full-text defaults BillTrax ran under -- see the module
# docstring for the measurement and the manual pages this comes from.
INNODB_FT_MIN_TOKEN_SIZE = 3
INNODB_FT_MAX_TOKEN_SIZE = 84
INNODB_FT_STOPWORDS: frozenset[str] = frozenset(
    (
        "a",
        "about",
        "an",
        "are",
        "as",
        "at",
        "be",
        "by",
        "com",
        "de",
        "en",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "la",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "who",
        "will",
        "with",
        "und",
        "www",
    )
)


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
    relevance: int


def _index_tokens(text: str) -> frozenset[str]:
    """Tokens of ``text`` as InnoDB's default full-text index would keep them.

    Applied identically to a keyword and to a section body -- BillTrax's query
    ran both sides through the same index -- so a token shorter than
    ``INNODB_FT_MIN_TOKEN_SIZE``, longer than ``INNODB_FT_MAX_TOKEN_SIZE``, or
    a member of ``INNODB_FT_STOPWORDS`` is dropped before either side is
    compared.
    """
    return frozenset(
        token
        for token in normalize_for_comparison(text).split()
        if INNODB_FT_MIN_TOKEN_SIZE <= len(token) <= INNODB_FT_MAX_TOKEN_SIZE and token not in INNODB_FT_STOPWORDS
    )


def keyword_tokens(keyword: str) -> frozenset[str]:
    """A keyword's indexed tokens; a multi-word keyword contributes each surviving word."""
    return _index_tokens(keyword)


def find_matching_sections(
    areas: Iterable[InterestArea], sections: Sequence[Section], *, limit: int = DEFAULT_LIMIT
) -> tuple[SectionMatch, ...]:
    """Match every area against every section, normalizing each input exactly once.

    Within one area a match's ``relevance`` is the count of distinct matched
    keywords, highest first, with the section's position in ``sections``
    breaking ties, so the top ``limit`` of an area are always its
    earliest-appearing best matches; the whole-result limit then keeps areas in
    the order they were given. Ranking an area's matches needs every one of
    them evaluated before any can be discarded, so the cost is ``O(areas x
    sections log sections)`` rather than ``O(areas x sections)``. Raises
    ``ValueError`` for a negative limit.
    """
    if limit < 0:
        raise ValueError("limit must be non-negative")
    body_tokens = [_index_tokens(section.body) for section in sections]

    results: list[SectionMatch] = []
    for area in areas:
        if not area.keywords:
            continue
        area_tokens = [(keyword, keyword_tokens(keyword)) for keyword in area.keywords]
        area_matches: list[tuple[int, int, SectionMatch]] = []
        for position, (section, tokens) in enumerate(zip(sections, body_tokens, strict=True)):
            matched = tuple(keyword for keyword, wanted in area_tokens if wanted & tokens)
            if not matched:
                continue
            relevance = len(matched)
            area_matches.append(
                (
                    relevance,
                    position,
                    SectionMatch(
                        section_id=section.section_id,
                        version_id=section.version_id,
                        bill_id=section.bill_id,
                        heading=section.heading,
                        excerpt=section.body[:EXCERPT_CHARS],
                        area_name=area.name,
                        rule="keyword_any",
                        keywords=matched,
                        relevance=relevance,
                    ),
                )
            )
        area_matches.sort(key=lambda entry: (-entry[0], entry[1]))
        results.extend(match for _, _, match in area_matches[:limit])
    return tuple(results[:limit])


__all__ = [
    "DEFAULT_LIMIT",
    "EXCERPT_CHARS",
    "INNODB_FT_MAX_TOKEN_SIZE",
    "INNODB_FT_MIN_TOKEN_SIZE",
    "INNODB_FT_STOPWORDS",
    "INTEREST_AREA_RULES",
    "InterestArea",
    "Section",
    "SectionMatch",
    "find_matching_sections",
    "keyword_tokens",
]
