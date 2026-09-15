"""Shared publication wiring for source-specific retained OpenFEC queries.

Each caller supplies its identity checks, traversal rules and coverage statement.
This helper adds no endpoint discovery, filtering or interpretation of records.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache, partial

from rulespec_artifacts import canonical_json_bytes, schema_bundle_digest

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.sources.fec.retained import (
    QueryAcquisition,
    RequestCheck,
    exact_page_count,
    next_page,
    parse_response,
    records_included,
)

RECORD_FIELDS = {"capture", "metadata", "embedded_bodies", "assets", "source_pointer"}


@dataclass(slots=True)
class CountedTraversal:
    """Check exact page counts; the publisher independently refuses repeated IDs."""

    request: RequestCheck
    classify: Callable
    count: int | None = None
    pages: int | None = None
    observed: int = 0

    def add(self, response: Mapping, *, page_index: int) -> None:
        count, pages = exact_page_count(response, request=self.request)
        if self.count is None:
            self.count, self.pages = count, pages
        if (count, pages) != (self.count, self.pages) or response["page"] != page_index + 1:
            raise ValueError("FEC query count or page inventory changed")
        for row in response["results"]:
            self.classify(row)
            self.observed += 1

    def finish(self) -> None:
        if self.count is None or self.count != self.observed:
            raise ValueError("FEC observations differ from the publisher count")


def observation_schema(*, name: str, version: str, identity: str, metadata: dict) -> dict:
    """Describe the shared metadata/body split with source-owned identity fields."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:spicy-docs:schema:{name}:{version}",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(RECORD_FIELDS),
        "properties": {
            "capture": {"type": "object"},
            "metadata": metadata,
            "embedded_bodies": {"type": "array"},
            "assets": {"type": "array"},
            "source_pointer": {"type": "string", "pattern": "^/results/[0-9]+$"},
        },
        "x-spicy-record-order": [
            {
                "fieldPath": f"/metadata/{identity}",
                "nullOrder": "forbidden",
                "tupleComparison": "utf16-code-unit",
                "valueType": "string",
            }
        ],
    }


def retained_query_profile(
    *,
    name,
    endpoint,
    schema_name,
    schema_version,
    schema_key,
    schema,
    scope_id,
    record_stem,
    identity,
    request,
    scope,
    classify,
    traversal,
    policy,
) -> SourceNativeProfile:
    """Wire the existing publisher without changing a source's sealed declarations."""

    @cache
    def schema_digest():
        return schema_bundle_digest({schema_key: schema})

    @cache
    def schema_declaration():
        return {"schemaDigest": schema_digest(), "schemaName": schema_name, "schemaVersion": schema_version}

    def record_scope(record, *, query_scope, page_window):
        index = request(record["capture"]["requestUrl"])[1] - 1
        if not 0 <= index < len(query_scope["captures"]) or record["capture"] != query_scope["captures"][index]:
            raise ValueError("FEC observation falls outside its selected capture")

    def wrap(record, *, schema_digest):
        return {
            "fieldDiagnostics": [],
            "record": dict(record),
            "schemaDigest": schema_digest,
            "schemaName": schema_name,
            "schemaVersion": schema_version,
            "scopeId": scope_id,
            "sourceRecordId": record["metadata"][identity],
        }

    return SourceNativeProfile(
        name=name,
        source_system_id=endpoint,
        source_system_version="v1",
        acquisition_policy_id=f"urn:spicy-docs:acquisition:{scope_id}",
        acquisition_policy_version="1.0",
        scope_id=scope_id,
        source_schema_key=schema_key,
        source_schema=schema,
        record_stem=record_stem,
        max_traversals=1,
        source_state_scope="observed-crawl",
        traversal_acceptance="single-observed-traversal",
        acquisition_policy=lambda value: {
            "initialQueryScope": scope(value),
            **copy.deepcopy(policy),
            "decimalRepresentation": "exact decimal strings; source JSON bytes retain original numbers",
        },
        validate_query_scope=scope,
        parse_page_response=partial(parse_response, request=request),
        next_page=next_page,
        traversal_check=traversal,
        classify_record=classify,
        wrap_record=wrap,
        record_digest=lambda record: "sha256:" + hashlib.sha256(canonical_json_bytes(dict(record))).hexdigest(),
        rendition_rows=lambda record: (),
        source_schema_declaration=schema_declaration,
        source_schema_digest=schema_digest,
        validate_record_scope=record_scope,
        records_included=records_included,
        acquisition_check=QueryAcquisition,
        page_window=lambda url: (request(url), url)[1],
    )
