"""The FEC committee master as a table: one row per committee per two-year cycle, and its row projection."""

from __future__ import annotations

from collections.abc import Mapping

from spicy_docs.schemas.tables import table_contract
from spicy_docs.sources.fec.committee_master import COMMITTEE_MASTER_FIELDS

#: Each published column after ``committee_id`` and ``cycle``, and the header field it copies.
_FROM_FIELD: dict[str, str] = {
    "name": "CMTE_NM",
    "treasurer_name": "TRES_NM",
    "street_1": "CMTE_ST1",
    "street_2": "CMTE_ST2",
    "city": "CMTE_CITY",
    "state": "CMTE_ST",
    "zip": "CMTE_ZIP",
    "designation": "CMTE_DSGN",
    "committee_type": "CMTE_TP",
    "party": "CMTE_PTY_AFFILIATION",
    "filing_frequency": "CMTE_FILING_FREQ",
    "organization_type": "ORG_TP",
    "connected_organization_name": "CONNECTED_ORG_NM",
    "candidate_id": "CAND_ID",
}
if {"CMTE_ID", *_FROM_FIELD.values()} != set(COMMITTEE_MASTER_FIELDS):
    raise AssertionError("fec_committee_history must map every committee master field once")


def project_committee_master_row(row: Mapping) -> dict[str, str | None]:
    """Project one :func:`iter_committee_master_rows` row onto the published columns; a blank field is NULL.

    A blank ``CMTE_ID`` refuses: it would publish an empty identity.
    """
    fields = row["fields"]
    if not fields["CMTE_ID"]:
        raise ValueError("FEC committee master row has a blank CMTE_ID")
    projected: dict[str, str | None] = {"committee_id": fields["CMTE_ID"], "cycle": str(row["cycle"])}
    projected.update({column: fields[field] or None for column, field in _FROM_FIELD.items()})
    return projected


FEC_COMMITTEE_HISTORY = table_contract(
    "fec_committee_history",
    grain="One row per FEC committee per two-year cycle, as that cycle's bulk committee master states it.",
    identity=("committee_id", "cycle"),
    version_column=None,
    columns={
        "committee_id": "The FEC committee id (`CMTE_ID`).",
        "cycle": "The two-year cycle the file covers, as its closing even year.",
        "name": "The committee's name as that cycle's file states it (`CMTE_NM`); NULL when blank.",
        "treasurer_name": "The treasurer's name as filed (`TRES_NM`); NULL when blank.",
        "street_1": "The first street line of the committee's address (`CMTE_ST1`); NULL when blank.",
        "street_2": "The second street line (`CMTE_ST2`); NULL when blank.",
        "city": "The address city (`CMTE_CITY`); NULL when blank.",
        "state": "The address state (`CMTE_ST`); NULL when blank.",
        "zip": "The address ZIP code as filed (`CMTE_ZIP`); NULL when blank.",
        "designation": "The FEC's committee designation code (`CMTE_DSGN`), literal; NULL when blank.",
        "committee_type": "The FEC's committee type code (`CMTE_TP`), literal; NULL when blank.",
        "party": "The party affiliation code (`CMTE_PTY_AFFILIATION`); NULL when blank.",
        "filing_frequency": "The filing frequency code (`CMTE_FILING_FREQ`), literal; NULL when blank.",
        "organization_type": "The interest-group category code (`ORG_TP`); NULL when blank.",
        "connected_organization_name": "The connected organization's name (`CONNECTED_ORG_NM`); NULL when blank.",
        "candidate_id": "The candidate the committee is linked to that cycle (`CAND_ID`); NULL when none.",
    },
)

__all__ = ["FEC_COMMITTEE_HISTORY", "project_committee_master_row"]
