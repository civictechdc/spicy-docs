"""Regulations.gov collection profiles share acquisition mechanics and retain distinct selection rules."""

from __future__ import annotations

from functools import partial
from typing import Final

from spicy_docs import regulations_gov_source_native as regulations_gov
from spicy_docs.source_native_profile import SourceNativeProfile

REGULATIONS_GOV_DOCUMENT_PROFILE: Final = SourceNativeProfile(
    name="Regulations.gov documents",
    source_system_id=regulations_gov.DOCUMENT_SOURCE_SYSTEM_ID,
    source_system_version=regulations_gov.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=regulations_gov.DOCUMENT_ACQUISITION_POLICY_ID,
    acquisition_policy_version=regulations_gov.ACQUISITION_POLICY_VERSION,
    scope_id=regulations_gov.DOCUMENT_SCOPE_ID,
    source_schema_key=regulations_gov.DOCUMENT_SOURCE_SCHEMA_KEY,
    source_schema=regulations_gov.REGULATIONS_GOV_DOCUMENT_SCHEMA,
    record_stem=regulations_gov.DOCUMENT_RECORD_STEM,
    max_traversals=regulations_gov.MAX_TRAVERSALS,
    source_state_scope="complete-snapshot",
    traversal_acceptance="source-enumeration",
    acquisition_policy=regulations_gov.document_acquisition_policy,
    validate_query_scope=regulations_gov.regulations_gov_document_query_scope,
    parse_page_response=regulations_gov.parse_document_page_response,
    next_page=regulations_gov.regulations_gov_next_page_url,
    traversal_check=regulations_gov.RegulationsGovTraversalCheck,
    classify_record=regulations_gov.classify_document,
    wrap_record=regulations_gov.document_source_record,
    record_digest=regulations_gov.document_source_record_digest,
    rendition_rows=regulations_gov.document_rendition_rows,
    source_schema_declaration=regulations_gov.document_source_schema_declaration,
    source_schema_digest=regulations_gov.document_source_schema_digest,
    validate_record_scope=regulations_gov.validate_document_record_scope,
    records_included=regulations_gov.document_records_included,
    acquisition_check=lambda: regulations_gov.MirrulationsAcquisitionCheck(regulations_gov.DOCUMENT_COLLECTION),
    page_window=regulations_gov.parse_mirrulations_request,
    # The mirror carries repeat observations of the same document id (a newer
    # modifyDate/postedDate object alongside an older one, e.g. Mirrulations'
    # "(1)" suffix files); collapse to the newest exactly as comments do
    # (2026-09-02, spec §4 amendment).
    observation_version=partial(regulations_gov.observation_version, collection=regulations_gov.DOCUMENT_COLLECTION),
    # ACF-2026-0199 (18)/(19) are byte-identical objects at one modifyDate
    # instant (Mirrulations refetch); collapse them, don't refuse the tie.
    refuse_equal_observation_versions=False,
    # BIS-2023-0021-0001 and EPA-HQ-OAR-2006-0894-0021 each have two objects
    # at one modifyDate instant differing only in a read-time-derived field
    # (openForComment); judge those ties on the narrower digest instead of
    # refusing (2026-09-02, spec §4 amendment).
    tie_comparison_digest=regulations_gov.document_tie_comparison_digest,
)

REGULATIONS_GOV_DOCKET_PROFILE: Final = SourceNativeProfile(
    name="Regulations.gov dockets",
    source_system_id=regulations_gov.DOCKET_SOURCE_SYSTEM_ID,
    source_system_version=regulations_gov.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=regulations_gov.DOCKET_ACQUISITION_POLICY_ID,
    acquisition_policy_version=regulations_gov.ACQUISITION_POLICY_VERSION,
    scope_id=regulations_gov.DOCKET_SCOPE_ID,
    source_schema_key=regulations_gov.DOCKET_SOURCE_SCHEMA_KEY,
    source_schema=regulations_gov.REGULATIONS_GOV_DOCKET_SCHEMA,
    record_stem=regulations_gov.DOCKET_RECORD_STEM,
    max_traversals=regulations_gov.MAX_TRAVERSALS,
    source_state_scope="complete-snapshot",
    traversal_acceptance="source-enumeration",
    acquisition_policy=regulations_gov.docket_acquisition_policy,
    validate_query_scope=regulations_gov.regulations_gov_docket_query_scope,
    parse_page_response=regulations_gov.parse_docket_page_response,
    next_page=regulations_gov.regulations_gov_next_page_url,
    traversal_check=regulations_gov.RegulationsGovTraversalCheck,
    classify_record=regulations_gov.classify_docket,
    wrap_record=regulations_gov.docket_source_record,
    record_digest=regulations_gov.docket_source_record_digest,
    rendition_rows=regulations_gov.docket_rendition_rows,
    source_schema_declaration=regulations_gov.docket_source_schema_declaration,
    source_schema_digest=regulations_gov.docket_source_schema_digest,
    validate_record_scope=regulations_gov.validate_docket_record_scope,
    records_included=regulations_gov.docket_records_included,
    acquisition_check=lambda: regulations_gov.MirrulationsAcquisitionCheck(regulations_gov.DOCKET_COLLECTION),
    page_window=regulations_gov.parse_mirrulations_request,
    # The mirror carries repeat observations of the same docket id (ACF-2007-0125:
    # a 2021-02-12 object and a newer 2024-06-12 "(1)" object); collapse to the
    # newest exactly as comments do (2026-09-02, spec §4 amendment).
    observation_version=partial(regulations_gov.observation_version, collection=regulations_gov.DOCKET_COLLECTION),
    # ACF-2026-0199 (18)/(19) are byte-identical objects at one modifyDate
    # instant (Mirrulations refetch); collapse them, don't refuse the tie.
    refuse_equal_observation_versions=False,
)

REGULATIONS_GOV_COMMENT_PROFILE: Final = SourceNativeProfile(
    name="Regulations.gov comments",
    source_system_id=regulations_gov.COMMENT_SOURCE_SYSTEM_ID,
    source_system_version=regulations_gov.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=regulations_gov.COMMENT_ACQUISITION_POLICY_ID,
    acquisition_policy_version=regulations_gov.ACQUISITION_POLICY_VERSION,
    scope_id=regulations_gov.COMMENT_SCOPE_ID,
    source_schema_key=regulations_gov.COMMENT_SOURCE_SCHEMA_KEY,
    source_schema=regulations_gov.REGULATIONS_GOV_COMMENT_SCHEMA,
    record_stem=regulations_gov.COMMENT_RECORD_STEM,
    max_traversals=regulations_gov.MAX_TRAVERSALS,
    source_state_scope="complete-snapshot",
    traversal_acceptance="source-enumeration",
    acquisition_policy=regulations_gov.comment_acquisition_policy,
    validate_query_scope=regulations_gov.regulations_gov_comment_query_scope,
    parse_page_response=regulations_gov.parse_comment_page_response,
    next_page=regulations_gov.regulations_gov_next_page_url,
    traversal_check=regulations_gov.RegulationsGovTraversalCheck,
    classify_record=regulations_gov.classify_comment,
    wrap_record=regulations_gov.comment_source_record,
    record_digest=regulations_gov.comment_source_record_digest,
    rendition_rows=regulations_gov.comment_rendition_rows,
    source_schema_declaration=regulations_gov.comment_source_schema_declaration,
    source_schema_digest=regulations_gov.comment_source_schema_digest,
    validate_record_scope=regulations_gov.validate_comment_record_scope,
    records_included=regulations_gov.comment_records_included,
    acquisition_check=lambda: regulations_gov.MirrulationsAcquisitionCheck(regulations_gov.COMMENT_COLLECTION),
    page_window=regulations_gov.parse_mirrulations_request,
    observation_version=regulations_gov.comment_observation_version,
    refuse_equal_observation_versions=True,
)
