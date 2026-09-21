"""Classify a bill version's ``version_code`` slug into a document kind.

Ported from BillTrax ``src/lib/version-kind.ts`` and reading
``sources.congress.bill_versions.VERSION_CODES``, the sealed publisher-fact
vocabulary, this states the distinction the vocabulary does not: a slug like
``engrossed-amendment-senate`` names an edit-instruction document, not full
bill text, and diffing it against full text produces the "+0 added / -N
removed" trap. Measured against the 119th BILLS corpus, the original's slug
lists miss 5 of the 24 codes the publisher actually used, which is why the
size heuristics exist for slugs no classification list names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from spicy_docs.sources.congress.bill_versions import slugify

VersionKind = Literal["full_text", "procedural_amendments", "procedural_summary", "kind_uncertain", "unknown"]

#: Edit-instruction documents, not full bill text (`version-kind.ts:17-28`).
PROCEDURAL_AMENDMENTS_SLUGS: frozenset[str] = frozenset(
    {
        "engrossed-amendment-senate",
        "engrossed-amendment-house",
        "amendment-senate",
        "amendment-house",
        "amendment-engrossed-senate",
        "amendment-engrossed-house",
        "amendment-senate-house",
        "additional-sponsors-house",
        "failed-amendment-senate",
        "failed-amendment-house",
    }
)

#: Brief procedural documents, not full bill text (`version-kind.ts:31-36`).
PROCEDURAL_SUMMARY_SLUGS: frozenset[str] = frozenset(
    {
        "statement-of-substance",
        "held-at-desk-senate",
        "held-at-desk-house",
        "previously-passed-senate",
    }
)

#: Slugs whose documents carry complete bill text (`version-kind.ts:39-78`).
FULL_TEXT_SLUGS: frozenset[str] = frozenset(
    {
        "introduced-in-house",
        "introduced-in-senate",
        "engrossed-in-house",
        "engrossed-in-senate",
        "engrossed-in-house-substitute",
        "enrolled-bill",
        "public-law",
        # Committee referral / reporting versions (full text accompanies the action)
        "referred-in-house",
        "referred-in-senate",
        "referred-to-committee",
        "reported-in-house",
        "reported-to-senate",
        "reported-by-committee",
        # Calendar placement
        "placed-on-calendar-senate",
        "placed-on-calendar-house",
        # Passage variants
        "passed-as-proposed",
        "passed-as-voted",
        "considered-and-passed-house",
        "considered-and-passed-senate",
        # Committee discharge
        "committee-discharge-house",
        "committee-discharge-senate",
        # Failed -- full text but failed passage
        "failed-in-house",
        "failed-in-senate",
        # Reference / administrative
        "reference-change-senate",
        "reference-change-house",
        "returned-to-the-house-by-unanimous-consent",
        "returned-to-the-senate-by-unanimous-consent",
        # Other known full-text milestones
        "original-in-senate",
        "original-in-house",
        "agreed-to-senate",
        "agreed-to-house",
    }
)

VERSION_KIND_LABELS: dict[VersionKind, str] = {
    "full_text": "Full bill text",
    "procedural_amendments": "Amendment document — not full bill text",
    "procedural_summary": "Procedural summary — not full bill text",
    "kind_uncertain": "Full bill text (short — verify)",
    "unknown": "Unknown format",
}

#: Inline hint for a non-full-text kind, shown in a version picker.
VERSION_KIND_WARNINGS: dict[VersionKind, str] = {
    "procedural_amendments": "amendment instructions, not bill text",
    "procedural_summary": "procedural summary, not bill text",
    "kind_uncertain": "unusually short — may be incomplete",
}

#: Below this, a full_text-classified slug downgrades to kind_uncertain (either bound).
_MIN_SECTION_COUNT = 20
_MIN_BODY_BYTES = 10_000


@dataclass(frozen=True, slots=True)
class VersionKindFinding:
    """One classification, naming the rule that fired and the size evidence it was given.

    ``rule`` is one of ``procedural_amendments_slug``,
    ``procedural_summary_slug``, ``full_text_slug``, ``full_text_slug_thin``
    (downgraded to ``kind_uncertain`` by the size heuristic),
    ``amendment_substring`` (an unlisted slug this repo's own heuristic caught),
    ``size_heuristic`` or ``unknown``.
    """

    kind: VersionKind
    rule: str
    section_count: int | None
    body_bytes: int | None


def version_kind_finding(
    version_code: str | None,
    *,
    section_count: int | None = None,
    body_bytes: int | None = None,
) -> VersionKindFinding:
    """Classify one bill version by its ``version_code`` slug and, for a size
    heuristic, its extracted section count or body byte length, naming the
    rule that decided it.

    ``version_code`` is re-normalized through ``slugify`` defensively, matching
    the original -- a caller that passes the display name instead of the stored
    slug still classifies correctly.
    """
    slug = slugify(version_code) if version_code else ""

    def _finding(kind: VersionKind, rule: str) -> VersionKindFinding:
        return VersionKindFinding(kind, rule, section_count, body_bytes)

    if slug in PROCEDURAL_AMENDMENTS_SLUGS:
        return _finding("procedural_amendments", "procedural_amendments_slug")
    if slug in PROCEDURAL_SUMMARY_SLUGS:
        return _finding("procedural_summary", "procedural_summary_slug")

    if slug in FULL_TEXT_SLUGS:
        # A "full text" code with too few sections or too little body text is
        # flagged uncertain -- the version code is right but content is thin.
        too_few_sections = section_count is not None and section_count < _MIN_SECTION_COUNT
        too_short = body_bytes is not None and body_bytes < _MIN_BODY_BYTES
        if too_few_sections or too_short:
            return _finding("kind_uncertain", "full_text_slug_thin")
        return _finding("full_text", "full_text_slug")

    # An unlisted slug containing "amendment" is almost certainly procedural
    # (catches future variant names the vocabulary has not named yet).
    if "amendment" in slug:
        return _finding("procedural_amendments", "amendment_substring")

    # Unknown slug -- infer from size if available.
    if body_bytes is not None and body_bytes >= _MIN_BODY_BYTES:
        return _finding("full_text", "size_heuristic")
    return _finding("unknown", "unknown")


def version_kind(
    version_code: str | None,
    *,
    section_count: int | None = None,
    body_bytes: int | None = None,
) -> VersionKind:
    """The kind alone; see `version_kind_finding` for the rule that produced it."""
    return version_kind_finding(version_code, section_count=section_count, body_bytes=body_bytes).kind


__all__ = [
    "FULL_TEXT_SLUGS",
    "PROCEDURAL_AMENDMENTS_SLUGS",
    "PROCEDURAL_SUMMARY_SLUGS",
    "VERSION_KIND_LABELS",
    "VERSION_KIND_WARNINGS",
    "VersionKind",
    "VersionKindFinding",
    "version_kind",
    "version_kind_finding",
]
