"""Committee reports, the agency blocks inside them, and hearing transcripts.

All three are keyed on the GovInfo package id, not on a bill (C11).  A
package-keyed report is fillable today by ``GovInfoBodyAcquirer``; the bill
linkage is not, so ``bill_id`` is nullable and a row exists without it rather
than the table waiting on a join nothing can make yet.  That is the correction
the placement study asked for on ``hearing_transcripts``, whose defect was a
contract nothing filled.

**``hearing_transcripts.bill_id`` is NULL for a different reason than
``committee_reports.bill_id`` is**, and the reason changed on 2026-09-20.  It
was "no source states it"; four publishers do state it
([the measurement](../../../docs/research/hearing-bill-linkage-2026-09-20.md)).
It is now "a scalar column is the wrong shape": a legislative hearing is held
on a *list* -- twelve bills on ``CHRG-118hhrg56198`` -- so the relationship is
one-to-many and ``hearing_bill_links`` hosts it, one row per (hearing, bill,
source).  A report is filed against one bill and keeps its scalar.

``report_sections.pattern`` is this table's provenance column: it names the
header pattern that fired to produce the block, so a mis-split report is
readable from the row rather than only from re-running the parser.

**The CBO estimate columns are the report-to-estimate link** (B4).  A
committee report reprints the CBO cost-estimate letter verbatim when its cover
declares it, which is the only text route to an estimate CBO's own site
refuses.  Those columns are appended *here*, on the package-keyed row, rather
than on ``cbo_cost_estimates``, and no ``document_citations`` row is written.
Both choices are measured, not aesthetic (``docs/decisions.md``):

* **The print names no estimate key.**  Across all 17 retained CRPT bodies
  there is exactly **one** ``cbo.gov`` locator -- a footnote to an unrelated
  2018 CBO study -- **no** ``/publication/{id}`` page, and no locator inside
  any located letter.  A citation row would therefore have to carry a
  ``target_key`` nothing in the document settles, in a table whose grain is
  one occurrence *of a cited key*.  The letter is also one span per document,
  not one occurrence per key.
* **The estimate row cannot know which letter is its own.**  It is shaped from
  one BILLSTATUS document in one pass and the report is a different package;
  61 of the 1,368 scored bills of the 118th carry more than one estimate and
  28 of those also carry a report, so attributing one reprinted letter to one
  of several estimates would be a guess on 28 bills.

So the relation is a join on the bill, which both sides state:
``cbo_cost_estimates.bill_id`` against this table's ``recital_bill_id`` -- the
*print's own* answer, read off the cover's ``[To accompany H.R. 801]`` -- with
``bill_id`` left as whatever index record the caller read.  Two columns for
one fact on purpose: what the print says and what an index says are different
claims, and the two agreeing is the check.

The same letter rule supports normalized HTM and PDF text. All four retained
PDFs (CRPT-118hrpt53, -118hrpt276, -118hrpt930, -118srpt289) now yield pinned
spans despite lost indentation; the 17 retained HTM findings are unchanged
apart from the version. The caller chooses the rendition; PDF is preferred
as the research plan recommends. ``format`` and ``text_sha256`` identify the
text the offsets address. No raster cost figures are extracted.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import Row, flag, table_contract, text

#: Which chamber each GovInfo document-type code belongs to.  CRPT's ``erpt``
#: is a Senate executive report, not a House one; naming the six codes as data
#: keeps that from being re-derived from a first letter.
CHAMBER_BY_DOCUMENT_TYPE: dict[str, str] = {
    "hrpt": "house",
    "srpt": "senate",
    "erpt": "senate",
    "hhrg": "house",
    "shrg": "senate",
    "jhrg": "joint",
}


def _package_columns(
    *,
    type_column: str,
    type_description: str,
    number_column: str,
    number_description: str,
) -> dict[str, str]:
    """The columns a captured GovInfo package states, in publish order.

    A committee report and a hearing transcript differ in exactly two column
    names -- what the document-type code and the number are called -- so the
    prose for the other seventeen is written once here, in the same order
    :func:`_package_row` fills them.
    """
    return {
        "package_id": "The GovInfo package id, which is this row's identity.",
        "collection": "The GovInfo collection the package belongs to (CRPT, CHRG).",
        "congress": "The numbered Congress, parsed from the package id's own grammar.",
        type_column: type_description,
        number_column: number_description,
        "chamber": "The chamber, from the package id's document-type code rather than from its first letter.",
        "title": "The package title as the keyed summary states it.",
        "date_issued": "The date the package was issued.",
        "last_modified": "When the publisher last modified the package; the merge prefers the larger value.",
        "bill_id": "The bill this package concerns, where a linkage exists; nullable by design (C11).",
        "format": "Which rendition was read (htm, xml, txt, pdf).",
        "media_type": "The response media type, proved against the format before the body was accepted.",
        "requested_url": "The URL the body fetch asked for.",
        "resolved_url": "The URL the body actually came from.",
        "byte_size": "Length in bytes of the captured body.",
        "sha256": "Digest of the captured body bytes.",
        "observed_at": "When the body was captured.",
        "page_count": "How many pages the extraction read, where a page-based extractor ran.",
        "text_sha256": "Digest of the extracted text, so a re-extraction that changed nothing is visible as such.",
    }


COMMITTEE_REPORTS = table_contract(
    "committee_reports",
    grain="One row per captured GovInfo committee report package, with the CBO estimate it reprints or refuses.",
    identity=("package_id",),
    version_column="last_modified",
    columns={
        **_package_columns(
            type_column="report_type",
            type_description="The report's document-type code (hrpt, srpt, erpt).",
            number_column="report_number",
            number_description="The report's number within its Congress and type.",
        ),
        # Appended after the nineteen shared columns, the way a hosted table
        # takes new ones (docs/tables.md): every column before this keeps its
        # order and spelling for anyone pinning the prefix.  NULL throughout
        # where no estimate rule was run over this package's text.
        "estimate_rule": (
            "Which rule read this report's cost-estimate statement.  Named even though there is one today, "
            "for the reason document_citations names its own: a second reader over another rendition "
            "would have to say which one produced the span."
        ),
        "estimate_rule_version": (
            "That rule's version, a digest over all patterns, flags, rejects, heading thresholds and rule revision, so a re-read "
            "under a corrected rule is attributable."
        ),
        "report_states_estimate": (
            "Whether the report's own cover carries the statutory recital `Including cost estimate of the "
            "Congressional Budget Office`, printed in brackets.  This is the gate and a heading is never "
            "one: three retained "
            "reports print a CBO heading over a section saying the estimate was not received, and one prints "
            "the estimate under a heading no pattern set had.  `false` is requested-empty with "
            "estimate_absence_reason attached, never absence: 3 of 13 reported bills whose index named an "
            "estimate had none in the report."
        ),
        "recital_bill_id": (
            "The measure the cover states this report accompanies, keyed the way congress_bills.bill_id is, "
            "with the Congress taken from this package's own identity because the cover states none.  The "
            "print's own answer to the report-to-bill join, which is what cbo_cost_estimates.bill_id joins "
            "against; bill_id beside it stays whatever index record the caller read."
        ),
        "estimate_heading": (
            "The section heading the located span opens on, as the committee spelled it, collapsed to one "
            "line where GPO wrapped it across two.  Committee-specific prose no index states."
        ),
        "estimate_heading_rule": (
            "Which entry of the heading vocabulary matched.  **That vocabulary is a floor**: it only ever "
            "locates a span the recital already declared, and one retained report uses a spelling the routes "
            "measurement's five patterns missed."
        ),
        "letter_span_start": (
            "Character offset of the reprinted letter in the extracted text text_sha256 digests, counted "
            "from zero.  The letter is not carried in the row, so the span is how it is re-read."
        ),
        "letter_span_end": "Offset just past the letter, so text[letter_span_start:letter_span_end] is it.",
        "letter_text_sha256": (
            "Digest of exactly those characters, so a consumer can prove the span it re-read is the span that "
            "was measured.  A re-extraction that moved one character moves every offset after it, which is "
            "why text_sha256 says which text these offsets index into."
        ),
        "letter_end_rule": (
            "How the end was found: `director_attribution` on the letter's own close, or "
            "`next_heading_in_series` where the report prints a summary table with no attribution at all.  A "
            "declared letter whose end could not be found publishes a NULL span rather than a guessed "
            "boundary."
        ),
        "letter_signatory": (
            "The Director as the letter names them; NULL where the attribution states no name, which the one "
            "table-shaped estimate does."
        ),
        "estimate_absence_reason": (
            "The publisher's own paragraph saying why the estimate is not here, verbatim, where the cover "
            "declares none.  Carried whole rather than as a span, unlike the letter: it is a paragraph, and a "
            "row that holds the words needs no offset to read them."
        ),
        "estimate_absence_rule": (
            "Which reason pattern matched: `not_available` (the estimate had not arrived when the report was "
            "filed) or `not_received` (the committee asked and CBO had not answered).  NULL where the report "
            "gives no reason, which is not the same as having none to give."
        ),
    },
)

HEARING_TRANSCRIPTS = table_contract(
    "hearing_transcripts",
    grain="One row per captured GovInfo hearing transcript package.",
    identity=("package_id",),
    version_column="last_modified",
    columns={
        **_package_columns(
            type_column="hearing_type",
            type_description="The hearing's document-type code (hhrg, shrg, jhrg).",
            number_column="jacket_number",
            number_description="The hearing's printing jacket number, leading zeros kept because it is opaque.",
        ),
        # Overridden in place, so the column keeps its position for anyone
        # pinning the order; only the sentence changes.
        "bill_id": (
            "Always NULL here, and NULL for a stated reason: a legislative hearing is held on a *list* of "
            "bills -- twelve of them on CHRG-118hhrg56198 -- so a scalar column would have to pick one of "
            "twelve.  The relationship is one-to-many and `hearing_bill_links` hosts it, one row per "
            "hearing, bill and source, the way `event_id` names `committee_meetings`.  The column stays "
            "because this table shares its shape with `committee_reports`, where a report *is* filed "
            "against one bill."
        ),
        # Appended last, the way a hosted table takes a new column (docs/tables.md):
        # the nineteen columns before it keep their order for anyone pinning it.
        "event_id": (
            "The committee-meeting event id the Congress.gov hearing record names as its associatedMeeting, "
            "which committee_meetings.event_id joins on; NULL where the hearing names none or was not looked up."
        ),
    },
)

REPORT_SECTIONS = table_contract(
    "report_sections",
    grain="One row per agency block parsed out of one committee report's text.",
    identity=("package_id", "seq"),
    version_column="last_modified",
    columns={
        "package_id": "The report package this block was parsed from.",
        "seq": "Zero-based position of this block in the report, in reading order.",
        "agency_label": (
            "The agency heading this block sits under, or the `Full Report` sentinel where no header "
            "matched anywhere in the report.  NULL on a preamble block, which precedes the first header "
            "and so has neither."
        ),
        "agency_key": "The normalized agency key, which is what a recurrence count groups on.",
        "body": "The block's text, trimmed the way the original trimmed it.",
        "pattern": (
            "Which header pattern fired to start this block; this table's provenance column.  Two values "
            "are not pattern names: `preamble` for the text before the first header, and `full_report` "
            "for a report where no header matched at all."
        ),
        "char_start": "Start offset of this block's span in the flattened report text.",
        "char_end": "End offset, exclusive; spans partition the whole input with no gap and no overlap.",
        "page_start": "First page the span touches, where the input carried page boundaries.",
        "page_end": "Last page the span touches, where the input carried page boundaries.",
        "body_chars": "Character length of body, which can be shorter than the span it sits in.",
        "last_modified": (
            "The parent report's last_modified, carried so this table versions with the package it came from."
        ),
    },
)


def _package_row(
    body: object,
    *,
    type_column: str,
    number_column: str,
    bill_id: str | None,
    page_count: int | None,
    text_sha256: str | None,
) -> Row:
    """The row a committee report and a hearing transcript share, in publish order.

    The two tables differ in exactly two column names -- what the package's
    document-type code and its number are called -- so those are named by the
    caller and everything else is written once.
    """
    identity = body.identity
    capture = body.body_capture
    summary = body.summary
    return {
        "package_id": text(identity.package_id),
        "collection": text(identity.collection),
        "congress": text(identity.congress),
        type_column: text(identity.document_type),
        number_column: text(identity.number),
        "chamber": text(CHAMBER_BY_DOCUMENT_TYPE.get(identity.document_type or "")),
        "title": text(summary.title),
        "date_issued": text(summary.date_issued),
        "last_modified": text(summary.last_modified),
        "bill_id": text(bill_id),
        "format": text(body.format),
        "media_type": text(body.body.media_type),
        "requested_url": text(capture.requested_url),
        "resolved_url": text(capture.resolved_url),
        "byte_size": text(capture.byte_size),
        "sha256": text(capture.sha256),
        "observed_at": text(capture.observed_at),
        "page_count": text(page_count),
        "text_sha256": text(text_sha256),
    }


def shape_committee_report(
    body: object,
    *,
    bill_id: str | None = None,
    page_count: int | None = None,
    text_sha256: str | None = None,
    estimate: object = None,
    recital_bill_id: str | None = None,
) -> Row:
    """One ``committee_reports`` row from one acquired CRPT package.

    ``estimate`` is the ``interpretation.cbo_estimates.CboEstimateFinding``
    read over this package's extracted text, or ``None`` where no rule was
    run -- which lands as NULL throughout rather than as ``false``, because
    "not read" and "the cover declares no estimate" are different answers and
    the whole requested-empty rule turns on the difference.  It is read
    structurally, so this module stays the stdlib-only leaf ``schemas`` is.

    ``recital_bill_id`` is
    ``cbo_estimates.recital_bill_id(estimate, identity.congress)``, passed in
    rather than derived here for the reason ``shape_bill_committee`` takes
    ``referral_signal``: reading a printed designator into a bill key is the
    ``interpretation`` package's vocabulary, and this layer does not import it.
    """
    row = _package_row(
        body,
        type_column="report_type",
        number_column="report_number",
        bill_id=bill_id,
        page_count=page_count,
        text_sha256=text_sha256,
    )
    span = None if estimate is None else estimate.letter_span
    row |= {
        "estimate_rule": text(None if estimate is None else estimate.rule),
        "estimate_rule_version": text(None if estimate is None else estimate.rule_version),
        "report_states_estimate": flag(None if estimate is None else estimate.report_states_estimate),
        "recital_bill_id": text(recital_bill_id),
        "estimate_heading": text(None if estimate is None else estimate.heading),
        "estimate_heading_rule": text(None if estimate is None else estimate.heading_rule),
        "letter_span_start": text(None if span is None else span[0]),
        "letter_span_end": text(None if span is None else span[1]),
        "letter_text_sha256": text(None if estimate is None else estimate.letter_sha256),
        "letter_end_rule": text(None if estimate is None else estimate.letter_end_rule),
        "letter_signatory": text(None if estimate is None else estimate.signatory),
        "estimate_absence_reason": text(None if estimate is None else estimate.absence_reason),
        "estimate_absence_rule": text(None if estimate is None else estimate.absence_rule),
    }
    return row


def shape_hearing_transcript(
    body: object,
    *,
    page_count: int | None = None,
    text_sha256: str | None = None,
    event_id: str | None = None,
) -> Row:
    """One ``hearing_transcripts`` row from one acquired CHRG package.

    ``event_id`` is the ``associatedMeeting.eventId`` the Congress.gov hearing
    detail record states for this jacket, which the caller that read that
    record supplies; the package itself does not carry it.

    There is deliberately no ``bill_id`` argument, unlike
    :func:`shape_committee_report`: the hearing-to-bill relationship is
    one-to-many and ``hearing_bill_links`` hosts it, so this shaper cannot
    fill a scalar the contract says is always NULL.
    """
    row = _package_row(
        body,
        type_column="hearing_type",
        number_column="jacket_number",
        bill_id=None,
        page_count=page_count,
        text_sha256=text_sha256,
    )
    row["event_id"] = text(event_id)
    return row


def shape_report_section(
    block: object,
    *,
    package_id: str,
    seq: int,
    last_modified: str | None = None,
) -> Row:
    """One ``report_sections`` row from one parsed agency block.

    ``last_modified`` is a column for the same reason ``bill_sections`` carries
    its parent's ``version_date``: the design names it this table's version
    column, and a merge can only read a version column the table itself has.
    """
    start, end = block.char_span
    pages = block.page_span
    return {
        "package_id": text(package_id),
        "seq": text(seq),
        "agency_label": text(block.agency),
        "agency_key": text(block.agency_key),
        "body": text(block.body),
        "pattern": text(block.pattern),
        "char_start": text(start),
        "char_end": text(end),
        "page_start": text(None if pages is None else pages[0]),
        "page_end": text(None if pages is None else pages[1]),
        "body_chars": text(len(block.body)),
        "last_modified": text(last_modified),
    }


__all__ = [
    "CHAMBER_BY_DOCUMENT_TYPE",
    "COMMITTEE_REPORTS",
    "HEARING_TRANSCRIPTS",
    "REPORT_SECTIONS",
    "shape_committee_report",
    "shape_hearing_transcript",
    "shape_report_section",
]
