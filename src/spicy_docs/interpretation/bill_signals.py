"""Identify which catalog bill a loose document is, from the text alone.

Publisher fact in: normalized page text of a bill document (the GPO rendering,
after line numbers and running heads have been stripped), plus candidate rows
from the published bill catalog.

Interpretation out: an ``ExtractedSignals`` record naming which extraction
tier produced the title, and a ranked tuple of ``BillMatch`` records whose
confidence is the weighted sum of five signals, each signal reported with its
own weight and score so a stored row can be read back rule by rule.

The windows, patterns, weights and thresholds are the sealed part and are
ported unchanged from ``BillTrax/src/lib/bill-identify.ts``: the first 3 KB
for bill number and congress, the first 6 KB for the sponsor (long titles push
the sponsor line past 3 KB), the whole text for the short title and section
headings, weights 0.55 / 0.20 / 0.10 / 0.10 / 0.05 summing to 1.0, congress
off-by-one worth 0.3, heading overlap accepted at Jaccard 0.5, at most five
results and none below 0.1 confidence.

``normalize_for_comparison`` deliberately keeps ASCII ``\\w`` semantics rather
than Python's Unicode default. Both sides of every comparison pass through it,
so the choice is symmetric either way; keeping the original class keeps
already-stored normalized titles and their Jaccard scores comparable across
the port, which is the point of a sealed contract.

The database half is gone. BillTrax ran a SQL lookup per phase and capped
section-heading lookups at three queries; here the caller supplies candidates
and ``MAX_HEADING_COMPARISONS`` keeps the same bound as a bound on work, so
the function is pure and the cost is still stated.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

HEAD_CHARS = 3000
SPONSOR_HEAD_CHARS = 6000
MARKER_WINDOW_CHARS = 10000
MARKER_TAIL_CHARS = 250
POSITION_FALLBACK = (200, 600)
MAX_SECTION_HEADINGS = 5

W_BILL_NUMBER = 0.55
W_TITLE = 0.20
W_CONGRESS = 0.10
W_SPONSOR = 0.10
W_SECTION_HEADINGS = 0.05
SIGNAL_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "bill_number": W_BILL_NUMBER,
        "title_similarity": W_TITLE,
        "congress": W_CONGRESS,
        "sponsor": W_SPONSOR,
        "section_heading_overlap": W_SECTION_HEADINGS,
    }
)

IDENTIFY_CONFIDENCE_THRESHOLDS: Mapping[str, float] = MappingProxyType({"high": 0.85, "medium": 0.55})
CONGRESS_OFF_BY_ONE_SCORE = 0.3
HEADING_OVERLAP_MIN_JACCARD = 0.5
MAX_HEADING_COMPARISONS = 3
MAX_CANDIDATES = 5
MIN_CONFIDENCE = 0.1

TITLE_SOURCES: tuple[str, ...] = ("may-be-cited-as", "fallback-marker", "fallback-position", "none")

_PROSE_BILL_NUMBER = re.compile(
    r"\b(H\.?\s*R\.?|S\.?|H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?"
    r"|H\.?\s*Con\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?|H\.?\s*Res\.?|S\.?\s*Res\.?)\.?\s*(\d{1,5})\b",
    re.IGNORECASE,
)
# The GPO bullet line, "•HR  7148  IH".
_BULLET_BILL_NUMBER = re.compile(r"[•·]\s*(HR|S|HJRES|SJRES|HCONRES|SCONRES|HRES|SRES)\s+(\d{1,5})\s", re.IGNORECASE)
_CONGRESS = re.compile(r"(\d{2,3})(?:st|nd|rd|th)?\s*Congress", re.IGNORECASE)
# The '' alternative consumes GPO's doubled single quote as one delimiter.
_SHORT_TITLE = re.compile(r"may be cited as (?:the\s+)?(?:''|[\"'`“‘]) *(.+?) *(?:''|[\"'`”’])", re.IGNORECASE)
_BILL_MARKER = re.compile(r"\b(?:A\s+BILL|AN\s+ACT)\b", re.IGNORECASE)
_MARKER_STOP = re.compile(r"Be it enacted|SECTION\s+1[\s\.—]|SEC\.\s*1[\s\.—]", re.IGNORECASE)
# Deliberately case-sensitive: the honorific and the small-caps surname are the
# signal. Two groups rejoin a name whose first letter was split onto its own
# line by the small-caps rendering ("Mr. C\nOLEintroduced" is COLE).
_SPONSOR = re.compile(r"\b(?:Mr|Ms|Mrs|Mx|MR|MS|MRS|MX)\.?\s+([A-Z])\s*\n?\s*([A-Z]{2,})(?:[a-z]+|\b)")
_SECTION_HEADING = re.compile(r"^SEC(?:TION|\.)?\s*(\d+)\.?\s*[—\-.]?\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]", re.ASCII)
_DB_LAST_NAME = re.compile(r"[A-Z]{2,}")
_SPONSOR_SPLIT = re.compile(r"[\s,]+")


@dataclass(frozen=True, slots=True)
class ExtractedSignals:
    """``title_source`` is the only observability on extraction quality; keep it stored."""

    bill_type: str | None
    bill_number: str | None
    congress: int | None
    normalized_title: str | None
    title_source: str
    sponsor_last_name: str | None
    section_headings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateBill:
    """One published catalog row, with the section headings of its latest version."""

    bill_id: str
    congress: int
    bill_type: str
    number: str
    title: str
    short_title: str | None = None
    sponsor: str | None = None
    section_headings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SignalScore:
    name: str
    weight: float
    score: float
    found: str | None = None
    matched: int | None = None
    total: int | None = None


@dataclass(frozen=True, slots=True)
class BillMatch:
    bill_id: str
    congress: int
    bill_type: str
    number: str
    title: str
    confidence: float
    signals: tuple[SignalScore, ...]


def normalize_for_comparison(value: str) -> str:
    """Lowercase, punctuation to space, whitespace collapsed. Part of the sealed contract."""
    return _WHITESPACE.sub(" ", _NON_WORD.sub(" ", value.lower())).strip()


def token_jaccard(left: str, right: str) -> float:
    """Jaccard over whitespace tokens; two empty strings are identical, one empty is not."""
    left_tokens = {token for token in left.split() if token}
    right_tokens = {token for token in right.split() if token}
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    return intersection / (len(left_tokens) + len(right_tokens) - intersection)


def normalize_bill_type(raw: str) -> str:
    """``H.R.`` and ``H R`` both become ``HR``."""
    return _WHITESPACE.sub("", re.sub(r"\.\s*", "", raw.upper())).strip()


def _title_from_citation(text: str) -> str | None:
    match = _SHORT_TITLE.search(text)
    return match.group(1).strip() if match else None


def _title_from_marker(text: str) -> str | None:
    """Take the LAST marker in the first 10 KB: a later one is a quoted reference."""
    last = None
    for match in _BILL_MARKER.finditer(text[:MARKER_WINDOW_CHARS]):
        last = match
    if last is None:
        return None
    after = text[last.end() :]
    stop = _MARKER_STOP.search(after[:MARKER_TAIL_CHARS])
    raw = after[: stop.start()] if stop else after[:MARKER_TAIL_CHARS]
    collapsed = _WHITESPACE.sub(" ", raw).strip()
    return collapsed if len(collapsed) >= 5 else None


def _title_from_position(text: str) -> str | None:
    collapsed = _WHITESPACE.sub(" ", text[POSITION_FALLBACK[0] : POSITION_FALLBACK[1]]).strip()
    return collapsed or None


@dataclass(frozen=True, slots=True)
class TitleTier:
    """``source`` is what ``title_source`` records when this tier supplies the title."""

    source: str
    extract: Callable[[str], str | None]


TITLE_TIERS: tuple[TitleTier, ...] = (
    TitleTier("may-be-cited-as", _title_from_citation),
    TitleTier("fallback-marker", _title_from_marker),
    TitleTier("fallback-position", _title_from_position),
)


@dataclass(frozen=True, slots=True)
class BillNumberPattern:
    """``window`` is how many leading characters the pattern is allowed to see."""

    name: str
    pattern: re.Pattern[str]
    window: int
    normalize_type: bool


BILL_NUMBER_PATTERNS: tuple[BillNumberPattern, ...] = (
    BillNumberPattern("prose", _PROSE_BILL_NUMBER, HEAD_CHARS, True),
    BillNumberPattern("gpo-bullet", _BULLET_BILL_NUMBER, HEAD_CHARS, False),
)


def extract_signals(text: str) -> ExtractedSignals:
    """Read the five signals out of one document's text."""
    head = text[:HEAD_CHARS]

    bill_type: str | None = None
    bill_number: str | None = None
    for candidate in BILL_NUMBER_PATTERNS:
        match = candidate.pattern.search(text[: candidate.window])
        if match:
            bill_type = normalize_bill_type(match.group(1)) if candidate.normalize_type else match.group(1).upper()
            bill_number = match.group(2)
            break

    congress_match = _CONGRESS.search(head)
    congress = int(congress_match.group(1)) if congress_match else None

    normalized_title: str | None = None
    title_source = "none"
    for tier in TITLE_TIERS:
        raw = tier.extract(text)
        if not raw:
            continue
        normalized = normalize_for_comparison(raw)
        if normalized:
            normalized_title = normalized
            title_source = tier.source
            break

    sponsor_match = _SPONSOR.search(text[:SPONSOR_HEAD_CHARS])
    sponsor_last_name = sponsor_match.group(1) + sponsor_match.group(2) if sponsor_match else None

    headings: list[str] = []
    for match in _SECTION_HEADING.finditer(text):
        if len(headings) >= MAX_SECTION_HEADINGS:
            break
        heading = normalize_for_comparison(_WHITESPACE.sub(" ", match.group(2)).strip())
        if heading:
            headings.append(heading)

    return ExtractedSignals(
        bill_type=bill_type,
        bill_number=bill_number,
        congress=congress,
        normalized_title=normalized_title,
        title_source=title_source,
        sponsor_last_name=sponsor_last_name,
        section_headings=tuple(headings),
    )


def sponsor_last_name_of(sponsor: str) -> str:
    """The first all-caps run in a stored sponsor string, which is how the catalog spells a surname.

    Sealed: this is one half of the sponsor score, so changing it moves stored
    confidences. ``member_matching.last_name_of`` is the other surname parser,
    reads the publisher's structured display name, and is free to improve.
    """
    for token in _SPONSOR_SPLIT.split(sponsor.upper()):
        if _DB_LAST_NAME.fullmatch(token):
            return token
    return ""


def _heading_overlap(signals: ExtractedSignals, candidate: CandidateBill) -> SignalScore | None:
    headings = tuple(
        normalized for heading in candidate.section_headings if (normalized := normalize_for_comparison(heading))
    )
    if not headings:
        return None
    matched = sum(
        any(token_jaccard(extracted, known) >= HEADING_OVERLAP_MIN_JACCARD for known in headings)
        for extracted in signals.section_headings
    )
    total = len(signals.section_headings)
    score = matched / total if total else 0.0
    return SignalScore("section_heading_overlap", W_SECTION_HEADINGS, score, matched=matched, total=total)


def _score(signals: ExtractedSignals, candidate: CandidateBill) -> tuple[float, list[SignalScore]]:
    scores: list[SignalScore] = []
    confidence = 0.0

    if signals.bill_type and signals.bill_number:
        hit = float(candidate.bill_type == signals.bill_type and candidate.number == signals.bill_number)
        scores.append(
            SignalScore("bill_number", W_BILL_NUMBER, hit, found=f"{signals.bill_type} {signals.bill_number}")
        )
        confidence += W_BILL_NUMBER * hit

    if signals.normalized_title:
        title = normalize_for_comparison(candidate.title)
        short_title = normalize_for_comparison(candidate.short_title) if candidate.short_title else ""
        score = max(
            token_jaccard(signals.normalized_title, title),
            token_jaccard(signals.normalized_title, short_title) if short_title else 0.0,
        )
        scores.append(SignalScore("title_similarity", W_TITLE, score))
        confidence += W_TITLE * score

    if signals.congress is not None:
        difference = abs(signals.congress - candidate.congress)
        score = 1.0 if difference == 0 else CONGRESS_OFF_BY_ONE_SCORE if difference == 1 else 0.0
        scores.append(SignalScore("congress", W_CONGRESS, score))
        confidence += W_CONGRESS * score

    if signals.sponsor_last_name and candidate.sponsor:
        known = sponsor_last_name_of(candidate.sponsor)
        score = float(bool(known) and known == signals.sponsor_last_name)
        scores.append(SignalScore("sponsor", W_SPONSOR, score, found=signals.sponsor_last_name))
        confidence += W_SPONSOR * score

    return confidence, scores


def identify_bill(signals: ExtractedSignals, candidates: Iterable[CandidateBill]) -> tuple[BillMatch, ...]:
    """Rank catalog candidates against extracted signals.

    Heading overlap is computed for at most ``MAX_HEADING_COMPARISONS``
    candidates, the ones leading after the cheap signals, which is the bound
    BillTrax spent as three database queries.
    """
    scored = [(candidate, *_score(signals, candidate)) for candidate in candidates]
    if not scored:
        return ()
    scored.sort(key=lambda entry: entry[1], reverse=True)

    if signals.section_headings:
        for index, (candidate, confidence, scores) in enumerate(scored[:MAX_HEADING_COMPARISONS]):
            overlap = _heading_overlap(signals, candidate)
            if overlap is None:
                continue
            scores.append(overlap)
            scored[index] = (candidate, confidence + W_SECTION_HEADINGS * overlap.score, scores)

    scored.sort(key=lambda entry: entry[1], reverse=True)
    return tuple(
        BillMatch(
            bill_id=candidate.bill_id,
            congress=candidate.congress,
            bill_type=candidate.bill_type,
            number=candidate.number,
            title=candidate.title,
            confidence=min(1.0, confidence),
            signals=tuple(scores),
        )
        for candidate, confidence, scores in scored[:MAX_CANDIDATES]
        if confidence >= MIN_CONFIDENCE
    )


def confidence_band(confidence: float) -> str:
    """``high``, ``medium`` or ``low`` against the sealed thresholds."""
    if confidence >= IDENTIFY_CONFIDENCE_THRESHOLDS["high"]:
        return "high"
    if confidence >= IDENTIFY_CONFIDENCE_THRESHOLDS["medium"]:
        return "medium"
    return "low"


__all__ = [
    "BILL_NUMBER_PATTERNS",
    "CONGRESS_OFF_BY_ONE_SCORE",
    "HEADING_OVERLAP_MIN_JACCARD",
    "HEAD_CHARS",
    "IDENTIFY_CONFIDENCE_THRESHOLDS",
    "MAX_CANDIDATES",
    "MAX_HEADING_COMPARISONS",
    "MAX_SECTION_HEADINGS",
    "MIN_CONFIDENCE",
    "SIGNAL_WEIGHTS",
    "SPONSOR_HEAD_CHARS",
    "TITLE_SOURCES",
    "TITLE_TIERS",
    "BillMatch",
    "BillNumberPattern",
    "CandidateBill",
    "ExtractedSignals",
    "SignalScore",
    "TitleTier",
    "confidence_band",
    "extract_signals",
    "identify_bill",
    "normalize_bill_type",
    "normalize_for_comparison",
    "sponsor_last_name_of",
    "token_jaccard",
]
