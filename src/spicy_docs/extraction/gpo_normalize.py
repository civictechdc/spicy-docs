"""Post-extraction normalization of GPO-formatted legislative PDF text.

Strips the self-evidencing print chrome -- the VerDate footer and its tail, the
job-code line, bulleted bill ids and unbulleted running bill-stage lines -- and
rejoins a hyphen-wrap only where a gutter number corroborates it as a print
artifact; normalization runs per page and never rejoins across a page break.
Bare page/gutter numbers are stripped only when that page carries GPO evidence
(its own footer or the document's gutter-number layout), never from the absence
of both, since outside a GPO document such a line could be a year or a footnote
number; the layout verdict is ``_layout_verdict``'s two-tier rule.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Named rules, one per GPO artifact. Simple, single-line rules are a table;
# the footer's multi-line continuation needs a short forward walk and is
# implemented in _strip_metadata below, next to the rule it extends.
# ---------------------------------------------------------------------------

_VERDATE_RE = re.compile(r"^VerDate\s")
# Re-derived (see module docstring, artifact 2): generalized from a literal
# "DSK" machine-id prefix and a literal trailing "$" to any machine id ending
# "PROD" and any trailing job-code token. Still matches BillTrax's original
# example ("kjohnson on DSK7ZCZBW3PROD with $_JOB").
_DSK_USER_RE = re.compile(r"^\w+ on \w*PROD\w* with \S+$")
_PAGE_NUM_RE = re.compile(r"^\d{1,4}\s*$")
_BULLET_BILL_RE = re.compile(r"^[•·]\s*[A-Z]")
# Ported verbatim from DeltaTrack's ``_RUNNING_FOOTER`` (civictechdc/DeltaTrack
# c636448, ``parsers/pdf_text.py:68-71``), built for its own #140: an
# unbulleted running bill-stage line (e.g. "HR 5895 PCS", for print stages GPO
# does not prefix with a bullet -- PCS/RDS/RFS unbulleted, EAH/RH/EH/RS/IH
# bulleted, all 2-4 caps, per that rule's own corpus-derived comment) that
# neither BillTrax's ``BULLET_BILL_RE`` nor this port's own ``_BULLET_BILL_RE``
# matches, since it carries no bullet character. Matched as a WHOLE line, like
# upstream, so prose mentioning a bill mid-sentence is never stripped.
_RUNNING_FOOTER_RE = re.compile(r"^(?:H|S|HR|HRES|SRES|HJRES|SJRES|HCONRES|SCONRES)\s+\d+\s+[A-Z]{2,4}$")

#: BillTrax's own bound: a GPO gutter number is 1-2 digits (its comment: "up
#: to 25 -- page line range"). A bare page-footer number can run to 4 digits
#: (``_PAGE_NUM_RE``); using the tighter bound here keeps the two apart.
_BARE_GUTTER_NUMBER_RE = re.compile(r"^\d{1,2}$")
_HYPHEN_WRAP_RE = re.compile(r"[A-Za-z]-$")
_SINGLE_CAP_RE = re.compile(r"^[A-Z]$")
_STARTS_CAP_RE = re.compile(r"^[A-Z]")
_SPACE_COLLAPSE_RE = re.compile(r"  +")
_CURLY_SINGLE_RE = re.compile(r"[\u2018\u2019]")
_CURLY_DOUBLE_RE = re.compile(r"[\u201c\u201d]")


@dataclass(frozen=True, slots=True)
class MetadataRule:
    """One named single-line detector and the GPO artifact it removes."""

    name: str
    artifact: str
    pattern: re.Pattern[str]


#: The single-line rules, in the order ``_strip_metadata`` checks them. The
#: footer's multi-line continuation is not a table entry: a VerDate match
#: truncates the rest of the page, so it lives in the walk, not a pattern.
METADATA_RULES: tuple[MetadataRule, ...] = (
    MetadataRule("verdate_footer", "GPO print metadata footer (VerDate line)", _VERDATE_RE),
    MetadataRule("dsk_user", "Document-processing user/job-code line", _DSK_USER_RE),
    MetadataRule("bare_page_number", "Bare page number or per-line gutter number", _PAGE_NUM_RE),
    MetadataRule("bullet_bill_id", "Bullet-prefixed bill identifier", _BULLET_BILL_RE),
    MetadataRule("running_footer", "Unbulleted running bill-stage line (e.g. HR 5895 PCS)", _RUNNING_FOOTER_RE),
)


# ---------------------------------------------------------------------------
# Per-page cleanup counts and the aggregate record.
# ---------------------------------------------------------------------------


#: Which GPO evidence, if any, gated this page's bare-digit-line stripping
#: (module docstring: "Bare-digit stripping is evidence-gated per page").
#: ``"none"`` means the lines were found but kept, for lack of evidence.
BareNumberEvidence = Literal["none", "page_footer", "gutter_layout", "both"]


@dataclass(frozen=True, slots=True)
class GpoPageCleanup:
    """Counts for one page. ``page`` is one-based, matching extraction output."""

    page: int
    verdate_footer_lines: int
    footer_continuation_lines: int
    dsk_user_lines: int
    running_footer_lines: int
    bare_page_number_lines: int
    bare_page_number_evidence: BareNumberEvidence
    bullet_bill_lines: int
    #: This page's own share of the ``line_numbers`` verdict's evidence: real
    #: prose lines, excluding every stripped-chrome and bare-digit line (see
    #: ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT``).
    content_lines: int
    small_caps_merges: int
    hyphen_rejoin_count: int


@dataclass(frozen=True, slots=True)
class GpoCleanupRecord:
    """The document-level cleanup counts plus a per-page breakdown.

    ``spacing_normalized`` is hardcoded ``True`` because the collapse rule always
    runs; it is kept for output parity, not because it carries information.
    """

    line_numbers: bool
    gpo_footers: bool
    spacing_normalized: bool
    running_footer_lines: int
    small_caps_merges: int
    hyphen_rejoin_count: int
    pages: tuple[GpoPageCleanup, ...]


@dataclass(frozen=True, slots=True)
class _Line:
    text: str
    #: True when the next physical line, before metadata stripping, was a
    #: bare 1-2 digit gutter number -- the corroborating signal for both
    #: ``is_gpo_layout`` and hyphen-rejoin eligibility (see module docstring,
    #: artifact 1).
    gutter_adjacent: bool
    #: True for a standalone 1-4 digit line. Provisionally kept, not yet
    #: dropped, by ``_strip_metadata``: whether it survives depends on
    #: page-level GPO evidence decided afterward (module docstring,
    #: "Bare-digit stripping is evidence-gated per page").
    is_bare_digit: bool = False


@dataclass(frozen=True, slots=True)
class _PageMetadataCounts:
    verdate_footer_lines: int
    footer_continuation_lines: int
    dsk_user_lines: int
    running_footer_lines: int
    bare_page_number_lines: int
    bullet_bill_lines: int
    content_lines: int
    gutter_adjacent_lines: int
    #: The gutter-adjacent digit *values* themselves, in page order -- e.g.
    #: ``(1, 2, 3, 4, 5, 6)`` for a page whose six content lines are each
    #: followed by their own line number. Used below
    #: ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` to test for a real GPO
    #: run rather than trusting the count alone (see
    #: ``_starts_consecutive_run_from_one``).
    gutter_numbers: tuple[int, ...]


def _strip_metadata(lines: Sequence[str]) -> tuple[list[_Line], _PageMetadataCounts]:
    """Drop the self-evidencing artifacts and the VerDate footer's tail.

    A bare page/gutter-number line is GPO-specific only in context, not by its own
    text ("2024" is indistinguishable from a stripped gutter number), so it is kept
    and tagged ``is_bare_digit`` for ``_gate_bare_digits`` to strip or keep once
    page-level evidence is known. Returns the surviving lines (blanks kept) tagged
    with gutter adjacency plus the counts of what was dropped or tagged.
    """
    kept: list[_Line] = []
    verdate = footer_continuation = dsk = running_footer = page_num = bullet = 0
    content = gutter_adjacent = 0
    gutter_numbers: list[int] = []
    i, n = 0, len(lines)
    while i < n:
        t = lines[i].strip()
        if not t:
            kept.append(_Line("", False))
            i += 1
            continue
        if _VERDATE_RE.match(t):
            # Nothing meaningful follows a VerDate line on its page (see
            # module docstring, artifact 2): drop it and the rest of the
            # page in one step, tallying what kind of line each was.
            # Proven on the four fixtures in tests/fixtures/gpo_pdf_text/
            # only; a page where real content genuinely follows a VerDate
            # line would lose that content here, silently.
            verdate += 1
            tail = [line.strip() for line in lines[i + 1 :]]
            dsk_in_tail = sum(1 for line in tail if _DSK_USER_RE.match(line))
            dsk += dsk_in_tail
            footer_continuation += len(tail) - dsk_in_tail
            i = n
            continue
        if _DSK_USER_RE.match(t):
            dsk += 1
            i += 1
            continue
        following = lines[i + 1].strip() if i + 1 < n else ""
        gutter_follows = bool(_BARE_GUTTER_NUMBER_RE.match(following))
        # A line shaped like a running footer ("HR 5895 PCS") but followed by
        # its own gutter number is real gutter-numbered content that happens
        # to share the chrome's shape, not chrome -- a genuine running footer
        # is page furniture, never itself part of the numbered line count
        # (reproduced: BILLS-119hr1009rfs's actual running footer is followed
        # by prose and still strips; a numbered content line shaped like one
        # must not be deleted along with its digit).
        if _RUNNING_FOOTER_RE.match(t) and not gutter_follows:
            running_footer += 1
            i += 1
            continue
        if _PAGE_NUM_RE.match(t):
            page_num += 1
            kept.append(_Line(t, False, is_bare_digit=True))
            i += 1
            continue
        if _BULLET_BILL_RE.match(t):
            bullet += 1
            i += 1
            continue
        content += 1
        if gutter_follows:
            gutter_adjacent += 1
            gutter_numbers.append(int(following))
        kept.append(_Line(t, gutter_follows))
        i += 1
    counts = _PageMetadataCounts(
        verdate,
        footer_continuation,
        dsk,
        running_footer,
        page_num,
        bullet,
        content,
        gutter_adjacent,
        tuple(gutter_numbers),
    )
    return kept, counts


def _gate_bare_digits(
    kept: list[_Line], *, page_has_footer: bool, document_gpo_layout: bool
) -> tuple[list[_Line], BareNumberEvidence]:
    """Strip tagged bare-digit lines only where this page has GPO evidence.

    Either source suffices alone: this page's own VerDate footer, or the
    document-level gutter-number layout (a page with its own footer still strips
    its page-number header even when ``line_numbers`` is ``False`` document-wide).
    """
    if page_has_footer and document_gpo_layout:
        evidence: BareNumberEvidence = "both"
    elif page_has_footer:
        evidence = "page_footer"
    elif document_gpo_layout:
        evidence = "gutter_layout"
    else:
        evidence = "none"
    if evidence == "none":
        return kept, evidence
    return [line for line in kept if not line.is_bare_digit], evidence


#: Ported from DeltaTrack's ``_MIN_LINES_FOR_GUARD`` (civictechdc/DeltaTrack
#: c636448, ``compare/pdf.py:85``). Its own floor-selection table
#: (``compare/pdf.py:62-78``), swept over 60 real GPO PDFs, found a hard cliff
#: between 28 and 29 judged lines (minimum accepted ratio 0.4286 -> 0.5517)
#: and picked 50 for a comfortable margin past it while declining the same 14
#: documents 29 would. At or above this floor, a ratio of at least 30%
#: numbered decides the verdict True by itself, as upstream's own guard does
#: -- *or* a per-page consecutive run (see ``_starts_consecutive_run_from_one``,
#: at least ``_MIN_GUTTER_RUN_LENGTH`` long) decides it True independently,
#: since GPO's own gutter numbering restarts at 1 on every page and steps by
#: one per typeset line, which a footnote marker or outline number need not
#: do, and a real run spanning many lines across several pages is strong
#: evidence on its own once the document is this big. Below the floor, both
#: signals are required together, unchanged from the original design: a
#: two-page memo should not be declared GPO-numbered on three lines just
#: because they happen to be numbered, and the floor's own minimum run length
#: (3, "the smallest run that cannot also be a single coincidental pair") is
#: comparatively weak evidence for a document this small without the ratio
#: also backing it. A first version of this floor gated the run test behind
#: the floor (below only) and behind a strict ``> 0.3`` ratio everywhere; a
#: 42-document corpus validation (``docs/extraction-gpo.md``, "Corpus
#: validation") found real GovInfo documents on both sides of that mistake --
#: see ``_layout_verdict``'s docstring. Residual false positive: at or above
#: the floor, a numbered outline whose own numbers sit on their own lines and
#: happen to restart at 1 on every page would pass the run test too, now
#: without a ratio to also require -- whether a real document of that shape
#: exists is still unmeasured on this corpus (none of its 42 documents
#: exercises the case). What such a verdict's *blast radius* would do to the
#: rest of the document, once decided, is now pinned by
#: ``test_gpo_normalize.py``'s
#: ``test_true_at_or_above_the_floor_across_pages_and_the_rejoin_blast_radius_on_an_unrelated_page``:
#: a document-wide True from a minimal per-page run reaches every page for
#: bare-digit stripping regardless of that page's own evidence, but not for
#: hyphen-rejoin, which still requires the specific line to carry its own
#: corroborating gutter number -- an unrelated page's hyphen-wrap is left
#: unrejoined even beside a gutter-adjacent line and a document verdict of
#: True.
_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT = 50

#: How many consecutive gutter numbers, starting at 1, one page must carry
#: before its digits count as structural GPO evidence below the floor above.
#: 3 is the smallest run that cannot also be a single coincidental pair (see
#: ``_starts_consecutive_run_from_one``).
_MIN_GUTTER_RUN_LENGTH = 3


def _starts_consecutive_run_from_one(numbers: Sequence[int], minimum: int = _MIN_GUTTER_RUN_LENGTH) -> bool:
    """True when ``numbers`` begins at 1 and increments by one for at least ``minimum`` entries.

    Only the prefix run counts: ``(1, 2, 4)`` stops at length 2 and ``(3, 4, 5)``
    never starts, since a run not beginning at 1 is what a footnote or outline
    sequence continuing from a prior page looks like -- GPO's per-page gutter
    numbering always restarts at 1.
    """
    run = 0
    for index, value in enumerate(numbers):
        if value != index + 1:
            break
        run += 1
    return run >= minimum


def _layout_verdict(page_counts: Sequence[_PageMetadataCounts]) -> bool:
    """The document-wide line-numbering verdict, shared by ``is_gpo_layout`` and ``normalize_gpo_pages``.

    Two-tier rule: at or above ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` content
    lines, a numbered ratio of at least 30% decides True by itself, or a per-page
    run from 1 decides True independently; below the floor both signals must hold
    together, because a short document's 3-line minimum run is weak evidence alone.
    """
    content = sum(c.content_lines for c in page_counts)
    if content == 0:
        return False
    numbered = sum(c.gutter_adjacent_lines for c in page_counts)
    ratio_qualifies = numbered / content >= 0.3
    has_structural_run = any(_starts_consecutive_run_from_one(c.gutter_numbers) for c in page_counts)
    if content >= _MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT:
        return ratio_qualifies or has_structural_run
    return ratio_qualifies and has_structural_run


def is_gpo_layout(pages: Sequence[str]) -> bool:
    """Detect GPO per-line gutter numbering (BillTrax's ``detectLineNumbered``).

    A content line is numbered when the next physical line is a bare 1-2 digit
    gutter number (this extractor never glues the number onto the content line).
    The verdict is ``_layout_verdict``'s two-tier rule.
    """
    return _layout_verdict([_strip_metadata(normalize_gpo_glyphs(page).split("\n"))[1] for page in pages])


def _merge_small_caps(lines: list[_Line]) -> tuple[list[_Line], int]:
    """Merge a lone uppercase letter into a following uppercase-led line, returning the merge count."""
    merged: list[_Line] = []
    count = 0
    i, n = 0, len(lines)
    while i < n:
        cur = lines[i]
        if _SINGLE_CAP_RE.match(cur.text) and i + 1 < n and _STARTS_CAP_RE.match(lines[i + 1].text):
            nxt = lines[i + 1]
            merged.append(_Line(cur.text + nxt.text, nxt.gutter_adjacent))
            count += 1
            i += 2
            continue
        merged.append(cur)
        i += 1
    return merged, count


def _rejoin_hyphens(lines: list[_Line], gpo_layout: bool) -> tuple[list[str], int]:
    """Rejoin a gutter-corroborated hyphen-wrap with the line that follows it.

    Only runs when ``gpo_layout`` is True: without a document confirmed to number
    its lines, a trailing hyphen is not trusted as a print-wrap artifact, since it
    could be a real compound word ending a line by coincidence.
    """
    if not gpo_layout:
        return [line.text for line in lines], 0
    working = list(lines)
    count = 0
    for j in range(len(working) - 1):
        cur = working[j]
        if cur.gutter_adjacent and _HYPHEN_WRAP_RE.search(cur.text):
            nxt = working[j + 1]
            working[j + 1] = _Line(cur.text[:-1] + nxt.text, nxt.gutter_adjacent)
            working[j] = _Line("\x00", False)
            count += 1
    return [line.text for line in working if line.text != "\x00"], count


def normalize_gpo_glyphs(raw: str) -> str:
    """Line endings and GPO's quote conventions, shared by every rendition.

    Public and extractor-agnostic because GPO spells the same document the same way
    in every rendition but one glyph set apart: PDF text carries curly quotes and
    no backtick, while the ``htm`` rendition of the same report carries typewriter
    pairs (two backticks opening, two apostrophes closing). Both spellings are
    handled here so the renditions agree; ``extraction.body_text`` is the other caller.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _CURLY_SINGLE_RE.sub("'", text)
    text = _CURLY_DOUBLE_RE.sub('"', text)
    text = text.replace("\u00a0", " ")
    # GPO renders a real double quote as two adjacent single curly quotes
    # ("\u2018\u2018...\u2019\u2019", seen in CRPT-119hrpt105) in its PDF, and
    # as a backtick/apostrophe typewriter pair in its htm; after the
    # replacements above the first is two straight single quotes, not one
    # double quote. Collapse both -- the apostrophe half independently confirmed
    # against DeltaTrack's own extractor-agnostic ``normalize_glyphs``
    # (parsers/pdf_text.py:179, doubled-quote collapse at line 192:
    # ``text.replace("''", '"')``), not adopting its em/en-dash rewrite
    # alongside it, since no fixture here measures one. The backtick half is
    # a no-op on every PDF-derived fixture here (zero backticks in all six),
    # so adding it changes no measured PDF count.
    return text.replace("``", '"').replace("''", '"')


def normalize_gpo_pages(pages: Sequence[str]) -> tuple[tuple[str, ...], GpoCleanupRecord]:
    """Normalize GPO PDF page text, keeping page boundaries.

    ``pages`` is one string per page in reading order, the shape
    ``PageResult.text`` produces per page from ``DocumentExtractor``; each page is
    normalized independently and nothing is rejoined across a page break. A
    nonempty sequence is required.
    """
    if not pages:
        raise ValueError("pages must be a nonempty sequence")
    per_page = [_strip_metadata(normalize_gpo_glyphs(raw_page).split("\n")) for raw_page in pages]
    gpo_layout = _layout_verdict([counts for _, counts in per_page])
    normalized: list[str] = []
    page_records: list[GpoPageCleanup] = []
    gpo_footers = False
    total_small_caps = total_hyphen = total_running_footer = 0

    for number, (kept, counts) in enumerate(per_page, start=1):
        # A running bill-stage line (e.g. "HR 5895 PCS") is as self-evidencing
        # as the VerDate/job-code footer it usually accompanies (see module
        # docstring on ``_RUNNING_FOOTER_RE``), so it counts toward the same
        # page-level GPO evidence that gates bare-digit stripping.
        page_has_footer = (
            counts.verdate_footer_lines > 0 or counts.dsk_user_lines > 0 or counts.running_footer_lines > 0
        )
        gated, evidence = _gate_bare_digits(kept, page_has_footer=page_has_footer, document_gpo_layout=gpo_layout)
        merged, small_caps = _merge_small_caps(gated)
        rejoined, hyphen_count = _rejoin_hyphens(merged, gpo_layout)
        collapsed = [_SPACE_COLLAPSE_RE.sub(" ", line) for line in rejoined]
        normalized.append("\n".join(collapsed))

        gpo_footers = gpo_footers or page_has_footer
        total_small_caps += small_caps
        total_hyphen += hyphen_count
        total_running_footer += counts.running_footer_lines
        page_records.append(
            GpoPageCleanup(
                page=number,
                verdate_footer_lines=counts.verdate_footer_lines,
                footer_continuation_lines=counts.footer_continuation_lines,
                dsk_user_lines=counts.dsk_user_lines,
                running_footer_lines=counts.running_footer_lines,
                bare_page_number_lines=counts.bare_page_number_lines,
                bare_page_number_evidence=evidence,
                bullet_bill_lines=counts.bullet_bill_lines,
                content_lines=counts.content_lines,
                small_caps_merges=small_caps,
                hyphen_rejoin_count=hyphen_count,
            )
        )

    record = GpoCleanupRecord(
        line_numbers=gpo_layout,
        gpo_footers=gpo_footers,
        spacing_normalized=True,
        running_footer_lines=total_running_footer,
        small_caps_merges=total_small_caps,
        hyphen_rejoin_count=total_hyphen,
        pages=tuple(page_records),
    )
    return tuple(normalized), record


__all__ = [
    "METADATA_RULES",
    "BareNumberEvidence",
    "GpoCleanupRecord",
    "GpoPageCleanup",
    "MetadataRule",
    "is_gpo_layout",
    "normalize_gpo_glyphs",
    "normalize_gpo_pages",
]
