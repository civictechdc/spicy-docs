"""Committee reports, the agency blocks inside them, and hearing transcripts.

All three are keyed on the GovInfo package id, not on a bill (C11).  A
package-keyed report is fillable today by ``GovInfoBodyAcquirer``; the bill
linkage is not, so ``bill_id`` is nullable and a row exists without it rather
than the table waiting on a join nothing can make yet.  That is the correction
the placement study asked for on ``hearing_transcripts``, whose defect was a
contract nothing filled.

``report_sections.pattern`` is this table's provenance column: it names the
header pattern that fired to produce the block, so a mis-split report is
readable from the row rather than only from re-running the parser.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import Row, table_contract, text

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
    grain="One row per captured GovInfo committee report package.",
    identity=("package_id",),
    version_column="last_modified",
    columns=_package_columns(
        type_column="report_type",
        type_description="The report's document-type code (hrpt, srpt, erpt).",
        number_column="report_number",
        number_description="The report's number within its Congress and type.",
    ),
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
) -> Row:
    """One ``committee_reports`` row from one acquired CRPT package."""
    return _package_row(
        body,
        type_column="report_type",
        number_column="report_number",
        bill_id=bill_id,
        page_count=page_count,
        text_sha256=text_sha256,
    )


def shape_hearing_transcript(
    body: object,
    *,
    bill_id: str | None = None,
    page_count: int | None = None,
    text_sha256: str | None = None,
    event_id: str | None = None,
) -> Row:
    """One ``hearing_transcripts`` row from one acquired CHRG package.

    ``event_id`` is the ``associatedMeeting.eventId`` the Congress.gov hearing
    detail record states for this jacket, which the caller that read that
    record supplies; the package itself does not carry it.
    """
    row = _package_row(
        body,
        type_column="hearing_type",
        number_column="jacket_number",
        bill_id=bill_id,
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
