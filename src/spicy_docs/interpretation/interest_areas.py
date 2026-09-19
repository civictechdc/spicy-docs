"""Match a reader's interest-area keywords against bill section bodies.

Publisher fact in: parsed bill sections (heading and body) as the published
section table holds them.

Interpretation out: a ``SectionMatch`` per hit, naming the area, the keywords
that matched, the rule that fired, the relevance that ordered it and a
fixed-length excerpt.

Only the matching half of ``BillTrax/src/lib/interest-areas.ts`` is here. The
CRUD half (:23-81) stores per-user rows and belongs to a UI, not to shared
logic; the keyword list is a user's own and is never a sealed vocabulary.

**The engine defaults, measured rather than assumed.** BillTrax matched with
``MATCH(bs.body) AGAINST(? IN BOOLEAN MODE)`` (``src/lib/interest-areas.ts:83-141``)
over a space-joined keyword string, then ``LIMIT ?`` with no ``ORDER BY`` at
all. Outside MySQL that operator does not exist, so what a row matching in
boolean mode *means* has to be encoded rather than called: a row matches when
it contains any keyword token that survived the engine's own index. Every
``docker-compose*.yml`` in BillTrax pins ``mysql:8.4``
(``docker-compose.yml.example``, ``docker-compose.prod.yml``,
``docker-compose.staging.yml``) and none of them, nor ``mysql-init.sql``, sets
``innodb_ft_min_token_size``, ``innodb_ft_max_token_size`` or a stopword-table
override, and ``bill_sections``/``report_sections`` take their FULLTEXT index
on InnoDB's default engine (``migrations/007_fulltext_indexes.ts``) -- so the
defaults below are the ones the query actually ran under, from the MySQL 8.4
Reference Manual:

* Token-length floor and ceiling, `Fine-Tuning MySQL Full-Text Search
  <https://dev.mysql.com/doc/refman/8.4/en/fulltext-fine-tuning.html>`_:
  ``innodb_ft_min_token_size`` defaults to 3, ``innodb_ft_max_token_size`` to
  84. A token outside ``[3, 84]`` never enters the index and so can never
  drive a match, whichever side of the comparison it came from.
* The default stopword table, `The INFORMATION_SCHEMA
  INNODB_FT_DEFAULT_STOPWORD Table
  <https://dev.mysql.com/doc/refman/8.4/en/information-schema-innodb-ft-default-stopword-table.html>`_:
  36 rows, though the manual's own example output lists ``the`` twice, so
  ``INNODB_FT_STOPWORDS`` below holds the 35 distinct words. A stopword is
  dropped from the index the same way a too-short or too-long token is.
* Relevance, `Boolean Full-Text Searches
  <https://dev.mysql.com/doc/refman/8.4/en/fulltext-boolean.html>`_: a
  matched row's relevance is the sum of its matched terms' weights, but --
  the manual states this plainly -- "boolean full-text searches do not
  automatically sort rows in order of decreasing relevance," and BillTrax's
  own query carries no ``ORDER BY``. So the order 40,260 rows actually came
  back in was never the engine's relevance ranking; it was whatever InnoDB's
  query plan happened to produce, which the application never controlled and
  this module cannot recover. What ``find_matching_sections`` encodes instead
  is the *documented formula*, applied as an explicit, deterministic
  ordering this module chooses to keep rather than an ordering BillTrax
  itself ever guaranteed: relevance is the count of distinct matched
  keywords (each surviving keyword weighs 1, since true term weighting needs
  a corpus-wide document frequency this pure, per-call function is not
  handed), and a section's position in the input sequence breaks ties, so
  the same input always orders the same way.

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
    a member of ``INNODB_FT_STOPWORDS`` is dropped before either side is ever
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

    Each section body is normalized once and each keyword is tokenized once,
    both outside the pairwise loop, so the cost is O(total body characters +
    total keyword characters) of normalization plus O(areas x sections) set
    intersections -- the same two terms the unfiltered version paid. Ranking
    an area's matches by relevance needs every one of them evaluated before
    any can be discarded, so, unlike the unfiltered version, a section already
    past the per-area limit is not skipped early; the extra cost is one sort
    of at most ``len(sections)`` matches per area, O(sections log sections),
    which does not change the dominant O(areas x sections) term.

    Within one area, a match's ``relevance`` is the count of distinct matched
    keywords (see the module docstring for the formula this stands in for),
    highest first; a tie keeps the section's position in ``sections``, so the
    top ``limit`` of an area are always its earliest-appearing best matches.
    The whole-result limit then keeps areas in the order they were given.
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
