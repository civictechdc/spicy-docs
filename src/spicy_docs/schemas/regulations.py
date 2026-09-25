"""The regulations.gov docket, document and comment record types, and the contracts of the tables published from them.

Each :class:`RecordType` pairs an S3 path pattern, Parquet schema, dedup key and extract function; ``RECORD_TYPES`` keys
them by name, and its order drives the default set of data types the pipeline processes.  ``DOCKETS``, ``DOCUMENTS``
and ``COMMENTS`` state the tables the host publishes: the extract's columns in its order, then on documents and
comments the host's ``pdf_extraction_results_json``, each keyed on its dedup key spelled ``value/1``.
"""

from json import dumps as json_dumps

from spicy_docs.schemas.base import RecordType
from spicy_docs.schemas.tables import VALUE_KEY, table_contract


def _extract_comment(d: dict) -> dict:
    attrs = d.get("data", {}).get("attributes", {})

    # Build compact attachments JSON from the included array
    attachments = []
    for inc in d.get("included", []):
        if inc.get("type") == "attachments":
            inc_attrs = inc.get("attributes", {})
            formats = [
                {"url": f["fileUrl"], "format": f.get("format"), "size": f.get("size")}
                for f in inc_attrs.get("fileFormats") or []
                if f.get("fileUrl")
            ]
            if formats:
                attachments.append({"title": inc_attrs.get("title", ""), "formats": formats})

    return {
        "comment_id": d.get("data", {}).get("id"),
        "docket_id": (v.strip('"') if (v := attrs.get("docketId")) else v),
        "agency_code": attrs.get("agencyId"),
        "first_name": attrs.get("firstName"),
        "last_name": attrs.get("lastName"),
        "organization": attrs.get("organization"),
        "category": attrs.get("category"),
        "title": attrs.get("title"),
        "comment": attrs.get("comment"),
        "document_type": attrs.get("documentType"),
        "posted_date": attrs.get("postedDate"),
        "modify_date": attrs.get("modifyDate"),
        "receive_date": attrs.get("receiveDate"),
        "attachments_json": json_dumps(attachments) if attachments else None,
        # Left None here; filled downstream. The run-pipeline ETL (which stays in
        # spicy-regs) fills it inline from Mirrulations' pre-extracted text
        # (transforms.EnrichCommentText), with the PDF text-extraction step
        # (spicy_regs.enrich_pdf) as the backfill for attachments not yet
        # extracted upstream.
        "text_content": None,
        "text_extraction_status": None,
    }


def _extract_document(d: dict) -> dict:
    attrs = d.get("data", {}).get("attributes", {})

    # Each fileFormats entry is one downloadable rendition of the document
    # (e.g. content.pdf), carrying its own URL, format, and byte size. Keep the
    # full list — the single file_url below is retained for backward compat.
    attachments = [
        {"url": f["fileUrl"], "format": f.get("format"), "size": f.get("size")}
        for f in attrs.get("fileFormats") or []
        if f.get("fileUrl")
    ]

    return {
        "document_id": d.get("data", {}).get("id"),
        "docket_id": (v.strip('"') if (v := attrs.get("docketId")) else v),
        "agency_code": attrs.get("agencyId"),
        "title": attrs.get("title"),
        "document_type": attrs.get("documentType"),
        "posted_date": attrs.get("postedDate"),
        "modify_date": attrs.get("modifyDate"),
        "comment_start_date": attrs.get("commentStartDate"),
        "comment_end_date": attrs.get("commentEndDate"),
        "file_url": attachments[0]["url"] if attachments else None,
        "attachments_json": json_dumps(attachments) if attachments else None,
        "fr_doc_num": attrs.get("frDocNum"),
        "withdrawn": attrs.get("withdrawn"),
        "reason_withdrawn": attrs.get("reasonWithdrawn"),
        "additional_rins": (json_dumps(rins) if (rins := attrs.get("additionalRins")) else None),
        # Populated out-of-band by the PDF text-extraction step
        # (spicy_regs.enrich_pdf, which stays in spicy-regs); the raw JSON has
        # no text layer.
        "text_content": None,
        "text_extraction_status": None,
    }


DOCKET = RecordType(
    name="dockets",
    path_pattern="/docket/",
    schema={
        "docket_id": str,
        "agency_code": str,
        "title": str,
        "docket_type": str,
        "modify_date": str,
        "abstract": str,
        "rin": str,
    },
    dedup_key="docket_id",
    extract=lambda d: {
        "docket_id": (v.strip('"') if (v := d.get("data", {}).get("id")) else v),
        "agency_code": d.get("data", {}).get("attributes", {}).get("agencyId"),
        "title": d.get("data", {}).get("attributes", {}).get("title"),
        "docket_type": d.get("data", {}).get("attributes", {}).get("docketType"),
        "modify_date": d.get("data", {}).get("attributes", {}).get("modifyDate"),
        "abstract": d.get("data", {}).get("attributes", {}).get("dkAbstract"),
        "rin": d.get("data", {}).get("attributes", {}).get("rin"),
    },
)


DOCUMENT = RecordType(
    name="documents",
    path_pattern="/documents/",
    schema={
        "document_id": str,
        "docket_id": str,
        "agency_code": str,
        "title": str,
        "document_type": str,
        "posted_date": str,
        "modify_date": str,
        "comment_start_date": str,
        "comment_end_date": str,
        "file_url": str,
        "attachments_json": str,
        "fr_doc_num": str,
        "withdrawn": str,
        "reason_withdrawn": str,
        "additional_rins": str,
        # Text extracted from the document's PDF rendition, plus the outcome
        # of that extraction ("ok"/"empty"/"encrypted"/"error"/None if not yet run).
        "text_content": str,
        "text_extraction_status": str,
    },
    dedup_key="document_id",
    extract=_extract_document,
)


COMMENT = RecordType(
    name="comments",
    path_pattern="/comments/",
    schema={
        "comment_id": str,
        "docket_id": str,
        "agency_code": str,
        "first_name": str,
        "last_name": str,
        "organization": str,
        "category": str,
        "title": str,
        "comment": str,
        "document_type": str,
        "posted_date": str,
        "modify_date": str,
        "receive_date": str,
        "attachments_json": str,
        # Text extracted from the comment's PDF attachment(s), plus the outcome
        # ("ok"/"empty"/"encrypted"/"error"/None if not yet run).
        "text_content": str,
        "text_extraction_status": str,
    },
    dedup_key="comment_id",
    extract=_extract_comment,
)


# Registry keyed by record-type name. Order matters: it drives the default
# set of data types the pipeline processes.
RECORD_TYPES: dict[str, RecordType] = {
    "dockets": DOCKET,
    "documents": DOCUMENT,
    "comments": COMMENT,
}


# The published tables.  Each key is the publisher's own id, which DocSpec
# decision 0004 keeps as the identity even for a document filed under two
# agencies; verified unique and non-empty on two 2026-09-25 generations
# (``docs/tables.md``).  The host's merge keeps the newest ``modify_date``.
DOCKETS = table_contract(
    "dockets",
    grain="One row per Regulations.gov docket, the folder an agency opens for one rulemaking or other action.",
    identity=(DOCKET.dedup_key,),
    version_column="modify_date",
    key_spelling=VALUE_KEY,
    columns={
        "docket_id": "The publisher's docket id, such as `ACF-2007-0125`.",
        "agency_code": "The publisher's code for the agency that owns the docket (`agencyId`).",
        "title": "The docket's title as the publisher states it.",
        "docket_type": "The publisher's docket category: `Rulemaking` or `Nonrulemaking`.",
        "modify_date": "When the publisher last modified the docket, an ISO 8601 UTC instant that sorts as it reads.",
        "abstract": "The agency's summary of the docket (`dkAbstract`), often NULL.",
        "rin": "The Regulation Identifier Number the publisher ties the docket to, often NULL or `Not Assigned`.",
    },
)

DOCUMENTS = table_contract(
    "documents",
    grain="One row per document an agency posted on Regulations.gov: a rule, notice or supporting material.",
    identity=(DOCUMENT.dedup_key,),
    version_column="modify_date",
    key_spelling=VALUE_KEY,
    columns={
        "document_id": "The publisher's document id, usually its docket id and a sequence (`FAA-2016-6907-0001`).",
        "docket_id": "The docket the publisher files the document under (`docketId`); NULL when it names none.",
        "agency_code": "The publisher's code for the posting agency (`agencyId`).",
        "title": "The document's title as the publisher states it.",
        "document_type": (
            "The publisher's category: `Rule`, `Proposed Rule`, `Notice`, `Supporting & Related Material`, `Other` "
            "or `Public Submission`."
        ),
        "posted_date": "When the document was posted, an ISO 8601 UTC instant kept as stated, year 0000 included.",
        "modify_date": "When the publisher last modified the document, an ISO 8601 UTC instant.",
        "comment_start_date": "When the comment period this document opens begins; NULL when it opens none.",
        "comment_end_date": (
            "When that period closes, almost always 23:59:59 Eastern spelled in UTC, so its UTC date is the day after "
            "the deadline."
        ),
        "file_url": "The first rendition the publisher lists, kept for older readers; `attachments_json` has them all.",
        "attachments_json": (
            "Every rendition the publisher lists, a JSON array of `url`, `format` and `size` objects in its order; "
            "NULL when it lists none."
        ),
        "fr_doc_num": "The Federal Register document number the publisher states (`frDocNum`), often NULL.",
        "withdrawn": "The publisher's withdrawal flag, `true` or `false`; NULL when the record states none.",
        "reason_withdrawn": "The publisher's reason for a withdrawal, spelled as stated; NULL when it states none.",
        "additional_rins": "Further Regulation Identifier Numbers the publisher lists, a JSON array; NULL when none.",
        "text_content": "Text the host extracted from the document's PDF renditions; NULL until one produced text.",
        "text_extraction_status": (
            "The host's PDF extraction outcome, `ok`, `empty`, `encrypted` or `error`; NULL before an attempt."
        ),
        "pdf_extraction_results_json": (
            "The host's latest PDF attempt, a JSON array with each selected URL's outcome and the SHA-256 of the "
            "bytes read; NULL when none is recorded."
        ),
    },
)

COMMENTS = table_contract(
    "comments",
    grain="One row per public comment posted on Regulations.gov.",
    identity=(COMMENT.dedup_key,),
    version_column="modify_date",
    key_spelling=VALUE_KEY,
    columns={
        "comment_id": "The publisher's comment id, usually its docket id and a sequence (`APHIS-2004-0018-0031`).",
        "docket_id": "The docket the publisher files the comment under (`docketId`); NULL when it names none.",
        "agency_code": "The publisher's code for the agency that received the comment (`agencyId`).",
        "first_name": "The submitter's first name, when given.",
        "last_name": "The submitter's last name, when given.",
        "organization": "The organization the submitter names, when given.",
        "category": "The submitter category the publisher assigns, often NULL.",
        "title": "The comment's title as the publisher states it.",
        "comment": "The comment's body as the publisher states it, markup included.",
        "document_type": "The publisher's category, `Public Submission` for almost every comment.",
        "posted_date": "When the comment was posted, an ISO 8601 UTC instant.",
        "modify_date": "When the publisher last modified the comment, an ISO 8601 UTC instant.",
        "receive_date": "When the agency received the comment, an ISO 8601 UTC instant.",
        "attachments_json": (
            "Each attached file's title and renditions, a JSON array of `title` and `formats` objects; NULL when "
            "there are none."
        ),
        "text_content": (
            "Text of the attachments, from Mirrulations' own extraction where it has one, else the host's PDF step; "
            "NULL when neither produced text."
        ),
        "text_extraction_status": (
            "Where `text_content` came from: `derived` for Mirrulations' extraction, else the host's PDF outcome "
            "(`ok`, `empty`, `encrypted`, `error`); NULL before either."
        ),
        "pdf_extraction_results_json": (
            "Provenance of `text_content` as JSON: for `derived` text the Mirrulations objects it was read from, else "
            "the host's latest PDF attempts; NULL when neither is recorded."
        ),
    },
)
