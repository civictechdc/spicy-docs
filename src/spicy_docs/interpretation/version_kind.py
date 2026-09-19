"""Classify a bill version's `version_code` slug into a document kind.

Ported from BillTrax `src/lib/version-kind.ts` (read-only,
`/Users/mikewolfd/Work/spicy-stack/BillTrax`). The key distinction the
publisher's own version-code vocabulary does not state directly: a slug like
`engrossed-amendment-senate` names an edit-instruction document, not full
bill text, and diffing it against full text produces the "+0 added / -N
removed" trap `version-kind.ts`'s module comment names. This is judgment over
`sources.congress.bill_versions.VERSION_CODES`, the sealed publisher-fact
vocabulary -- it belongs in `interpretation`, not in the `sources` package,
per the split `docs/research/billtrax-value-inventory-2026-09-19.md` records.

Measured 2026-09-19 against the 119th BILLS corpus
(`docs/research/billtrax-raw-data-2026-09-19.md` §1): `version-kind.ts` misses
5 of the 24 codes the publisher actually used (`as`, `cdh`, `lth`, `rds`,
`ris` fall through to the size heuristic below); `cdh` misses only because
BillTrax spells its slug `committee-discharge-house` while the publisher's
own `type` string is "Committee Discharged House" (`version_slug` of that
name does not match). Ported as measured -- the fallback heuristics below
exist precisely for slugs a classification list does not name.
"""

from __future__ import annotations

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


def version_kind(
    version_code: str | None,
    *,
    section_count: int | None = None,
    body_bytes: int | None = None,
) -> VersionKind:
    """Classify one bill version by its `version_code` slug and, for a size
    heuristic, its extracted section count or body byte length.

    `version_code` is re-normalized through `slugify` defensively, matching
    `version-kind.ts:103` -- a caller that passes the display name instead of
    the stored slug still classifies correctly.
    """
    slug = slugify(version_code) if version_code else ""

    if slug in PROCEDURAL_AMENDMENTS_SLUGS:
        return "procedural_amendments"
    if slug in PROCEDURAL_SUMMARY_SLUGS:
        return "procedural_summary"

    if slug in FULL_TEXT_SLUGS:
        # A "full text" code with too few sections or too little body text is
        # flagged uncertain -- the version code is right but content is thin.
        too_few_sections = section_count is not None and section_count < _MIN_SECTION_COUNT
        too_short = body_bytes is not None and body_bytes < _MIN_BODY_BYTES
        if too_few_sections or too_short:
            return "kind_uncertain"
        return "full_text"

    # An unlisted slug containing "amendment" is almost certainly procedural
    # (catches future variant names the vocabulary has not named yet).
    if "amendment" in slug:
        return "procedural_amendments"

    # Unknown slug -- infer from size if available.
    if body_bytes is not None and body_bytes >= _MIN_BODY_BYTES:
        return "full_text"
    return "unknown"


__all__ = [
    "FULL_TEXT_SLUGS",
    "PROCEDURAL_AMENDMENTS_SLUGS",
    "PROCEDURAL_SUMMARY_SLUGS",
    "VERSION_KIND_LABELS",
    "VERSION_KIND_WARNINGS",
    "VersionKind",
    "version_kind",
]
