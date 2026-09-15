"""Publish one pinned OpenFEC candidate query, preserving its literal scope.

The ordinary /v1/candidates/ answer supplies candidate_id identity. Counts cover
that query observation, not historical candidate profiles or every requested ID.
Omitted IDs produce no invented rows. Repeated source IDs refuse publication;
overlapping queries belong in separate releases. No source sorting is assumed.
"""

from __future__ import annotations

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

SOURCE_SYSTEM_ID = "https://api.open.fec.gov/v1/candidates/"
SCHEMA_NAME = "fec-candidate-observation"
SCHEMA_VERSION = "1.0"
SCHEMA_KEY = f"schemas/{SCHEMA_NAME}-{SCHEMA_VERSION}.json"
SCOPE_ID = "fec-retained-candidate-query"
# Retained HTTP422 describes P/H/S followed by eight letters or numbers.
# Validate that shape without rewriting case or inferring office/state semantics.
_ID_PATTERN = r"[HSP][0-9A-Za-z]{8}"
_request = partial(page_request, endpoint=SOURCE_SYSTEM_ID)
candidate_query_scope = partial(query_scope, request=_request)
iter_retained_candidate_pages = partial(iter_pages, request=_request)


def _scope(value: Mapping) -> dict:
    if set(value) != {"captures"}:
        raise ValueError("FEC candidate query scope fields differ")
    return candidate_query_scope(value["captures"])


def _classify(value: object) -> dict:
    if not isinstance(value, Mapping) or set(value) != RECORD_FIELDS or not isinstance(value["metadata"], Mapping):
        raise ValueError("FEC candidate observation fields differ")
    identity = value["metadata"].get("candidate_id")
    if not isinstance(identity, str) or re.fullmatch(_ID_PATTERN, identity) is None:
        raise ValueError("FEC candidate observation lacks its native candidate_id")
    pairs, _ = _request(value["capture"]["requestUrl"])
    selected = [item for key, item in pairs if key == "candidate_id"]
    if selected and identity not in selected:
        raise ValueError("FEC candidate result falls outside its explicit candidate-ID selection")
    return dict(value)


_SCHEMA = observation_schema(
    name=SCHEMA_NAME,
    version=SCHEMA_VERSION,
    identity="candidate_id",
    metadata={
        "type": "object",
        "required": ["candidate_id"],
        "properties": {"candidate_id": {"type": "string", "pattern": f"^{_ID_PATTERN}$"}},
    },
)

FEC_CANDIDATE_QUERY_PROFILE = retained_query_profile(
    name="Retained OpenFEC candidate query",
    endpoint=SOURCE_SYSTEM_ID,
    schema_name=SCHEMA_NAME,
    schema_version=SCHEMA_VERSION,
    schema_key=SCHEMA_KEY,
    schema=_SCHEMA,
    scope_id=SCOPE_ID,
    record_stem="fec-candidate",
    identity="candidate_id",
    request=_request,
    scope=_scope,
    classify=_classify,
    traversal=partial(CountedTraversal, request=_request, classify=_classify),
    policy={
        "strategy": "replay-pinned-exact-count-candidate-query",
        "coverageLimits": [
            "Only the pinned candidates query and its explicit publisher filters are covered.",
            "Requested-empty or omitted candidate IDs are query observations, not proof of source absence.",
            "Cycles and election years remain source fields, not reconstructed historical profiles.",
            "No frozen publisher snapshot, full candidate population or committee relationship census is established.",
            "Linked originals and other API collections remain outside this release.",
        ],
        "recordIdentity": "source candidate_id within this query observation; no cross-query reconciliation",
    },
)

__all__ = ["FEC_CANDIDATE_QUERY_PROFILE", "candidate_query_scope", "iter_retained_candidate_pages"]
