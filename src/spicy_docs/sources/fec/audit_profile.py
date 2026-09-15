"""Publish a complete retained /v1/audit-case/ query using its audit_case_id.

An audit_id, committee, cycle or report link is metadata, not a replacement for
the publisher's case identity. Categories remain attributed source observations;
this profile does not read report PDFs or infer findings from category names.
"""

import re
from collections.abc import Mapping
from functools import partial

from spicy_docs.sources.fec.query_profile import (
    RECORD_FIELDS,
    CountedTraversal,
    observation_schema,
    retained_query_profile,
)
from spicy_docs.sources.fec.retained import iter_pages, page_request, query_scope

SOURCE_SYSTEM_ID = "https://api.open.fec.gov/v1/audit-case/"
SCHEMA_NAME = "fec-audit-case-observation"
SCHEMA_VERSION = "1.0"
SCHEMA_KEY = f"schemas/{SCHEMA_NAME}-{SCHEMA_VERSION}.json"
SCOPE_ID = "fec-retained-audit-query"
_request = partial(page_request, endpoint=SOURCE_SYSTEM_ID)
audit_query_scope = partial(query_scope, request=_request)
iter_retained_audit_pages = partial(iter_pages, request=_request)


def _scope(value):
    if set(value) != {"captures"}:
        raise ValueError("FEC audit query scope fields differ")
    return audit_query_scope(value["captures"])


def _classify(value):
    if not isinstance(value, Mapping) or set(value) != RECORD_FIELDS or not isinstance(value["metadata"], Mapping):
        raise ValueError("FEC audit observation fields differ")
    identity = value["metadata"].get("audit_case_id")
    if not isinstance(identity, str) or re.fullmatch(r"[0-9]+", identity) is None:
        raise ValueError("FEC audit observation lacks its native audit_case_id")
    return dict(value)


_SCHEMA = observation_schema(
    name=SCHEMA_NAME,
    version=SCHEMA_VERSION,
    identity="audit_case_id",
    metadata={
        "type": "object",
        "required": ["audit_case_id"],
        "properties": {
            "audit_case_id": {"type": "string", "pattern": "^[0-9]+$"},
        },
    },
)

FEC_AUDIT_QUERY_PROFILE = retained_query_profile(
    name="Retained OpenFEC audit case query",
    endpoint=SOURCE_SYSTEM_ID,
    schema_name=SCHEMA_NAME,
    schema_version=SCHEMA_VERSION,
    schema_key=SCHEMA_KEY,
    schema=_SCHEMA,
    scope_id=SCOPE_ID,
    record_stem="fec-audit-case",
    identity="audit_case_id",
    request=_request,
    scope=_scope,
    classify=_classify,
    traversal=partial(CountedTraversal, request=_request, classify=_classify),
    policy={
        "strategy": "replay-pinned-exact-count-audit-case-query",
        "coverageLimits": [
            "Only the pinned audit-case query and its explicit publisher filters are covered.",
            "Audit categories, associated identifiers and report links remain source metadata.",
            "A complete observed query establishes no frozen snapshot, complete report files or historical audit census.",
            "Requested-empty queries remain observations; linked originals and category reference endpoints are separate.",
        ],
        "recordIdentity": "native audit_case_id; audit_id and committee identifiers remain metadata",
    },
)

__all__ = ["FEC_AUDIT_QUERY_PROFILE", "audit_query_scope", "iter_retained_audit_pages"]
