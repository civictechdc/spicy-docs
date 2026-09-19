"""Shared data shapes that flow between sources and transforms.

``base`` holds the generic :class:`RecordType` contract; domain-specific
record definitions (e.g. the regulations.gov shapes) live alongside it and
are re-exported here for convenience.

The table-contract layer lives here too: :class:`~spicy_docs.schemas.tables.TableContract`
and the family modules that declare one contract and one pure ``shape_*``
function per published table.  The whole package is a stdlib-only leaf -- no
pyarrow, no DeltaTrack, no ``sources.*`` or ``interpretation.*`` imports -- so
spicy-regs can import a column tuple without pulling an HTTP client, a model
client or a git dependency.  See ``docs/tables.md``.
"""

from collections.abc import Mapping
from types import MappingProxyType

from spicy_docs.schemas.activity_events import PUBLIC_ACTIVITY_EVENTS
from spicy_docs.schemas.base import RecordType
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
from spicy_docs.schemas.committee_report_tables import (
    COMMITTEE_REPORTS,
    HEARING_TRANSCRIPTS,
    REPORT_SECTIONS,
)
from spicy_docs.schemas.congress_activity_tables import (
    AMENDMENTS,
    MEMBER_VOTES,
    PRESS_RELEASES,
    ROLL_CALL_VOTES,
)
from spicy_docs.schemas.legislator_tables import MEMBER_TERMS, MEMBERS
from spicy_docs.schemas.regulations import COMMENT, DOCKET, DOCUMENT, RECORD_TYPES
from spicy_docs.schemas.tables import Row, TableContract, TableContractError

_REGISTERED: tuple[TableContract, ...] = (
    CONGRESS_BILLS,
    BILL_ACTIONS,
    BILL_COMMITTEES,
    BILL_PUBLISHER_SUMMARIES,
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
)

if len({contract.name for contract in _REGISTERED}) != len(_REGISTERED):
    raise AssertionError("TABLE_CONTRACTS has a duplicate table name")

#: Every published table by name.  spicy-regs reads this to build its Arrow
#: schemas, its merge calls, its data-dictionary entries and its MCP view list,
#: so a table added here reaches all four without a second declaration.
TABLE_CONTRACTS: Mapping[str, TableContract] = MappingProxyType({c.name: c for c in _REGISTERED})

__all__ = [
    "AMENDMENTS",
    "BILL_ACTIONS",
    "BILL_COMMITTEES",
    "BILL_PUBLISHER_SUMMARIES",
    "BILL_SECTIONS",
    "BILL_SUMMARIES",
    "BILL_VERSIONS",
    "COMMENT",
    "COMMITTEE_REPORTS",
    "CONGRESS_BILLS",
    "DIFF_SUMMARIES",
    "DOCKET",
    "DOCUMENT",
    "FINANCIAL_CHANGES",
    "HEARING_TRANSCRIPTS",
    "MEMBERS",
    "MEMBER_TERMS",
    "MEMBER_VOTES",
    "PRESS_RELEASES",
    "PUBLIC_ACTIVITY_EVENTS",
    "RECORD_TYPES",
    "REPORT_SECTIONS",
    "ROLL_CALL_VOTES",
    "SECTION_CLASSIFICATIONS",
    "SECTION_DIFFS",
    "SECTION_DIFF_ITEMS",
    "TABLE_CONTRACTS",
    "RecordType",
    "Row",
    "TableContract",
    "TableContractError",
]
