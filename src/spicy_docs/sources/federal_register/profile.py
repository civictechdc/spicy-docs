"""Federal Register acquisition policy and profile; imports no live transport."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Final, cast

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.sources.federal_register import native as federal_register

FEDERAL_REGISTER_ACQUISITION_POLICY_ID: Final = "urn:spicy-regs:acquisition:federal-register-paginated"
# Policy 1.3 adds the publisher's XML locator and pins fields and renditions.
# Admission and replay require this policy; see docs/sources/federal-register.md.
FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION: Final = "1.3"
FEDERAL_REGISTER_SOURCE_SCHEMA_KEY: Final = "schemas/federal-register-document-1.1.schema.json"


def _federal_register_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    """Refuse a record whose publication date falls outside the validated page window."""
    del query_scope
    if (
        not isinstance(page_window, tuple)
        or len(page_window) != 2
        or not all(isinstance(value, date) for value in page_window)
    ):
        raise federal_register.FederalRegisterSourceError("Federal Register page lacks a validated date window")
    typed_window = cast(tuple[date, date], page_window)
    record_date = date.fromisoformat(str(record["publication_date"]))
    if not typed_window[0] <= record_date <= typed_window[1]:
        raise federal_register.FederalRegisterSourceError("Federal Register result falls outside its date window")


FEDERAL_REGISTER_PROFILE: Final = SourceNativeProfile(
    name="Federal Register",
    source_system_id=federal_register.SOURCE_SYSTEM_ID,
    source_system_version=federal_register.SOURCE_SYSTEM_VERSION,
    acquisition_policy_id=FEDERAL_REGISTER_ACQUISITION_POLICY_ID,
    acquisition_policy_version=FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION,
    scope_id=federal_register.SCOPE_ID,
    source_schema_key=FEDERAL_REGISTER_SOURCE_SCHEMA_KEY,
    source_schema=federal_register.FEDERAL_REGISTER_DOCUMENT_SCHEMA,
    record_stem="federal-register",
    max_traversals=federal_register.MAX_RECONCILIATION_TRAVERSALS,
    source_state_scope="observed-crawl",
    traversal_acceptance="stable-consecutive-traversals",
    acquisition_policy=federal_register.federal_register_acquisition_policy,
    validate_query_scope=federal_register.federal_register_query_scope,
    parse_page_response=federal_register.parse_page_response,
    next_page=federal_register.federal_register_next_page_url,
    traversal_check=federal_register.FederalRegisterTraversalCheck,
    classify_record=federal_register.classify_document,
    wrap_record=federal_register.source_record,
    record_digest=federal_register.source_record_digest,
    rendition_rows=federal_register.rendition_rows,
    source_schema_declaration=federal_register.source_schema_declaration,
    source_schema_digest=federal_register.source_schema_digest,
    validate_record_scope=_federal_register_record_scope,
    records_included=federal_register.federal_register_records_included,
    acquisition_check=federal_register.FederalRegisterAcquisitionCheck,
    page_window=federal_register.federal_register_request_window,
    # Pair number and date because unrelated documents can reuse a number.
    # observation_version returns the date too, so it agrees within an identity;
    # it only participates in resolving repeated observations of that same pair.
    observation_version=federal_register.federal_register_observation_version,
    # A repeat of one (document_number, publication_date) identity still
    # refuses unless every observed record shares a canonical digest.
    refuse_equal_observation_versions=False,
)
