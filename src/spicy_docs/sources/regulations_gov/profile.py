"""Regulations.gov collection profiles share acquisition mechanics and retain distinct selection rules."""

from __future__ import annotations

from functools import partial
from typing import Final

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.sources.regulations_gov import definitions, evidence, records, schemas, scope

REGULATIONS_GOV_DOCUMENT_PROFILE: Final = SourceNativeProfile(
    name="Regulations.gov documents",
    source_system_id=definitions.DOCUMENT_SOURCE_SYSTEM_ID,
    source_system_version=definitions.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=definitions.DOCUMENT_ACQUISITION_POLICY_ID,
    acquisition_policy_version=definitions.ACQUISITION_POLICY_VERSION,
    scope_id=definitions.DOCUMENT_SCOPE_ID,
    source_schema_key=definitions.DOCUMENT_SOURCE_SCHEMA_KEY,
    source_schema=schemas.REGULATIONS_GOV_DOCUMENT_SCHEMA,
    record_stem=definitions.DOCUMENT_RECORD_STEM,
    max_traversals=definitions.MAX_TRAVERSALS,
    source_state_scope="complete-snapshot",
    traversal_acceptance="source-enumeration",
    acquisition_policy=scope.document_acquisition_policy,
    validate_query_scope=scope.regulations_gov_document_query_scope,
    parse_page_response=evidence.parse_document_page_response,
    next_page=scope.regulations_gov_next_page_url,
    traversal_check=scope.RegulationsGovTraversalCheck,
    classify_record=records.classify_document,
    wrap_record=records.document_source_record,
    record_digest=records.document_source_record_digest,
    rendition_rows=records.document_rendition_rows,
    source_schema_declaration=schemas.document_source_schema_declaration,
    source_schema_digest=schemas.document_source_schema_digest,
    validate_record_scope=scope.validate_document_record_scope,
    records_included=scope.document_records_included,
    acquisition_check=lambda: scope.MirrulationsAcquisitionCheck(definitions.DOCUMENT_COLLECTION),
    page_window=scope.parse_mirrulations_request,
    # The mirror carries repeat observations of the same document id (a newer
    # modifyDate/postedDate object alongside an older one, e.g. Mirrulations'
    # "(1)" suffix files); collapse to the newest exactly as comments do
    # (2026-09-02, spec §4 amendment).
    observation_version=partial(records.observation_version, collection=definitions.DOCUMENT_COLLECTION),
    # ACF-2026-0199 (18)/(19) are byte-identical objects at one modifyDate
    # instant (Mirrulations refetch); collapse them, don't refuse the tie.
    refuse_equal_observation_versions=False,
    # BIS-2023-0021-0001 and EPA-HQ-OAR-2006-0894-0021 each have two objects
    # at one modifyDate instant differing only in a read-time-derived field
    # (openForComment); judge those ties on the narrower digest instead of
    # refusing (2026-09-02, spec §4 amendment).
    tie_comparison_digest=records.document_tie_comparison_digest,
)

REGULATIONS_GOV_DOCKET_PROFILE: Final = SourceNativeProfile(
    name="Regulations.gov dockets",
    source_system_id=definitions.DOCKET_SOURCE_SYSTEM_ID,
    source_system_version=definitions.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=definitions.DOCKET_ACQUISITION_POLICY_ID,
    acquisition_policy_version=definitions.ACQUISITION_POLICY_VERSION,
    scope_id=definitions.DOCKET_SCOPE_ID,
    source_schema_key=definitions.DOCKET_SOURCE_SCHEMA_KEY,
    source_schema=schemas.REGULATIONS_GOV_DOCKET_SCHEMA,
    record_stem=definitions.DOCKET_RECORD_STEM,
    max_traversals=definitions.MAX_TRAVERSALS,
    source_state_scope="complete-snapshot",
    traversal_acceptance="source-enumeration",
    acquisition_policy=scope.docket_acquisition_policy,
    validate_query_scope=scope.regulations_gov_docket_query_scope,
    parse_page_response=evidence.parse_docket_page_response,
    next_page=scope.regulations_gov_next_page_url,
    traversal_check=scope.RegulationsGovTraversalCheck,
    classify_record=records.classify_docket,
    wrap_record=records.docket_source_record,
    record_digest=records.docket_source_record_digest,
    rendition_rows=records.docket_rendition_rows,
    source_schema_declaration=schemas.docket_source_schema_declaration,
    source_schema_digest=schemas.docket_source_schema_digest,
    validate_record_scope=scope.validate_docket_record_scope,
    records_included=scope.docket_records_included,
    acquisition_check=lambda: scope.MirrulationsAcquisitionCheck(definitions.DOCKET_COLLECTION),
    page_window=scope.parse_mirrulations_request,
    # The mirror carries repeat observations of the same docket id (ACF-2007-0125:
    # a 2021-02-12 object and a newer 2024-06-12 "(1)" object); collapse to the
    # newest exactly as comments do (2026-09-02, spec §4 amendment).
    observation_version=partial(records.observation_version, collection=definitions.DOCKET_COLLECTION),
    # ACF-2026-0199 (18)/(19) are byte-identical objects at one modifyDate
    # instant (Mirrulations refetch); collapse them, don't refuse the tie.
    refuse_equal_observation_versions=False,
)

REGULATIONS_GOV_COMMENT_PROFILE: Final = SourceNativeProfile(
    name="Regulations.gov comments",
    source_system_id=definitions.COMMENT_SOURCE_SYSTEM_ID,
    source_system_version=definitions.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=definitions.COMMENT_ACQUISITION_POLICY_ID,
    acquisition_policy_version=definitions.COMMENT_ACQUISITION_POLICY_VERSION,
    scope_id=definitions.COMMENT_SCOPE_ID,
    source_schema_key=definitions.COMMENT_SOURCE_SCHEMA_KEY,
    source_schema=schemas.REGULATIONS_GOV_COMMENT_SCHEMA,
    record_stem=definitions.COMMENT_RECORD_STEM,
    max_traversals=definitions.MAX_TRAVERSALS,
    source_state_scope="complete-snapshot",
    traversal_acceptance="source-enumeration",
    acquisition_policy=scope.comment_acquisition_policy,
    validate_query_scope=scope.regulations_gov_comment_query_scope,
    parse_page_response=evidence.parse_comment_page_response,
    next_page=scope.regulations_gov_next_page_url,
    traversal_check=scope.RegulationsGovTraversalCheck,
    classify_record=records.classify_comment,
    wrap_record=records.comment_source_record,
    record_digest=records.comment_source_record_digest,
    rendition_rows=records.comment_rendition_rows,
    source_schema_declaration=schemas.comment_source_schema_declaration,
    source_schema_digest=schemas.comment_source_schema_digest,
    validate_record_scope=scope.validate_comment_record_scope,
    records_included=scope.comment_records_included,
    acquisition_check=lambda: scope.MirrulationsAcquisitionCheck(definitions.COMMENT_COLLECTION),
    page_window=scope.parse_mirrulations_request,
    observation_version=records.comment_observation_version,
    # Comments join the 2026-09-02 amendment (2026-09-23): a census of every ACF comment found
    # 23 (id, instant) groups repeated by Mirrulations "(1)" refetch files, all byte-identical and
    # none differing. Identical records collapse; differing records at one instant still refuse.
    refuse_equal_observation_versions=False,
)
