"""GAO product-page acquisition profile."""

from __future__ import annotations

from typing import Final

from spicy_docs import gao_product_pages_source_native as gao
from spicy_docs.source_native_profile import SourceNativeProfile

GAO_PRODUCT_PAGE_PROFILE: Final = SourceNativeProfile(
    name="GAO product pages",
    source_system_id=gao.SOURCE_SYSTEM_ID,
    source_system_version=gao.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=gao.ACQUISITION_POLICY_ID,
    acquisition_policy_version=gao.ACQUISITION_POLICY_VERSION,
    scope_id=gao.SCOPE_ID,
    source_schema_key=gao.SOURCE_SCHEMA_KEY,
    source_schema=gao.GAO_PRODUCT_PAGE_SCHEMA,
    record_stem=gao.RECORD_STEM,
    max_traversals=gao.MAX_TRAVERSALS,
    source_state_scope="complete-snapshot",
    traversal_acceptance="source-enumeration",
    acquisition_policy=gao.gao_product_acquisition_policy,
    validate_query_scope=gao.gao_product_query_scope,
    parse_page_response=gao.parse_gao_product_page_response,
    next_page=gao.gao_product_next_page_url,
    traversal_check=gao.GaoProductTraversalCheck,
    classify_record=gao.classify_gao_product_page,
    wrap_record=gao.source_record,
    record_digest=gao.source_record_digest,
    rendition_rows=gao.rendition_rows,
    source_schema_declaration=gao.source_schema_declaration,
    source_schema_digest=gao.source_schema_digest,
    validate_record_scope=gao.validate_record_scope,
    records_included=gao.gao_product_records_included,
    acquisition_check=gao.GaoProductAcquisitionCheck,
    page_window=gao.parse_gao_product_request,
)
