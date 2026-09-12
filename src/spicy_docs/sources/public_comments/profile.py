"""Profile for exact captures of the community public-comment table."""

from __future__ import annotations

from typing import Final

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.sources.public_comments import native as spicy_regs_tables

SPICY_REGS_PUBLIC_COMMENT_PROFILE: Final = SourceNativeProfile(
    name="SpicyRegs public comments",
    source_system_id=spicy_regs_tables.SOURCE_SYSTEM_ID,
    source_system_version=spicy_regs_tables.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=spicy_regs_tables.COMMENT_ACQUISITION_POLICY_ID,
    acquisition_policy_version=spicy_regs_tables.ACQUISITION_POLICY_VERSION,
    scope_id=spicy_regs_tables.COMMENT_SCOPE_ID,
    source_schema_key=spicy_regs_tables.COMMENT_SOURCE_SCHEMA_KEY,
    source_schema=spicy_regs_tables.SPICY_REGS_PUBLIC_COMMENT_SCHEMA,
    record_stem=spicy_regs_tables.COMMENT_RECORD_STEM,
    max_traversals=spicy_regs_tables.MAX_TRAVERSALS,
    source_state_scope="observed-crawl",
    traversal_acceptance="single-observed-traversal",
    acquisition_policy=spicy_regs_tables.comment_acquisition_policy,
    validate_query_scope=spicy_regs_tables.spicy_regs_public_comment_query_scope,
    parse_page_response=spicy_regs_tables.parse_comment_page_response,
    next_page=spicy_regs_tables.public_table_next_page,
    traversal_check=spicy_regs_tables.PublicTableTraversalCheck,
    classify_record=spicy_regs_tables.classify_comment_row,
    wrap_record=spicy_regs_tables.comment_source_record,
    record_digest=spicy_regs_tables.comment_source_record_digest,
    rendition_rows=spicy_regs_tables.comment_rendition_rows,
    source_schema_declaration=spicy_regs_tables.comment_source_schema_declaration,
    source_schema_digest=spicy_regs_tables.comment_source_schema_digest,
    validate_record_scope=spicy_regs_tables.validate_comment_record_scope,
    records_included=spicy_regs_tables.comment_records_included,
    acquisition_check=lambda: spicy_regs_tables.PublicTableAcquisitionCheck(spicy_regs_tables.COMMENT_TABLE),
    page_window=spicy_regs_tables.parse_public_table_request,
    # The upstream pipeline already selected the current row per comment_id.
    # This profile reports that selection; it does not re-collapse versions, so
    # a repeated identity in one capture fails closed rather than being picked
    # between here. The version column travels in the record and in the schema
    # declaration's provenance instead.
    observation_version=None,
)
