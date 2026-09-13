"""Publish retained, explicitly selected OpenFEC committee census responses.

Call ``committee_census_scope(captures)`` for ``SourceNativeReleaseBuild`` and
pass ``iter_retained_committee_pages(captures, blob_source=...)`` to the existing
``SourceNativeReleasePublisher(FEC_COMMITTEE_CENSUS_PROFILE, ...)``. Each capture
pins ``requestUrl``, ``observedAt``, ``responseSha256`` and ``byteSize``; optional
``resolvedUrl``, ``mediaType`` and ``via`` preserve the acquisition description.

Evidence contains the exact JSON bytes plus that capture description. Replay
derives every record and body pointer from those bytes. The published ``record``
contains ``capture`` and the existing ``split_record`` result: full ``metadata``
apart from lifted body fields, ``embedded_bodies``, ``assets``, and a source JSON
pointer. Decimal numbers use exact decimal strings, as in the FEC raw-reader CLI;
their original JSON type and spelling remain in the retained response.

This first profile requires one complete, exactly counted API traversal ordered
by committee ID. Completeness is limited to the pinned requests and their source
filters. It establishes neither a frozen publisher snapshot nor historical FEC
coverage. No request is made here, and linked files remain unrequested.
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
    MAX_CAPTURES,  # noqa: F401 -- existing public constant
    exact_page_count,
    iter_pages,
    page_request,
    parse_response,
    query_scope,
)
from spicy_docs.sources.fec.retained import QueryAcquisition as _Acquisition
from spicy_docs.sources.fec.retained import RetainedPage as RetainedCommitteePage  # noqa: F401
from spicy_docs.sources.fec.retained import next_page as _next
from spicy_docs.sources.fec.retained import records_included as _included

SOURCE_SYSTEM_ID = "https://api.open.fec.gov/v1/committees/"
SCHEMA_NAME = "fec-committee-observation"
SCHEMA_VERSION = "1.0"
SCHEMA_KEY = "schemas/fec-committee-observation-1.0.json"
SCOPE_ID = "fec-retained-committee-census"
_request = partial(page_request, endpoint=SOURCE_SYSTEM_ID, order_by="committee_id")
committee_census_scope = partial(query_scope, request=_request)
iter_retained_committee_pages = partial(iter_pages, request=_request)
_parse = partial(parse_response, request=_request)
_RECORD_FIELDS = {"capture", "metadata", "embedded_bodies", "assets", "source_pointer"}


def _scope(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {"captures"}:
        raise ValueError("FEC census scope fields differ")
    return committee_census_scope(value["captures"])


@dataclass(slots=True)
class _Traversal:
    count: int | None = None
    pages: int | None = None
    observed: int = 0
    last_id: str | None = None

    def add(self, response: Mapping[str, Any], *, page_index: int) -> None:
        count, pages = exact_page_count(response, request=_request)
        if self.count is None:
            self.count, self.pages = count, pages
        if count != self.count or pages != self.pages or response["page"] != page_index + 1:
            raise ValueError("FEC census counts or page inventory changed during traversal")
        for row in response["results"]:
            record = _classify(row)
            identity = record["metadata"]["committee_id"]
            if self.last_id is not None and identity <= self.last_id:
                raise ValueError("FEC census committee IDs repeat or cease increasing")
            self.last_id = identity
            self.observed += 1

    def finish(self) -> None:
        if self.count is None or self.observed != self.count:
            raise ValueError("FEC census records differ from its publisher count")


def _classify(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS or not isinstance(value["metadata"], Mapping):
        raise ValueError("FEC committee observation fields differ")
    identity = value["metadata"].get("committee_id")
    if not isinstance(identity, str) or re.fullmatch(r"C[0-9]{8}", identity) is None:
        raise ValueError("FEC committee observation lacks a source committee ID")
    return dict(value)


def _record_scope(record, *, query_scope, page_window) -> None:
    # Request filters, including cycle selection, are publisher controls rather
    # than inferred historical coverage of each current committee metadata row.
    index = _request(record["capture"]["requestUrl"])[1] - 1
    if not 0 <= index < len(query_scope["captures"]) or record["capture"] != query_scope["captures"][index]:
        raise ValueError("FEC committee observation falls outside its selected capture")


def _wrap(record: Mapping[str, Any], *, schema_digest: str) -> dict[str, Any]:
    return {
        "fieldDiagnostics": [],
        "record": dict(record),
        "schemaDigest": schema_digest,
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "scopeId": SCOPE_ID,
        "sourceRecordId": record["metadata"]["committee_id"],
    }


_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:spicy-docs:schema:fec-committee-observation:1.0",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_RECORD_FIELDS),
    "properties": {
        "capture": {"type": "object"},
        "metadata": {
            "type": "object",
            "required": ["committee_id"],
            "properties": {"committee_id": {"type": "string", "pattern": "^C[0-9]{8}$"}},
        },
        "embedded_bodies": {"type": "array"},
        "assets": {"type": "array"},
        "source_pointer": {"type": "string", "pattern": "^/results/[0-9]+$"},
    },
    "x-spicy-record-order": [
        {
            "fieldPath": "/metadata/committee_id",
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


FEC_COMMITTEE_CENSUS_PROFILE = SourceNativeProfile(
    name="Retained OpenFEC committee census",
    source_system_id=SOURCE_SYSTEM_ID,
    source_system_version="v1",
    acquisition_policy_id="urn:spicy-docs:acquisition:fec-retained-committee-census",
    acquisition_policy_version="1.0",
    scope_id=SCOPE_ID,
    source_schema_key=SCHEMA_KEY,
    source_schema=_SCHEMA,
    record_stem="fec-committee",
    max_traversals=1,
    source_state_scope="observed-crawl",
    traversal_acceptance="single-observed-traversal",
    acquisition_policy=lambda scope: {
        "initialQueryScope": _scope(scope),
        "strategy": "replay-pinned-exact-count-committee-id-traversal",
        "coverageLimits": [
            "Only the pinned requests and their explicit publisher filters are covered.",
            "One observed traversal establishes no frozen publisher snapshot or historical FEC completeness.",
            "Linked originals and other API collections remain outside this release.",
        ],
        "decimalRepresentation": "exact decimal strings; source JSON bytes retain original numbers",
    },
    validate_query_scope=_scope,
    parse_page_response=_parse,
    next_page=_next,
    traversal_check=_Traversal,
    classify_record=_classify,
    wrap_record=_wrap,
    record_digest=lambda record: "sha256:" + hashlib.sha256(canonical_json_bytes(dict(record))).hexdigest(),
    rendition_rows=lambda record: (),
    source_schema_declaration=_schema_declaration,
    source_schema_digest=_schema_digest,
    validate_record_scope=_record_scope,
    records_included=_included,
    acquisition_check=_Acquisition,
    page_window=lambda request: (_request(request), request)[1],
)


__all__ = ["FEC_COMMITTEE_CENSUS_PROFILE", "committee_census_scope", "iter_retained_committee_pages"]
