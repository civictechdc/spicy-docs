"""Publish one pinned, complete OpenFEC processed-filings query observation.

Use ``filing_query_scope(captures)`` in ``SourceNativeReleaseBuild`` and pass
``iter_retained_filing_pages(captures, blob_source=...)`` to the existing
publisher with ``FEC_FILING_QUERY_PROFILE``. Capture descriptors and evidence
ZIPs have the same shape as the committee profile. No network access is needed.

Each returned row retains its native ``sub_id`` as ``sourceRecordId`` and the
complete metadata/body-pointer split. File numbers, original URLs, amendment
fields, nulls and unknown fields remain unmodified source metadata. Decimal
values use exact strings; original JSON numeric types remain in the evidence.

This is the processed API's observed answer to one explicit query, not an
inventory of original filings or complete amendment history. A requested-empty
answer produces a release with pinned query evidence and zero records. No row
is invented for an omitted file number; compare requested filters with returned
metadata if per-file dispositions are needed. Overlapping queries belong in
separate releases; this source layer chooses no preferred amendment or report.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import partial
from typing import Any

from spicy_docs.sources.fec.query_profile import (
    RECORD_FIELDS,
    CountedTraversal,
    observation_schema,
    retained_query_profile,
)
from spicy_docs.sources.fec.retained import (
    iter_pages,
    page_request,
    query_scope,
)

SOURCE_SYSTEM_ID = "https://api.open.fec.gov/v1/filings/"
SCHEMA_NAME = "fec-filing-observation"
# 1.2 admits source-negative numbers observed in F13; sub_id still supplies identity.
# Earlier qualification releases keep their original schemas and input pins.
SCHEMA_VERSION = "1.2"
SCHEMA_KEY = f"schemas/{SCHEMA_NAME}-{SCHEMA_VERSION}.json"
SCOPE_ID = "fec-retained-filing-query"
_request = partial(page_request, endpoint=SOURCE_SYSTEM_ID)
filing_query_scope = partial(query_scope, request=_request)
iter_retained_filing_pages = partial(iter_pages, request=_request)
_FIELDS = RECORD_FIELDS


def _scope(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {"captures"}:
        raise ValueError("FEC filing query scope fields differ")
    return filing_query_scope(value["captures"])


def _classify(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS or not isinstance(value["metadata"], Mapping):
        raise ValueError("FEC filing observation fields differ")
    metadata = value["metadata"]
    if not isinstance(metadata.get("sub_id"), str) or re.fullmatch(r"[0-9]+", metadata["sub_id"]) is None:
        raise ValueError("FEC filing observation lacks its native processed-record sub_id")
    # File numbers may be negative, null or absent in official responses.
    # Preserve them as metadata; a direct filter still needs a known match.
    number = metadata.get("file_number")
    if number is not None and type(number) is not int:
        raise ValueError("FEC filing observation has an invalid file number")
    # This filter names the returned field directly. Other source filters may
    # select through associations, so their meaning stays with the publisher.
    pairs, _ = _request(value["capture"]["requestUrl"])
    selected = [number for key, number in pairs if key == "file_number"]
    if selected and str(number) not in selected:
        raise ValueError("FEC filing result falls outside its explicit file-number selection")
    return dict(value)


_Traversal = partial(CountedTraversal, request=_request, classify=_classify)


_SCHEMA = observation_schema(
    name=SCHEMA_NAME,
    version=SCHEMA_VERSION,
    identity="sub_id",
    metadata={
        "type": "object",
        "required": ["sub_id"],
        "properties": {
            "sub_id": {"type": "string", "pattern": "^[0-9]+$"},
            "file_number": {"type": ["integer", "null"]},
        },
    },
)


FEC_FILING_QUERY_PROFILE = retained_query_profile(
    name="Retained OpenFEC filing query",
    endpoint=SOURCE_SYSTEM_ID,
    schema_name=SCHEMA_NAME,
    schema_version=SCHEMA_VERSION,
    schema_key=SCHEMA_KEY,
    schema=_SCHEMA,
    scope_id=SCOPE_ID,
    record_stem="fec-filing",
    identity="sub_id",
    request=_request,
    scope=_scope,
    classify=_classify,
    traversal=_Traversal,
    policy={
        "strategy": "replay-pinned-exact-count-filing-query",
        "coverageLimits": [
            "Only the pinned processed-filings query and its explicit publisher filters are covered.",
            "A requested-empty query is an observed answer, not proof that an original filing does not exist.",
            "No frozen publisher snapshot, full filing population or complete amendment history is established.",
            "Original filing bytes and linked documents remain separately acquired inputs.",
        ],
        "recordIdentity": "source sub_id within this query observation; no amendment selection",
    },
)


__all__ = ["FEC_FILING_QUERY_PROFILE", "filing_query_scope", "iter_retained_filing_pages"]
