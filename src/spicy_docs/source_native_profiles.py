"""Public profiles for supported source-native releases.

Import a source's own ``sources.<source>.profile`` module when only that source
is needed. In particular, offline Federal Register replay must not import GAO's
live transport as a side effect of obtaining its profile.
"""

from spicy_docs.sources.fec.audit_profile import FEC_AUDIT_QUERY_PROFILE
from spicy_docs.sources.fec.bulk_profile import FEC_BULK_FILES_PROFILE
from spicy_docs.sources.fec.candidate_profile import FEC_CANDIDATE_QUERY_PROFILE
from spicy_docs.sources.fec.filing_profile import FEC_FILING_QUERY_PROFILE
from spicy_docs.sources.fec.legal_profile import FEC_LEGAL_QUERY_PROFILE
from spicy_docs.sources.fec.profile import FEC_COMMITTEE_CENSUS_PROFILE
from spicy_docs.sources.fec.row_profile import FEC_POSITIONAL_ROWS_PROFILE
from spicy_docs.sources.federal_register.profile import (
    FEDERAL_REGISTER_ACQUISITION_POLICY_ID,
    FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION,
    FEDERAL_REGISTER_PROFILE,
    FEDERAL_REGISTER_SOURCE_SCHEMA_KEY,
)
from spicy_docs.sources.gao.profile import GAO_PRODUCT_PAGE_PROFILE
from spicy_docs.sources.public_comments.profile import SPICY_REGS_PUBLIC_COMMENT_PROFILE
from spicy_docs.sources.regulations_gov.profile import (
    REGULATIONS_GOV_COMMENT_PROFILE,
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)

__all__ = [
    "FEC_AUDIT_QUERY_PROFILE",
    "FEC_BULK_FILES_PROFILE",
    "FEC_CANDIDATE_QUERY_PROFILE",
    "FEC_COMMITTEE_CENSUS_PROFILE",
    "FEC_FILING_QUERY_PROFILE",
    "FEC_LEGAL_QUERY_PROFILE",
    "FEC_POSITIONAL_ROWS_PROFILE",
    "FEDERAL_REGISTER_ACQUISITION_POLICY_ID",
    "FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION",
    "FEDERAL_REGISTER_PROFILE",
    "FEDERAL_REGISTER_SOURCE_SCHEMA_KEY",
    "GAO_PRODUCT_PAGE_PROFILE",
    "REGULATIONS_GOV_COMMENT_PROFILE",
    "REGULATIONS_GOV_DOCKET_PROFILE",
    "REGULATIONS_GOV_DOCUMENT_PROFILE",
    "SPICY_REGS_PUBLIC_COMMENT_PROFILE",
]
