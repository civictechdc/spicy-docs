"""The Regulations.gov attribute tables: what a document's or docket's API detail record states beyond the thin
``documents`` and ``dockets`` tables, one row per record, typed natively (spicy-regs owner decisions 66 and 67).

A column is the API attribute it carries in snake_case, ``_json`` after the one attribute published as JSON text
(``displayProperties``). Scalars are spelled by :func:`~spicy_docs.schemas.tables.text`, lists of strings are
``VARCHAR[]``, and the publisher's instants (always ``YYYY-MM-DDTHH:MM:SSZ``) are ``TIMESTAMPTZ``. Submitters' stated
contact details are published (decision 66); attributes never stated, constant, derivable from the key, or already
carried by the thin tables are left out, as the contract note lists them (DocSpec
``docs/research/regulations-attributes-contract-2026-09-26.md``).

:func:`project_document_attributes` and :func:`project_docket_attributes` are the one spelling of a row: spicy-regs'
ETL calls them per record and DocSpec's exporter proves its native spelling against them.
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
    text,
)

#: The only instant spelling the publisher states on these attributes (every one of 3,035,813 stated values, census
#: 2026-09-26); anything else refuses rather than being guessed at.
_STATED_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


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
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _projected(contract: TableContract, key: str, attributes: Mapping[str, object]) -> dict[str, object]:
    row: dict[str, object] = {contract.identity[0]: key}
    for column in contract.columns[1:]:
        stated = attributes.get(attribute_of(column))
        column_type = contract.column_type(column)
        if stated is None:
            row[column] = None
        elif column_type == TIMESTAMPTZ:
            row[column] = _instant(stated)
        elif column_type == VARCHAR:
            row[column] = json_column(stated) if column.endswith("_json") else text(stated)
        else:
            row[column] = stated
    return contract.checked(row)


DOCUMENT_ATTRIBUTES = _attribute_contract(
    "document_attributes",
    grain="One row per Regulations.gov document: the attributes the thin documents table does not carry.",
    key=("document_id", "The document's id; its API record is https://api.regulations.gov/v4/documents/{document_id}."),
    parent="documents",
    columns=(
        ("address1", VARCHAR, "The submitter's street address, first line, as stated."),
        ("address2", VARCHAR, "The submitter's street address, second line, as stated."),
        ("allow_late_comments", BOOLEAN, "Whether the agency accepts comments after the period closes."),
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
        ("category", VARCHAR, "The submitter's sector category the agency assigns; 38 values."),
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
            "An agency-defined field; its meaning is the record's display_properties_json label (“File Date” on all but one).",
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
            "Whether the document was open for comment when captured; an observation, not a live status.",
        ),
        ("organization", VARCHAR, "The organization the author or submitter names."),
        (
            "original_document_id",
            VARCHAR,
            "The id of the document this one derives from; the empty string on 368,375 records.",
        ),
        ("page_count", INTEGER, "Pages in the content file."),
        ("postmark_date", TIMESTAMPTZ, "The postmark date (often labelled “Answer Date”), a UTC instant."),
        ("receive_date", TIMESTAMPTZ, "When the agency received the document, a UTC instant."),
        ("reg_writer_instruction", VARCHAR, "Agency notes (labelled “Old Submitter” on 61,052)."),
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
        ("subtype", VARCHAR, "The agency's subtype: Correspondence, Report, Decision, … (823 values)."),
        ("topics", VARCHAR_LIST, "The publisher's topics, in its order."),
        ("tracking_nbr", VARCHAR, "The portal's tracking number."),
        ("within_comment_period", BOOLEAN, "Whether the document arrived within the comment period, when stated."),
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
            "The agency's labels for this docket's fields: a JSON array of {label, name, tooltip}; [] on 64,859; json_column spelling.",
        ),
        (
            "effective_date",
            TIMESTAMPTZ,
            "Mostly the docket's close date (labelled “Docket Close Date” on 13,111), a UTC instant.",
        ),
        (
            "field1",
            VARCHAR,
            "An agency-defined field (“Related Docket's RIN”, “Related To”, …); see display_properties_json.",
        ),
        ("field2", VARCHAR, "An agency-defined field (“Docket Status” on 59,872); see display_properties_json."),
        ("generic", VARCHAR, "An agency program code (“Docket Item Code”, “Location”, “Program Area”)."),
        ("keywords", VARCHAR_LIST, "The docket's keywords, in the publisher's order."),
        ("legacy_id", VARCHAR, "The docket's id in a predecessor system."),
        ("object_id", VARCHAR, "The publisher's internal object handle."),
        (
            "organization",
            VARCHAR,
            "Labelled “Pre-EDOCKET ID” on 3,980 and “Organization” on 3,766; see display_properties_json.",
        ),
        ("petition_nbr", VARCHAR, "A petition number."),
        ("program", VARCHAR, "The program office (labelled “Center” on 64,910)."),
        ("short_title", VARCHAR, "A short title (labelled “Action Office” on 13,262)."),
        ("sub_type", VARCHAR, "The agency's docket subtype; 411 values."),
        ("sub_type2", VARCHAR, "A second docket subtype level."),
    ),
)


def project_document_attributes(document_id: str, attributes: Mapping[str, object]) -> dict[str, object]:
    """One ``document_attributes`` row from a document's API detail record: its ``data.id`` and ``data.attributes``.

    A stated value of the wrong type (a string for a BOOLEAN, an instant in another spelling, a list holding a
    non-string) refuses with :class:`~spicy_docs.schemas.tables.TableContractError`.
    """
    return _projected(DOCUMENT_ATTRIBUTES, document_id, attributes)


def project_docket_attributes(docket_id: str, attributes: Mapping[str, object]) -> dict[str, object]:
    """One ``docket_attributes`` row from a docket's API detail record: its ``data.id`` and ``data.attributes``."""
    return _projected(DOCKET_ATTRIBUTES, docket_id, attributes)
