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

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache, partial
from typing import Any

from rulespec_artifacts import canonical_json_bytes, schema_bundle_digest

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.sources.fec.retained import (
    QueryAcquisition,
    exact_page_count,
    iter_pages,
    next_page,
    page_request,
    parse_response,
    query_scope,
    records_included,
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
_FIELDS = {"capture", "metadata", "embedded_bodies", "assets", "source_pointer"}


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


@dataclass(slots=True)
class _Traversal:
    count: int | None = None
    pages: int | None = None
    observed: int = 0

    def add(self, response: Mapping[str, Any], *, page_index: int) -> None:
        count, pages = exact_page_count(response, request=_request)
        if self.count is None:
            self.count, self.pages = count, pages
        if (count, pages) != (self.count, self.pages) or response["page"] != page_index + 1:
            raise ValueError("FEC filing query count or page inventory changed")
        for row in response["results"]:
            _classify(row)
            self.observed += 1

    def finish(self) -> None:
        if self.count is None or self.count != self.observed:
            raise ValueError("FEC filing observations differ from the publisher count")


def _record_scope(record, *, query_scope, page_window) -> None:
    index = _request(record["capture"]["requestUrl"])[1] - 1
    if not 0 <= index < len(query_scope["captures"]) or record["capture"] != query_scope["captures"][index]:
        raise ValueError("FEC filing observation falls outside its selected capture")


def _wrap(record: Mapping[str, Any], *, schema_digest: str) -> dict[str, Any]:
    return {
        "fieldDiagnostics": [],
        "record": dict(record),
        "schemaDigest": schema_digest,
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "scopeId": SCOPE_ID,
        "sourceRecordId": record["metadata"]["sub_id"],
    }


_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"urn:spicy-docs:schema:{SCHEMA_NAME}:{SCHEMA_VERSION}",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_FIELDS),
    "properties": {
        "capture": {"type": "object"},
        "metadata": {
            "type": "object",
            "required": ["sub_id"],
            "properties": {
                "sub_id": {"type": "string", "pattern": "^[0-9]+$"},
                "file_number": {"type": ["integer", "null"]},
            },
        },
        "embedded_bodies": {"type": "array"},
        "assets": {"type": "array"},
        "source_pointer": {"type": "string", "pattern": "^/results/[0-9]+$"},
    },
    "x-spicy-record-order": [
        {
            "fieldPath": "/metadata/sub_id",
            "nullOrder": "forbidden",
            "tupleComparison": "utf16-code-unit",
            "valueType": "string",
        }
    ],
}


@cache
def _schema_digest() -> str:
    return schema_bundle_digest({SCHEMA_KEY: _SCHEMA})


@cache
def _schema_declaration() -> dict[str, str]:
    return {"schemaDigest": _schema_digest(), "schemaName": SCHEMA_NAME, "schemaVersion": SCHEMA_VERSION}


FEC_FILING_QUERY_PROFILE = SourceNativeProfile(
    name="Retained OpenFEC filing query",
    source_system_id=SOURCE_SYSTEM_ID,
    source_system_version="v1",
    acquisition_policy_id="urn:spicy-docs:acquisition:fec-retained-filing-query",
    acquisition_policy_version="1.0",
    scope_id=SCOPE_ID,
    source_schema_key=SCHEMA_KEY,
    source_schema=_SCHEMA,
    record_stem="fec-filing",
    max_traversals=1,
    source_state_scope="observed-crawl",
    traversal_acceptance="single-observed-traversal",
    acquisition_policy=lambda scope: {
        "initialQueryScope": _scope(scope),
        "strategy": "replay-pinned-exact-count-filing-query",
        "coverageLimits": [
            "Only the pinned processed-filings query and its explicit publisher filters are covered.",
            "A requested-empty query is an observed answer, not proof that an original filing does not exist.",
            "No frozen publisher snapshot, full filing population or complete amendment history is established.",
            "Original filing bytes and linked documents remain separately acquired inputs.",
        ],
        "recordIdentity": "source sub_id within this query observation; no amendment selection",
        "decimalRepresentation": "exact decimal strings; source JSON bytes retain original numbers",
    },
    validate_query_scope=_scope,
    parse_page_response=partial(parse_response, request=_request),
    next_page=next_page,
    traversal_check=_Traversal,
    classify_record=_classify,
    wrap_record=_wrap,
    record_digest=lambda record: "sha256:" + hashlib.sha256(canonical_json_bytes(dict(record))).hexdigest(),
    rendition_rows=lambda record: (),
    source_schema_declaration=_schema_declaration,
    source_schema_digest=_schema_digest,
    validate_record_scope=_record_scope,
    records_included=records_included,
    acquisition_check=QueryAcquisition,
    page_window=lambda request: (_request(request), request)[1],
)


__all__ = ["FEC_FILING_QUERY_PROFILE", "filing_query_scope", "iter_retained_filing_pages"]
