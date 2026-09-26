"""Stable public Federal Register source columns and their faithful projection."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from spicy_docs.schemas.tables import FEDERAL_REGISTER_RECORD_KEY, table_contract

FEDERAL_REGISTER_COLUMNS: tuple[str, ...] = (
    "document_number",
    "title",
    "abstract",
    "document_type",
    "publication_date",
    "effective_on",
    "comments_close_on",
    "signing_date",
    "agencies_json",
    "agency_slugs",
    "docket_ids_json",
    "regulation_id_numbers_json",
    "cfr_references_json",
    "topics_json",
    "html_url",
    "pdf_url",
    "body_html_url",
    "volume",
    "start_page",
    "end_page",
    "subtype",
    "executive_order_number",
    "modify_date",
)


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def project_federal_register_document(document: Mapping[str, Any]) -> dict[str, str | None]:
    """Project one exact API record onto the stable public source columns.

    ``modify_date`` is always NULL: the API states no update instant.
    """

    agencies = document.get("agencies") or []
    agency_slugs = ",".join(
        str(agency["slug"]) for agency in agencies if isinstance(agency, Mapping) and agency.get("slug")
    )
    return {
        "document_number": _text(document.get("document_number")),
        "title": _text(document.get("title")),
        "abstract": _text(document.get("abstract")),
        "document_type": _text(document.get("type")),
        "publication_date": _text(document.get("publication_date")),
        "effective_on": _text(document.get("effective_on")),
        "comments_close_on": _text(document.get("comments_close_on")),
        "signing_date": _text(document.get("signing_date")),
        "agencies_json": json.dumps(agencies),
        "agency_slugs": agency_slugs or None,
        "docket_ids_json": json.dumps(document.get("docket_ids") or []),
        "regulation_id_numbers_json": json.dumps(document.get("regulation_id_numbers") or []),
        "cfr_references_json": json.dumps(document.get("cfr_references") or []),
        "topics_json": json.dumps(document.get("topics") or []),
        "html_url": _text(document.get("html_url")),
        "pdf_url": _text(document.get("pdf_url")),
        "body_html_url": _text(document.get("body_html_url")),
        "volume": _text(document.get("volume")),
        "start_page": _text(document.get("start_page")),
        "end_page": _text(document.get("end_page")),
        "subtype": _text(document.get("subtype")),
        "executive_order_number": _text(document.get("executive_order_number")),
        # The API exposes no update instant; preserve the public null column.
        "modify_date": None,
    }


#: The published table: the projection plus the host's derived ``rin``. The identity is the dated record, because
#: the Register reuses a document number when it republishes a correction under it on another date. Its key spelling is
#: the ``number@date`` DocSpec already records (``federal-register-source-record-id/1``). ``documents.fr_doc_num`` names a document
#: number only, so it is not a :class:`~spicy_docs.schemas.tables.Reference`: the host's ``table_joins`` watches it,
#: and the resolved link, on ``unpadded_federal_register_document_number``, is a DocSpec layer.
FEDERAL_REGISTER = table_contract(
    "federal_register",
    grain="One row per dated Federal Register document: a rule, proposed rule, notice or presidential document.",
    identity=("document_number", "publication_date"),
    version_column=None,
    key_spelling=FEDERAL_REGISTER_RECORD_KEY,
    columns={
        "document_number": "The Register's document number, spelled as it serves it (`2017-07442`, unpadded before 2013).",
        "title": "The document's title.",
        "abstract": "The agency's abstract of the document; often NULL.",
        "document_type": "The Register's category: `Rule`, `Proposed Rule`, `Notice` or `Presidential Document`.",
        "publication_date": "The date the document was published, canonical YYYY-MM-DD.",
        "effective_on": "The date the action takes effect, when stated; often NULL.",
        "comments_close_on": "The public comment deadline, for a document that opens a comment period; often NULL.",
        "signing_date": "The date a presidential document was signed; NULL for other documents.",
        "agencies_json": "The issuing agencies as the Register's agency objects, a JSON array.",
        "agency_slugs": "The issuing agencies' Register slugs, comma-separated; NULL when none.",
        "docket_ids_json": "The docket labels the document states, a JSON array, as printed (many are agency numbers).",
        "regulation_id_numbers_json": "The Regulation Identifier Numbers the document states, a JSON array; often `[]`.",
        "cfr_references_json": "The CFR citations the document affects, a JSON array of `{title, part, chapter, citation_url}`.",
        "topics_json": "The Register's CFR index terms for the document (`topics`), a JSON array; `[]` when it lists none.",
        "html_url": "The document's page on federalregister.gov.",
        "pdf_url": "The document's PDF rendition.",
        "body_html_url": "The document's full-text HTML body; the XML body the Register also serves carries no boilerplate.",
        "volume": "The Federal Register volume.",
        "start_page": "The document's first page.",
        "end_page": "The document's last page.",
        "subtype": "The Register's subtype, when set; often NULL.",
        "executive_order_number": "The executive order number, for a presidential executive order; NULL otherwise.",
        "modify_date": "Always NULL: the Register's API states no update instant.",
        "rin": "The host's derived first RIN of `regulation_id_numbers_json`; NULL when it states none.",
    },
)

__all__ = [
    "FEDERAL_REGISTER",
    "FEDERAL_REGISTER_COLUMNS",
    "project_federal_register_document",
]
