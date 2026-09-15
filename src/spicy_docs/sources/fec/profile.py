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

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from spicy_docs.sources.fec.query_profile import RECORD_FIELDS, observation_schema, retained_query_profile
from spicy_docs.sources.fec.retained import (
    MAX_CAPTURES,  # noqa: F401 -- existing public constant
    exact_page_count,
    iter_pages,
    page_request,
    query_scope,
)
from spicy_docs.sources.fec.retained import RetainedPage as RetainedCommitteePage  # noqa: F401

SOURCE_SYSTEM_ID = "https://api.open.fec.gov/v1/committees/"
SCHEMA_NAME = "fec-committee-observation"
SCHEMA_VERSION = "1.0"
SCHEMA_KEY = "schemas/fec-committee-observation-1.0.json"
SCOPE_ID = "fec-retained-committee-census"
_request = partial(page_request, endpoint=SOURCE_SYSTEM_ID, order_by="committee_id")
committee_census_scope = partial(query_scope, request=_request)
iter_retained_committee_pages = partial(iter_pages, request=_request)
_RECORD_FIELDS = RECORD_FIELDS


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


_SCHEMA = observation_schema(
    name=SCHEMA_NAME,
    version=SCHEMA_VERSION,
    identity="committee_id",
    metadata={
        "type": "object",
        "required": ["committee_id"],
        "properties": {"committee_id": {"type": "string", "pattern": "^C[0-9]{8}$"}},
    },
)


FEC_COMMITTEE_CENSUS_PROFILE = retained_query_profile(
    name="Retained OpenFEC committee census",
    endpoint=SOURCE_SYSTEM_ID,
    schema_name=SCHEMA_NAME,
    schema_version=SCHEMA_VERSION,
    schema_key=SCHEMA_KEY,
    schema=_SCHEMA,
    scope_id=SCOPE_ID,
    record_stem="fec-committee",
    identity="committee_id",
    request=_request,
    scope=_scope,
    classify=_classify,
    traversal=_Traversal,
    policy={
        "strategy": "replay-pinned-exact-count-committee-id-traversal",
        "coverageLimits": [
            "Only the pinned requests and their explicit publisher filters are covered.",
            "One observed traversal establishes no frozen publisher snapshot or historical FEC completeness.",
            "Linked originals and other API collections remain outside this release.",
        ],
    },
)


__all__ = ["FEC_COMMITTEE_CENSUS_PROFILE", "committee_census_scope", "iter_retained_committee_pages"]
