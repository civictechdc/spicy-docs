"""Shared data shapes that flow between sources and transforms.

``base`` holds the generic :class:`RecordType` contract, the sibling modules hold the
domain record shapes and every published table's :class:`~spicy_docs.schemas.tables.TableContract`,
and the whole package is a stdlib-only leaf -- no pyarrow, no DeltaTrack, no ``sources.*``
or ``interpretation.*`` imports -- so spicy-regs can import a column tuple without pulling
an HTTP client or a model client.  See ``docs/tables.md``.
"""

from collections.abc import Mapping
from types import MappingProxyType

from spicy_docs.schemas.activity_events import PUBLIC_ACTIVITY_EVENTS
from spicy_docs.schemas.base import RecordType
from spicy_docs.schemas.bill_action_tables import BILL_COMMITTEE_ACTIONS
from spicy_docs.schemas.bill_diff_tables import (
    FINANCIAL_CHANGES,
    SECTION_DIFF_ITEMS,
    SECTION_DIFFS,
)
from spicy_docs.schemas.bill_model_tables import (
    BILL_SUMMARIES,
    DIFF_SUMMARIES,
    SECTION_CLASSIFICATIONS,
)
from spicy_docs.schemas.bill_tables import (
    BILL_ACTIONS,
    BILL_COMMITTEES,
    BILL_PUBLISHER_SUMMARIES,
    CONGRESS_BILLS,
)
from spicy_docs.schemas.bill_version_tables import BILL_SECTIONS, BILL_VERSIONS
from spicy_docs.schemas.budget_volume_tables import BUDGET_VOLUMES
from spicy_docs.schemas.committee_report_tables import (
    COMMITTEE_REPORTS,
    HEARING_TRANSCRIPTS,
    REPORT_SECTION_READER_VERSION,
    REPORT_SECTIONS,
)
from spicy_docs.schemas.congress_activity_tables import (
    AMENDMENTS,
    MEMBER_VOTES,
    PRESS_RELEASES,
    ROLL_CALL_VOTES,
)
from spicy_docs.schemas.congress_index_tables import (
    COMMITTEE_MEETINGS,
    HOUSE_COMMUNICATIONS,
    NOMINATIONS,
    RECORD_ISSUES,
    TREATIES,
)
from spicy_docs.schemas.cost_estimate_tables import CBO_COST_ESTIMATES
from spicy_docs.schemas.document_citation_tables import (
    DOCUMENT_CITATIONS,
    HOUSE_ACTIVITY_REPORTS,
)
from spicy_docs.schemas.hearing_bill_link_tables import HEARING_BILL_LINKS
from spicy_docs.schemas.law_tables import LAW_CODE_SECTIONS, LAWS, TABLE3_RECORDS
from spicy_docs.schemas.legislator_tables import MEMBER_TERMS, MEMBERS
from spicy_docs.schemas.regulations import (
    COMMENT,
    COMMENTS,
    DOCKET,
    DOCKETS,
    DOCUMENT,
    DOCUMENTS,
    RECORD_TYPES,
)
from spicy_docs.schemas.roster_tables import COMMITTEE_ASSIGNMENTS, COMMITTEES
from spicy_docs.schemas.senate_expenditure_tables import SENATE_EXPENDITURES
from spicy_docs.schemas.tables import Reference, Row, TableContract, TableContractError

_REGISTERED: tuple[TableContract, ...] = (
    CONGRESS_BILLS,
    BILL_ACTIONS,
    BILL_COMMITTEES,
    BILL_PUBLISHER_SUMMARIES,
    # The fifth table the same BILLSTATUS document fills (B4): the CBO
    # cost-estimate index, keyless where CBO's own site is walled.
    CBO_COST_ESTIMATES,
    BILL_VERSIONS,
    BILL_SECTIONS,
    SECTION_DIFFS,
    SECTION_DIFF_ITEMS,
    FINANCIAL_CHANGES,
    SECTION_CLASSIFICATIONS,
    BILL_SUMMARIES,
    DIFF_SUMMARIES,
    PUBLIC_ACTIVITY_EVENTS,
    AMENDMENTS,
    PRESS_RELEASES,
    ROLL_CALL_VOTES,
    MEMBER_VOTES,
    MEMBERS,
    MEMBER_TERMS,
    COMMITTEE_REPORTS,
    REPORT_SECTIONS,
    HEARING_TRANSCRIPTS,
    # Wave 2, gaps A5, A7 and A10: the Congress.gov index tables.
    HOUSE_COMMUNICATIONS,
    COMMITTEE_MEETINGS,
    RECORD_ISSUES,
    TREATIES,
    NOMINATIONS,
    # --- A8 laws and A9 rosters (law_tables, roster_tables) ---
    LAWS,
    LAW_CODE_SECTIONS,
    TABLE3_RECORDS,
    COMMITTEES,
    COMMITTEE_ASSIGNMENTS,
    # The first PDF-only family contract and the shared link table it is built
    # on (the rollup's build order, step 1).
    DOCUMENT_CITATIONS,
    HOUSE_ACTIVITY_REPORTS,
    # The revised build order's first family: the budget volumes, whose print
    # names 504 public laws their own MODS does not (B4).
    BUDGET_VOLUMES,
    # The build order's step 4: the one PDF-only family whose value is a ruled
    # table and not a citation.
    SENATE_EXPENDITURES,
    # What the print states that no index does: the bill-action relationship,
    # hosted with its measured attachment reliability per row.
    BILL_COMMITTEE_ACTIONS,
    # A2 reopened: a hearing is held on a list, so the linkage is a table and
    # not a column, keyed on the source that stated each pair.
    HEARING_BILL_LINKS,
    # The Regulations.gov tables, keyed on the publisher's id so DocSpec can
    # admit a generation by reference (its decision 0007).
    DOCKETS,
    DOCUMENTS,
    COMMENTS,
)

if len({contract.name for contract in _REGISTERED}) != len(_REGISTERED):
    raise AssertionError("TABLE_CONTRACTS has a duplicate table name")

#: Every published table by name.  spicy-regs reads this to build its Arrow
#: schemas, its merge calls, its data-dictionary entries and its MCP view list,
#: so a table added here reaches all four without a second declaration.
TABLE_CONTRACTS: Mapping[str, TableContract] = MappingProxyType({c.name: c for c in _REGISTERED})

# A reference names a row of another published table, so it must name a
# registered table by exactly that table's identity.
for _contract in _REGISTERED:
    for _reference in _contract.references:
        _parent = TABLE_CONTRACTS.get(_reference.parent_table)
        if _parent is None or _reference.parent_columns != _parent.identity:
            raise TableContractError(
                f"{_contract.name}: a reference must name a registered table by its identity, "
                f"not {_reference.parent_table}{_reference.parent_columns}"
            )

__all__ = [
    "AMENDMENTS",
    "BILL_ACTIONS",
    "BILL_COMMITTEES",
    "BILL_COMMITTEE_ACTIONS",
    "BILL_PUBLISHER_SUMMARIES",
    "BILL_SECTIONS",
    "BILL_SUMMARIES",
    "BILL_VERSIONS",
    "BUDGET_VOLUMES",
    "CBO_COST_ESTIMATES",
    "COMMENT",
    "COMMENTS",
    "COMMITTEES",
    "COMMITTEE_ASSIGNMENTS",
    "COMMITTEE_MEETINGS",
    "COMMITTEE_REPORTS",
    "CONGRESS_BILLS",
    "DIFF_SUMMARIES",
    "DOCKET",
    "DOCKETS",
    "DOCUMENT",
    "DOCUMENTS",
    "DOCUMENT_CITATIONS",
    "FINANCIAL_CHANGES",
    "HEARING_BILL_LINKS",
    "HEARING_TRANSCRIPTS",
    "HOUSE_ACTIVITY_REPORTS",
    "HOUSE_COMMUNICATIONS",
    "LAWS",
    "LAW_CODE_SECTIONS",
    "MEMBERS",
    "MEMBER_TERMS",
    "MEMBER_VOTES",
    "NOMINATIONS",
    "PRESS_RELEASES",
    "PUBLIC_ACTIVITY_EVENTS",
    "RECORD_ISSUES",
    "RECORD_TYPES",
    "REPORT_SECTIONS",
    "REPORT_SECTION_READER_VERSION",
    "ROLL_CALL_VOTES",
    "SECTION_CLASSIFICATIONS",
    "SECTION_DIFFS",
    "SECTION_DIFF_ITEMS",
    "SENATE_EXPENDITURES",
    "TABLE3_RECORDS",
    "TABLE_CONTRACTS",
    "TREATIES",
    "RecordType",
    "Reference",
    "Row",
    "TableContract",
    "TableContractError",
]
