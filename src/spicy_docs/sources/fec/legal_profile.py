"""Publish one complete retained legal-search query with an explicit source type.

Search rows retain native doc_id/type identity, nested document associations and
body pointers. A complete search answer is not a complete case file: detail JSON,
linked originals and interpretations remain separately selected inputs.
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
from spicy_docs.sources.fec.retained import iter_pages, parse_response, query_scope, request_pairs

SOURCE_SYSTEM_ID = "https://api.open.fec.gov/v1/legal/search/"
SCHEMA_NAME = "fec-legal-search-observation"
SCHEMA_VERSION = "1.0"
SCHEMA_KEY = f"schemas/{SCHEMA_NAME}-{SCHEMA_VERSION}.json"
SCOPE_ID = "fec-retained-legal-query"
LEGAL_TYPES = ("advisory_opinions", "murs", "admin_fines", "adrs")


def _request(url):
    pairs = request_pairs(url, endpoint=SOURCE_SYSTEM_ID)
    controls = {key: [value for name, value in pairs if name == key] for key in ("type", "hits_returned", "from_hit")}
    if len(controls["type"]) != 1 or controls["type"][0] not in LEGAL_TYPES:
        raise ValueError("FEC legal release requires one supported search type")
    if len(controls["hits_returned"]) != 1 or len(controls["from_hit"]) > 1:
        raise ValueError("FEC legal release requires explicit size and unambiguous offset controls")
    try:
        size = int(controls["hits_returned"][0])
        offset = int(controls["from_hit"][0]) if controls["from_hit"] else 0
    except ValueError as error:
        raise ValueError("FEC legal page size and offset must be integers") from error
    if (
        not 1 <= size <= 200
        or offset < 0
        or offset % size
        or any(key in {"page", "per_page"} or key.startswith("last_") for key, _ in pairs)
    ):
        raise ValueError("FEC legal query controls are outside the selected profile")
    return pairs, offset // size + 1


legal_query_scope = partial(query_scope, request=_request, page_parameter="from_hit")
iter_retained_legal_pages = partial(iter_pages, request=_request, page_parameter="from_hit")


def _scope(value):
    if set(value) != {"captures"}:
        raise ValueError("FEC legal query scope fields differ")
    return legal_query_scope(value["captures"])


def _classify(value):
    if not isinstance(value, Mapping) or set(value) != RECORD_FIELDS or not isinstance(value["metadata"], Mapping):
        raise ValueError("FEC legal observation fields differ")
    metadata = value["metadata"]
    pairs, _ = _request(value["capture"]["requestUrl"])
    selected = dict(pairs)["type"]
    if not isinstance(metadata.get("doc_id"), str) or not metadata["doc_id"].strip():
        raise ValueError("FEC legal observation lacks its native doc_id")
    if metadata.get("type") != selected or re.fullmatch(f"/{selected}/[0-9]+", value["source_pointer"]) is None:
        raise ValueError("FEC legal observation differs from its selected source type or result group")
    return dict(value)


def _count_page(response, *, request):
    pairs, page = request(response["capture"]["requestUrl"])
    controls = dict(pairs)
    pagination = response["pagination"]
    count = pagination.get("total_" + controls["type"])
    if type(count) is not int or count < 0:
        raise ValueError("FEC legal query requires a nonnegative publisher total")
    if "total_all" in pagination and (type(pagination["total_all"]) is not int or pagination["total_all"] != count):
        raise ValueError("FEC legal aggregate total differs from the selected source total")
    size = int(controls["hits_returned"])
    if len(response["results"]) != min(size, max(0, count - (page - 1) * size)):
        raise ValueError("FEC legal result count differs from its declared total and offset")
    return count, (count + size - 1) // size


_SCHEMA = observation_schema(
    name=SCHEMA_NAME,
    version=SCHEMA_VERSION,
    identity="doc_id",
    pointer_pattern="^/(" + "|".join(LEGAL_TYPES) + ")/[0-9]+$",
    metadata={
        "type": "object",
        "required": ["doc_id", "type"],
        "properties": {
            "doc_id": {"type": "string", "pattern": "\\S"},
            "type": {"enum": list(LEGAL_TYPES)},
        },
    },
)

FEC_LEGAL_QUERY_PROFILE = retained_query_profile(
    name="Retained OpenFEC legal search query",
    endpoint=SOURCE_SYSTEM_ID,
    schema_name=SCHEMA_NAME,
    schema_version=SCHEMA_VERSION,
    schema_key=SCHEMA_KEY,
    schema=_SCHEMA,
    scope_id=SCOPE_ID,
    record_stem="fec-legal-search",
    identity="doc_id",
    request=_request,
    scope=_scope,
    classify=_classify,
    traversal=partial(CountedTraversal, request=_request, classify=_classify, count_page=_count_page),
    parse_page=partial(parse_response, request=_request, mode="legal"),
    policy={
        "strategy": "replay-pinned-declared-total-legal-offset-query",
        "coverageLimits": [
            "Only one explicitly selected legal-search type and its pinned query observation are covered.",
            "Publisher totals, exact offset membership and unique doc_id values govern this search answer.",
            "Search summaries, citations, statuses and nested document associations remain source observations.",
            "Search completeness establishes neither complete case files nor a frozen publisher snapshot.",
            "Legal detail JSON, linked originals, rulemakings, statutes and other source collections remain separate inputs.",
        ],
        "recordIdentity": "native doc_id within the selected legal-search type; no prefix inference or case reconciliation",
    },
)

__all__ = ["FEC_LEGAL_QUERY_PROFILE", "iter_retained_legal_pages", "legal_query_scope"]
