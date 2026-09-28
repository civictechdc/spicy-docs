"""The Regulations.gov attribute tables: what a document's, docket's or comment's API detail record states beyond the
thin ``documents``, ``dockets`` and ``comments`` tables, one row per record, typed natively (spicy-regs owner decisions
66 and 67).

A column is the API attribute it carries in snake_case, ``_json`` after the one attribute published as JSON text
(``displayProperties``, spelled by :func:`~spicy_docs.schemas.tables.json_column`). Lists of strings are
``VARCHAR[]``, and the publisher's instants (always ``YYYY-MM-DDTHH:MM:SSZ``) are ``TIMESTAMPTZ``. Submitters' stated
contact details are published (decision 66); attributes never stated, constant, derivable from the key, or already
carried by the thin tables are left out, as the contract note lists them (DocSpec
``docs/research/regulations-attributes-contract-2026-09-26.md``). A scalar VARCHAR attribute must be stated as a
string and ``displayProperties`` as an array, as DocSpec's exporter requires; anything else refuses.

:func:`project_document_attributes`, :func:`project_docket_attributes` and :func:`project_comment_attributes` are the
one spelling of a row: spicy-regs' ETL calls them per record and DocSpec's exporter proves its native spelling against
them.

``comment_attributes`` follows the same rules, with one difference the owner ruled on 2026-09-28: a comment's stated
``email`` and ``phone`` are left out. Documents state neither, so decision 66 never ruled on them; on comments they
are private individuals' contact details, bulk-queryable once published, with little analytic value.
:data:`COMMENT_ATTRIBUTES_LEFT_OUT` lists every comment attribute left out and why.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime

from spicy_docs.schemas.tables import (
    BOOLEAN,
    INTEGER,
    TIMESTAMPTZ,
    VALUE_KEY,
    VARCHAR,
    VARCHAR_LIST,
    Reference,
    TableContract,
    TableContractError,
    json_column,
    table_contract,
)

#: The only instant spelling the publisher states on these attributes (every one of 2,935,804 stated values, census
#: 2026-09-26); anything else refuses rather than being guessed at. ASCII digits only: ``\d`` would admit others.
_STATED_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _attribute_contract(
    name: str, *, grain: str, key: tuple[str, str], parent: str, columns: tuple[tuple[str, str, str], ...]
) -> TableContract:
    """A contract keyed ``value/1`` on its record's id, referencing the thin table's row, from (column, type,
    description) triples in publish order."""
    return table_contract(
        name,
        grain=grain,
        identity=(key[0],),
        version_column=None,
        columns={key[0]: key[1]} | {column: description for column, _, description in columns},
        key_spelling=VALUE_KEY,
        references=(Reference((key[0],), parent, (key[0],)),),
        types={column: column_type for column, column_type, _ in columns if column_type != VARCHAR},
    )


def attribute_of(column: str) -> str:
    """The API attribute a column carries: the column without ``_json``, in camelCase."""
    return re.sub(r"_([a-z0-9])", lambda match: match.group(1).upper(), column.removesuffix("_json"))


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or _STATED_INSTANT.fullmatch(value) is None:
        raise TableContractError(f"not a stated instant (YYYY-MM-DDTHH:MM:SSZ): {value!r}")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise TableContractError(f"not a calendar instant: {value!r}") from error


type _Plan = tuple[tuple[str, str, str], ...]


def _plan(contract: TableContract) -> _Plan:
    """(column, attribute, type) for every non-key column, worked out once per contract rather than once per row."""
    return tuple((column, attribute_of(column), contract.column_type(column)) for column in contract.columns[1:])


def _projected(contract: TableContract, plan: _Plan, key: str, attributes: Mapping[str, object]) -> dict[str, object]:
    row: dict[str, object] = {contract.identity[0]: key}
    for column, attribute, column_type in plan:
        stated = attributes.get(attribute)
        if stated is None:
            row[column] = None
        elif column_type == TIMESTAMPTZ:
            row[column] = _instant(stated)
        elif column_type != VARCHAR:
            row[column] = stated
        elif column.endswith("_json"):
            if not isinstance(stated, list):
                raise TableContractError(f"{contract.name}: {attribute} is {type(stated).__name__}, not an array")
            row[column] = json_column(stated)
        elif isinstance(stated, str):
            row[column] = stated
        else:
            raise TableContractError(f"{contract.name}: {attribute} is {type(stated).__name__}, not a string")
    contract.spelled_key(row)  # refuses a NULL or empty key, which checked() would pass
    return contract.checked(row)


DOCUMENT_ATTRIBUTES = _attribute_contract(
    "document_attributes",
    grain="One row per Regulations.gov document: the attributes the thin documents table does not carry.",
    key=("document_id", "The document's id; its API record is https://api.regulations.gov/v4/documents/{document_id}."),
    parent="documents",
    columns=(
        ("address1", VARCHAR, "The submitter's street address, first line, as stated."),
        ("address2", VARCHAR, "The submitter's street address, second line, as stated."),
        (
            "allow_late_comments",
            BOOLEAN,
            "Whether the agency accepts comments after the period closes, as the publisher stated it on the record's latest version; the comment window's state comes from its dates.",
        ),
        (
            "author_date",
            TIMESTAMPTZ,
            "When the document was written (labelled “Author/ Document Date”), a UTC instant.",
        ),
        (
            "authors",
            VARCHAR_LIST,
            "The document's authors, people or organizations, in the publisher's order; almost all on Supporting & Related Material.",
        ),
        ("category", VARCHAR, "The submitter's sector category the agency assigns."),
        ("cfr_part", VARCHAR, "The CFR parts the document affects, free text as stated."),
        ("city", VARCHAR, "The submitter's city."),
        ("comment", VARCHAR, "The record's comment text as stated, markup included."),
        ("country", VARCHAR, "The submitter's country."),
        (
            "display_properties_json",
            VARCHAR,
            "The agency's labels for this record's fields: a JSON array of {label, name, tooltip}, name being the attribute it labels; json_column spelling.",
        ),
        ("doc_abstract", VARCHAR, "The document's abstract or summary."),
        ("effective_date", TIMESTAMPTZ, "When the action takes effect, a UTC instant."),
        ("exhibit_location", VARCHAR, "Where a physical exhibit is held."),
        ("exhibit_type", VARCHAR, "The exhibit's type."),
        ("fax", VARCHAR, "The submitter's fax number."),
        (
            "field1",
            VARCHAR,
            "An agency-defined field; its meaning is the record's display_properties_json label (“Answer Date”, “XRIN”, “RTID”, …).",
        ),
        (
            "field2",
            VARCHAR,
            "An agency-defined field; its meaning is the record's display_properties_json label (labelled “File Date”).",
        ),
        ("first_name", VARCHAR, "The submitter's given name."),
        ("fr_vol_num", VARCHAR, "The Federal Register volume or citation, free text as stated."),
        ("gov_agency", VARCHAR, "The government body that submitted the document."),
        (
            "gov_agency_type",
            VARCHAR,
            "That body's level: Federal, State, Local, Tribal, Regional, U.S. House of Representatives or U.S. Senate.",
        ),
        ("implementation_date", TIMESTAMPTZ, "The implementation or service date, a UTC instant."),
        ("last_name", VARCHAR, "The submitter's family name."),
        (
            "legacy_id",
            VARCHAR,
            "The record's id in a predecessor system (“Document Legacy ID”, “Legacy Exhibit Number”, …).",
        ),
        ("media", VARCHAR, "How the document arrived: Electronic, Paper, … (spellings vary)."),
        ("object_id", VARCHAR, "The publisher's internal object handle."),
        ("omb_approval", VARCHAR, "An OMB control number, as stated."),
        (
            "open_for_comment",
            BOOLEAN,
            "Whether the document was open for comment, an observation as the publisher stated it on the record's latest version rather than a live status; the comment window's state comes from its dates.",
        ),
        ("organization", VARCHAR, "The organization the author or submitter names."),
        (
            "original_document_id",
            VARCHAR,
            "The id of the document this one derives from; sometimes the empty string.",
        ),
        ("page_count", INTEGER, "Pages in the content file."),
        ("postmark_date", TIMESTAMPTZ, "The postmark date (often labelled “Answer Date”), a UTC instant."),
        ("receive_date", TIMESTAMPTZ, "When the agency received the document, a UTC instant."),
        ("reg_writer_instruction", VARCHAR, "Agency notes (often labelled “Old Submitter”)."),
        ("restrict_reason", VARCHAR, "Why access is restricted, free text."),
        (
            "restrict_reason_type",
            VARCHAR,
            "The restriction's kind: Copyrighted, Confidential Business Information, Personally Identifiable Information or Other.",
        ),
        ("source_citation", VARCHAR, "The source publication's citation."),
        ("start_end_page", VARCHAR, "The Federal Register start and end pages, as stated."),
        ("state_province_region", VARCHAR, "The submitter's state, province or region."),
        ("subject", VARCHAR, "The subject line."),
        ("submitter_rep", VARCHAR, "The name of the submitter's representative."),
        ("subtype", VARCHAR, "The agency's subtype: Correspondence, Report, Decision and others."),
        ("topics", VARCHAR_LIST, "The publisher's topics, in its order."),
        ("tracking_nbr", VARCHAR, "The portal's tracking number."),
        (
            "within_comment_period",
            BOOLEAN,
            "Whether the document arrived within the comment period, where given, as the publisher stated it on the record's latest version; the comment window's state comes from its dates.",
        ),
        ("zip", VARCHAR, "The submitter's postal code."),
    ),
)


DOCKET_ATTRIBUTES = _attribute_contract(
    "docket_attributes",
    grain="One row per Regulations.gov docket: the attributes the thin dockets table does not carry.",
    key=("docket_id", "The docket's id; its API record is https://api.regulations.gov/v4/dockets/{docket_id}."),
    parent="dockets",
    columns=(
        ("category", VARCHAR, "The docket's status (labelled “Disposition”): Pending, Closed and others."),
        (
            "display_properties_json",
            VARCHAR,
            "The agency's labels for this docket's fields: a JSON array of {label, name, tooltip}; [] when none; json_column spelling.",
        ),
        (
            "effective_date",
            TIMESTAMPTZ,
            "Mostly the docket's close date (usually labelled “Docket Close Date”), a UTC instant.",
        ),
        (
            "field1",
            VARCHAR,
            "An agency-defined field (“Related Docket's RIN”, “Related To”, …); see display_properties_json.",
        ),
        ("field2", VARCHAR, "An agency-defined field (usually “Docket Status”); see display_properties_json."),
        ("generic", VARCHAR, "An agency program code (“Docket Item Code”, “Location”, “Program Area”)."),
        ("keywords", VARCHAR_LIST, "The docket's keywords, in the publisher's order."),
        ("legacy_id", VARCHAR, "The docket's id in a predecessor system."),
        ("object_id", VARCHAR, "The publisher's internal object handle."),
        (
            "organization",
            VARCHAR,
            "Labelled “Pre-EDOCKET ID” or “Organization”; see display_properties_json.",
        ),
        ("petition_nbr", VARCHAR, "A petition number."),
        ("program", VARCHAR, "The program office (usually labelled “Center”)."),
        ("short_title", VARCHAR, "A short title (sometimes labelled “Action Office”)."),
        ("sub_type", VARCHAR, "The agency's docket subtype."),
        ("sub_type2", VARCHAR, "A second docket subtype level."),
    ),
)

COMMENT_ATTRIBUTES = _attribute_contract(
    "comment_attributes",
    grain="One row per Regulations.gov comment: the attributes the thin comments table does not carry.",
    key=("comment_id", "The comment's id; its API record is https://api.regulations.gov/v4/comments/{comment_id}."),
    parent="comments",
    columns=(
        ("address1", VARCHAR, "The submitter's street address, first line, as stated."),
        ("address2", VARCHAR, "The submitter's street address, second line, as stated."),
        ("city", VARCHAR, "The submitter's city."),
        ("country", VARCHAR, "The submitter's country, spelled as stated (United States, US, ...)."),
        (
            "display_properties_json",
            VARCHAR,
            "The agency's labels for this record's fields: a JSON array of {label, name, tooltip}, name being the attribute it labels; json_column spelling.",
        ),
        ("doc_abstract", VARCHAR, "A summary the agency recorded for the comment; rarely stated."),
        ("fax", VARCHAR, "The submitter's fax number."),
        (
            "file_formats_json",
            VARCHAR,
            "Renditions of the comment's own content file, rarely stated: a JSON array of {fileUrl, format, size}; json_column spelling. Attached files are in the thin table's attachments_json.",
        ),
        ("gov_agency", VARCHAR, "The government body that submitted the comment."),
        ("gov_agency_type", VARCHAR, "That body's level: Federal, State, Local, Tribal and others."),
        ("legacy_id", VARCHAR, "The comment's id in a predecessor system."),
        ("object_id", VARCHAR, "The publisher's internal object handle."),
        ("page_count", INTEGER, "Pages in the content file, as stated."),
        ("postmark_date", TIMESTAMPTZ, "The postmark of a comment that arrived by mail, a UTC instant."),
        ("reason_withdrawn", VARCHAR, "The publisher's reason for a withdrawal, spelled as stated."),
        ("restrict_reason", VARCHAR, "Why access is restricted, free text."),
        (
            "restrict_reason_type",
            VARCHAR,
            "The restriction's kind: Copyrighted, Confidential Business Information, Personally Identifiable Information or Other.",
        ),
        ("state_province_region", VARCHAR, "The submitter's state, province or region."),
        ("submitter_rep", VARCHAR, "The name of the submitter's representative."),
        ("tracking_nbr", VARCHAR, "The portal's tracking number."),
        (
            "withdrawn",
            BOOLEAN,
            "Whether the comment has been withdrawn, as the publisher stated it on the record's latest version.",
        ),
        ("zip", VARCHAR, "The submitter's postal code."),
    ),
)

#: Every stated comment attribute ``comment_attributes`` does not carry, by reason. "Never stated" and "constant" are
#: measured on the spicy-regs re-read of every comment (4,368,949 objects when this was set, 2026-09-28; the full
#: read re-measures them); the thin ``comments`` table's attributes are what ``schemas.regulations.COMMENT.extract``
#: reads, which a test derives rather than lists.
COMMENT_ATTRIBUTES_LEFT_OUT: Mapping[str, tuple[str, ...]] = {
    "private contact details, left out by owner ruling (2026-09-28)": ("email", "phone"),
    "never stated": ("field1", "field2", "submitterRepAddress", "submitterRepCityState"),
    "constant (false)": ("openForComment",),
}

_DOCUMENT_PLAN = _plan(DOCUMENT_ATTRIBUTES)
_DOCKET_PLAN = _plan(DOCKET_ATTRIBUTES)
_COMMENT_PLAN = _plan(COMMENT_ATTRIBUTES)


def project_document_attributes(document_id: str, attributes: Mapping[str, object]) -> dict[str, object]:
    """One ``document_attributes`` row from a document's API detail record: its ``data.id`` and ``data.attributes``.

    A stated value of the wrong type (a string for a BOOLEAN, an instant in another spelling, a list holding a
    non-string, a NULL or empty id) refuses with :class:`~spicy_docs.schemas.tables.TableContractError`.
    """
    return _projected(DOCUMENT_ATTRIBUTES, _DOCUMENT_PLAN, document_id, attributes)


def project_docket_attributes(docket_id: str, attributes: Mapping[str, object]) -> dict[str, object]:
    """One ``docket_attributes`` row from a docket's API detail record: its ``data.id`` and ``data.attributes``."""
    return _projected(DOCKET_ATTRIBUTES, _DOCKET_PLAN, docket_id, attributes)


def project_comment_attributes(comment_id: str, attributes: Mapping[str, object]) -> dict[str, object]:
    """One ``comment_attributes`` row from a comment's API detail record: its ``data.id`` and ``data.attributes``.

    The same rules as :func:`project_document_attributes`: a stated value of the wrong type refuses with
    :class:`~spicy_docs.schemas.tables.TableContractError`.
    """
    return _projected(COMMENT_ATTRIBUTES, _COMMENT_PLAN, comment_id, attributes)
