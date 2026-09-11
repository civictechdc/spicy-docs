"""Federal Register acquisition policy and profile; imports no live transport."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Final, cast

from spicy_docs import federal_register_source_native as federal_register
from spicy_docs.source_native_profile import SourceNativeProfile

FEDERAL_REGISTER_ACQUISITION_POLICY_ID: Final = "urn:spicy-regs:acquisition:federal-register-paginated"
# Policy 1.1 makes identity composite (document_number, publication_date).
# Requested fields remain policy 1.0: correction_of was deferred and never
# landed. Version acquisition and fields independently. See docs/decisions.md
# for the SD-24 / DocSpec 0003 provenance and the deferred field decision.
FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION: Final = "1.1"
FEDERAL_REGISTER_SOURCE_SCHEMA_KEY: Final = "schemas/federal-register-document-1.0.schema.json"


def _federal_register_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
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
    # document_number is reused across unrelated documents: 00-111 resolves to
    # a 2000-01-18 "Notice of Filing of Plat of an Island; Minnesota" and also
    # discovers an older 2000-01-14 "Compliance Monitoring..." rule filed under
    # the same number. Identity is composite (the composite-identity decision,
    # 2026-09-04): document_number and publication_date together, so the two
    # 00-111 documents are distinct records and neither evicts the other.
    # observation_version still returns publication_date, but that value is
    # now part of the identity rather than a tiebreak across it -- it can
    # only ever agree within one identity, so it settles a residual repeat of
    # one (document_number, publication_date) pair, not a cross-date choice.
    observation_version=federal_register.federal_register_observation_version,
    # A repeat of one (document_number, publication_date) identity still
    # refuses unless every observed record shares a canonical digest.
    refuse_equal_observation_versions=False,
)
