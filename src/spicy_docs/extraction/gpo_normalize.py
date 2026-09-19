"""Post-extraction normalization of GPO-formatted legislative PDF text.

Ported from BillTrax's ``pdf-normalize.ts``, and re-derived against this
repo's own PDF extraction rather than pdf-parse: the default native-text
strategy (``extraction.NativeText`` over ``extraction.DocumentExtractor``,
see ``extraction/pages.py::_PDFPage.native``) reads PyMuPDF's line-grouped
``get_text("dict")`` spans, one physical line of output per PDF text line.

That line layout is not pdf-parse's, and two of BillTrax's seven artifacts
are re-derived here because of it, each measured against real GovInfo PDFs
decoded with this extractor (see ``docs/extraction-gpo.md``):

1. **Line-number placement.** pdf-parse glued a GPO gutter line number onto
   the end of its content line ("Representa-1"). PyMuPDF emits the gutter
   number as its own physical line, immediately after the content line it
   annotates. ``detectLineNumbered``'s trailing-suffix regex never matches
   under this extractor -- the suffix does not exist -- so line-numbering is
   detected instead from that adjacency: a content line immediately followed
   by a bare one- or two-digit line. The same adjacency also replaces the
   trailing-digit match that used to gate which lines are hyphen-rejoin
   candidates, keeping BillTrax's original scope (rejoin only where a gutter
   number corroborates that a trailing hyphen is a print-wrap artifact, not
   a coincidence or a real compound word) on the new signal.
2. **Footer shape.** pdf-parse fused GPO's whole per-page print-shop footer
   ("VerDate ... Jkt ... PO ... Frm ... Fmt ... Sfmt ... E:\\...") onto one
   line; only its first token needed matching. PyMuPDF splits it across
   several physical lines instead, and nothing meaningful follows it: on
   every fixture measured (``docs/extraction-gpo.md``), a VerDate line is
   always the tail of its page's text. So the footer is dropped by
   truncating the page at that line -- checked against DeltaTrack
   (civictechdc/DeltaTrack, commit c636448)'s own PyPDFium2-derived
   normalizer, which reached the same conclusion independently
   (``parsers/pdf_text.py:72``, ``_VERDATE_AND_BELOW``, a DOTALL "to end of
   text" cut) -- rather than by enumerating each field (time+date, Jkt, PO, Frm,
   Fmt, Sfmt, file path, file stem): a field GPO adds later needs no new
   rule. BillTrax's job-code line ("kjohnson on DSK7ZCZBW3PROD with $_JOB")
   no longer matches real 2025 output either -- current jackets use a
   machine id that need not start "DSK" and a trailing job code with no
   leading "$" (observed: "ssavage on LAPJG3WLY3PROD with BILLS",
   "abielarski on DSK125SN23PROD with HEARING"; the first has no "DSK"
   substring at all, so DeltaTrack's own ``_WATERMARK_AND_BELOW``, which
   still requires one, would miss it too -- worth raising upstream). Both
   are re-derived below; see ``docs/extraction-gpo.md`` for the measured
   line counts this fixed.

The other five artifacts -- metadata footers named by their first line, bare
page numbers, bullet bill identifiers, small-caps single-letter splits, and
doubled internal spaces from kerning -- are kept verbatim. Doubled spaces and
non-breaking spaces were measured at zero occurrences across every fixture
here (PyMuPDF's span reconstruction does not reproduce pdf-parse's kerning
artifact); the rules stay for compatibility and are marked unmeasured rather
than removed, per the same "keep spacingNormalized" precedent BillTrax set
for its own always-true field.

**Bare-digit stripping is evidence-gated per page, not by one document-level
flag.** Docs recommend running this normalizer on every PDF-derived text
before a downstream parser, including non-GPO documents. A VerDate line and
a job-code line are self-evidencing -- the match itself is GPO-specific, so
both are always dropped. A standalone 1-4 digit line is not: outside a GPO
document it could be a year or a footnote number, and stripping it
unconditionally (as BillTrax's ``PAGE_NUM_RE`` does, and this port did before
this was measured) would silently lose real content on a non-GPO page. It is
now stripped only when *this page* carries GPO evidence: its own VerDate
footer, or the document-level gutter-number layout (``is_gpo_layout``) --
never from the absence of both. A committee report page can have
``line_numbers=False`` at the document level yet still legitimately strip its
page-number header, because its own page carries a VerDate footer; that is
why the gate checks both, not the layout verdict alone. See
``GpoPageCleanup.bare_page_number_evidence``.

Normalization runs per page and keeps page boundaries: a hyphen-wrapped word
split across a page break is not rejoined, since doing so would move
characters onto the wrong page's text.

**Two rules ported from DeltaTrack, not from BillTrax.** Validated upstream
gap-analysis (``docs/research/deltatrack-upstream-issues-2026-09-19.md``,
claims B2/B3) found these are upstream features this port lacked, not
upstream gaps -- so they are ported here rather than raised there:

3. **The unbulleted running bill-stage footer.** ``_RUNNING_FOOTER_RE``,
   ported verbatim from DeltaTrack's ``_RUNNING_FOOTER``
   (``parsers/pdf_text.py:68-71``, built for its own #140), strips a line
   like "HR 5895 PCS" -- a print-stage tag GPO does not bullet, so neither
   BillTrax's original rule nor this port's ``_BULLET_BILL_RE`` catches it.
   None of this port's first three fixtures carried one; the fourth,
   ``BILLS-119hr1009rfs`` (an RFS-stage bill, fetched keyless through
   ``sources.govinfo.bodies.package_body_locator``), does. Matched as a whole
   line, like upstream, but only when the *next* physical line is not itself
   a bare gutter number: a genuine running footer is page furniture followed
   by prose, but a real numbered content line can coincidentally share its
   shape, and deleting that line would delete a real gutter number with it
   (reproduced during review; see ``_strip_metadata``).
4. **The layout verdict's minimum-size floor.** Ported from DeltaTrack's own
   derivation (``compare/pdf.py:85``, table at ``:62-78``), but not its
   constant alone: upstream derived 50 for a document-wide ratio guard, while
   this port's own signal is also structural per page. At or above the
   floor, a document-wide ratio of at least 30% numbered decides True by
   itself, *or* a per-page consecutive run of gutter digits starting at 1
   decides True independently; below the floor both must hold together (see
   ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` and
   ``_starts_consecutive_run_from_one``). Both real one-page/two-page
   fixtures here (``BILLS-119hr4727ih``, ``BILLS-119hr1009rfs``) sit under the
   50-line floor and are genuinely gutter-numbered with both a qualifying
   ratio and a real run on at least one page, so both correctly report
   ``line_numbers=True`` and rejoin their real hyphen-wraps. A 42-document
   corpus validation (``docs/extraction-gpo.md``, "Corpus validation") found
   the run test originally could not fire above the floor at all, and the
   ratio's strict ``>`` missed two real documents landing at exactly 30% --
   both fixed; see ``_layout_verdict``'s own docstring for the documents that
   caught each one.
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
    """Every field BillTrax's ``PdfCleanupRecord`` had, plus a per-page breakdown.

    ``spacing_normalized`` is hardcoded ``True`` for the same reason
    BillTrax's was: the collapse rule always runs. It is kept, not because it
    still carries information (doubled spaces measured at zero occurrences
    under this extractor, across every fixture -- see module docstring), but
    for parity with the field BillTrax's own docstring already declared
    uninformative and kept anyway.
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

    A bare page/gutter-number line is not dropped here: it is GPO-specific
    only in context, not by its own text ("2024" is indistinguishable from a
    stripped gutter number), so it is kept in the returned lines, tagged
    ``is_bare_digit``, for the caller to strip or keep once page-level GPO
    evidence is known (see ``_gate_bare_digits`` and the module docstring).
    Everything else self-evidences (VerDate, the job-code line, the bullet
    bill id) and is dropped unconditionally, as BillTrax's was.

    Returns the surviving lines (blanks kept) tagged with gutter adjacency,
    and the counts of what was dropped or tagged, plus what is left to
    detect layout and hyphen-wraps from.
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

    Two independent sources of evidence, either sufficient on its own: this
    page's own VerDate footer, or the document-level gutter-number layout
    (a committee report page can have neither/either -- ``line_numbers`` is
    ``False`` for the whole document, but a page with its own footer still
    strips its page-number header; see the module docstring).
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
#: without a ratio to also require -- unmeasured on this corpus (none of its
#: documents exercises the case), tracked here rather than assumed safe.
_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT = 50

#: How many consecutive gutter numbers, starting at 1, one page must carry
#: before its digits count as structural GPO evidence below the floor above.
#: 3 is the smallest run that cannot also be a single coincidental pair (see
#: ``_starts_consecutive_run_from_one``).
_MIN_GUTTER_RUN_LENGTH = 3


def _starts_consecutive_run_from_one(numbers: Sequence[int], minimum: int = _MIN_GUTTER_RUN_LENGTH) -> bool:
    """True when ``numbers`` (in the order they appear on the page) begins at
    1 and increments by exactly one for at least ``minimum`` entries.

    Only the *prefix* run counts: ``(1, 2, 4)`` stops at length 2 (fails a
    minimum of 3), and ``(3, 4, 5)`` never starts, so it is length 0 --
    consecutive digits that do not begin at 1 are exactly what a footnote or
    outline sequence continuing from a prior page looks like, which GPO's own
    per-page gutter numbering never does.
    """
    run = 0
    for index, value in enumerate(numbers):
        if value != index + 1:
            break
        run += 1
    return run >= minimum


def _layout_verdict(page_counts: Sequence[_PageMetadataCounts]) -> bool:
    """Shared by ``is_gpo_layout`` and ``normalize_gpo_pages`` so a document's
    layout is one ``_strip_metadata`` pass per page, not two.

    See ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` for the two-tier rule this
    implements: at or above the floor, a document-wide ratio of at least 30%
    numbered decides True by itself, *or* a per-page structural run decides
    True independently -- a run spans real evidence (GPO's numbering
    restarting at 1 every page) that does not need a document-wide ratio to
    back it up once the document is big enough for the floor to apply at
    all. Below the floor, both signals are still required together, as
    before: a short document's minimum run (``_MIN_GUTTER_RUN_LENGTH``, 3)
    is comparatively weak evidence on its own, and BillTrax's original
    "a two-page memo should not be declared GPO-numbered on three lines just
    because they happen to be numbered" concern is about exactly that case,
    not the one below.

    **Two false negatives found validating this against a 42-document
    corpus** (``docs/extraction-gpo.md``, "Corpus validation"), both fixed
    here:

    1. A strict ``> 0.3`` made two real GPO-numbered documents fail on an
       exact 30% ratio: ``BILLS-119sjres141is`` (9 of 30 content lines
       numbered, both of its two pages independently showing a perfect
       consecutive run from 1 -- 6 long and 3 long) and
       ``BILLS-119hconres11eh`` (6 of 20, one page's run 4 long). Both are
       below the floor and both signals already agreed (ratio exactly at the
       line, run confirmed); only the strict inequality was wrong. Changed
       to ``>= 0.3``.
    2. The per-page run test only ever ran *below* the floor. A document at
       or above the floor whose numbered pages are diluted by a long
       unnumbered run -- ``BILLS-119hconres26ih``, a 10-page,
       261-content-line House concurrent resolution whose first six pages
       are entirely unnumbered "Whereas" recitals (a print convention this
       resolution type uses; a plain bill's enacting clause carries no
       comparable preamble) before its "Resolved" operative text begins --
       fails the whole-document ratio (0.268, genuinely under 30%, not a
       boundary tie) despite four pages (70 of the 261 content lines) each
       showing an unambiguous consecutive run from 1, one of them 25 long.
       Unlike case 1, raising the ratio's own ceiling would not have fixed
       this; the run test itself needed to reach documents at or above the
       floor, as an alternative to the ratio rather than a corroboration of
       it -- justified by scale, not just by evidence type: 70 lines across
       four pages is far past the 3-line minimum the floor's below-line
       guard exists to distrust.
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

    Re-derived signal (see module docstring, artifact 1): a content line is
    "numbered" when the next physical line, before stripping, is a bare 1-2
    digit gutter number -- not, as under pdf-parse, when the content line's
    own text ends in a trailing digit suffix, which this extractor never
    produces. At ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` content lines or
    more, a document-wide ratio of at least 30% numbered decides the verdict
    True by itself, or a page's gutter digits forming a consecutive run
    starting at 1 decides it True independently; below that floor both
    signals are required together (see ``_layout_verdict`` and
    ``_starts_consecutive_run_from_one``).
    """
    return _layout_verdict([_strip_metadata(normalize_gpo_glyphs(page).split("\n"))[1] for page in pages])


def _merge_small_caps(lines: list[_Line]) -> tuple[list[_Line], int]:
    """Merge a lone uppercase letter into a following uppercase-led line."""
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

    Only runs when ``gpo_layout`` is True, preserving BillTrax's original
    scope: without a document confirmed to number its lines, a trailing
    hyphen is not trusted as a print-wrap artifact (it could be a real
    hyphenated compound word ending a line by coincidence).
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

    Public and extractor-agnostic because GPO spells the same document the
    same way in every rendition but one glyph set apart, and a caller that
    normalizes only one of them makes two texts of one document. Measured
    2026-09-19 across six PDF-derived fixtures and four keyless ``htm``
    bodies: the PDF text carries curly quotes (8, 99 and 242 on
    CRPT-119hrpt105, -113hrpt135 and -113srpt77) and no backtick at all,
    while the ``htm`` rendition of those same reports carries no curly quote
    and 2, 54 and 119 typewriter pairs (two backticks opening, two
    apostrophes closing). Both spellings are handled here, so the two
    renditions agree afterwards; ``extraction.body_text`` is the other
    caller.
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

    ``pages`` is one string per page in reading order -- the shape
    ``PageResult.text`` produces per page from ``DocumentExtractor``. Each
    page is normalized independently; nothing is rejoined across a page
    break (see module docstring).
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
