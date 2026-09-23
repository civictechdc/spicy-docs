"""Regulations.gov query scope, completeness checks, and acquisition policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from spicy_docs.reading.media_types import media_type_policy
from spicy_docs.sources.regulations_gov.definitions import (
    _ASCII_ID,
    COMMENT_COLLECTION,
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    EVIDENCE_PACK_TYPE,
    MAX_EVIDENCE_PACK_OBJECTS,
    MAX_EVIDENCE_PACK_RAW_BYTES,
    MAX_OBJECT_BYTES,
    MAX_QUERY_DAYS,
    MAX_TRAVERSALS,
    MirrulationsWindow,
    RegulationsGovSourceError,
)
from spicy_docs.sources.regulations_gov.records import (
    _data_attributes,
    _optional_record_date,
    _record_date,
)


def _date_scope(
    value: Mapping[str, Any],
    *,
    from_field: str,
    through_field: str,
) -> dict[str, Any]:
    if set(value) != {"agencies", from_field, through_field}:
        raise RegulationsGovSourceError("Regulations.gov query scope fields differ")
    agencies = value.get("agencies")
    if (
        not isinstance(agencies, list)
        or not agencies
        or any(not isinstance(agency, str) or _ASCII_ID.fullmatch(agency) is None for agency in agencies)
        or agencies != sorted(set(agencies))
    ):
        raise RegulationsGovSourceError("Regulations.gov agencies must be nonempty, ASCII, sorted, and distinct")
    try:
        start = date.fromisoformat(str(value[from_field]))
        end = date.fromisoformat(str(value[through_field]))
    except ValueError as error:
        raise RegulationsGovSourceError("Regulations.gov query dates are invalid") from error
    if end < start:
        raise RegulationsGovSourceError("Regulations.gov query scope is reversed")
    if (end - start).days >= MAX_QUERY_DAYS:
        raise RegulationsGovSourceError(f"Regulations.gov query scope exceeds the {MAX_QUERY_DAYS}-day date bound")
    return {
        "agencies": list(agencies),
        from_field: start.isoformat(),
        through_field: end.isoformat(),
    }


def regulations_gov_document_query_scope(value: Mapping[str, Any]) -> dict[str, Any]:
    return _date_scope(
        value,
        from_field="publishedFrom",
        through_field="publishedThrough",
    )


def regulations_gov_docket_query_scope(value: Mapping[str, Any]) -> dict[str, Any]:
    return _date_scope(
        value,
        from_field="modifiedFrom",
        through_field="modifiedThrough",
    )


def regulations_gov_comment_query_scope(value: Mapping[str, Any]) -> dict[str, Any]:
    return _date_scope(
        value,
        from_field="postedFrom",
        through_field="postedThrough",
    )


def regulations_gov_next_page_url(
    response: Mapping[str, Any],
    *,
    seen_urls: set[str],
) -> None:
    del seen_urls
    if response.get("next_page_url") is not None:
        raise RegulationsGovSourceError("Mirrulations exact-object evidence cannot paginate")


@dataclass(slots=True)
class RegulationsGovTraversalCheck:
    observed_pages: int = 0

    def add(self, response: Mapping[str, Any], *, page_index: int) -> None:
        results = response.get("results")
        if (
            page_index != 0
            or not isinstance(results, list)
            or not 0 <= len(results) <= MAX_EVIDENCE_PACK_OBJECTS
            or response.get("count") != len(results)
        ):
            raise RegulationsGovSourceError("Mirrulations evidence-pack inventory differs")
        self.observed_pages += 1

    def finish(self) -> None:
        if self.observed_pages != 1:
            raise RegulationsGovSourceError("Mirrulations object window is incomplete")


def _pack_request(
    *,
    collection: str,
    agency: str,
    pack_index: int,
    terminal: bool,
) -> str:
    query = urlencode(
        {
            "agency": agency,
            "packIndex": str(pack_index),
            "terminal": "true" if terminal else "false",
        }
    )
    return f"mirrulations://regulations-gov/{collection}/pack?{query}"


def parse_mirrulations_request(value: str) -> MirrulationsWindow:
    parsed = urlparse(value)
    path = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "mirrulations"
        or parsed.netloc != "regulations-gov"
        or len(path) != 2
        or path[0] not in {COMMENT_COLLECTION, DOCUMENT_COLLECTION, DOCKET_COLLECTION}
        or path[1] != "pack"
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RegulationsGovSourceError("Mirrulations request key is invalid")
    collection, _ = path
    parameters = parse_qs(parsed.query, keep_blank_values=True)
    agency_values = parameters.get("agency", [])
    if len(agency_values) != 1 or _ASCII_ID.fullmatch(agency_values[0]) is None:
        raise RegulationsGovSourceError("Mirrulations request agency is invalid")
    agency = agency_values[0]
    if set(parameters) != {"agency", "packIndex", "terminal"} or any(
        len(values) != 1 for values in parameters.values()
    ):
        raise RegulationsGovSourceError("Mirrulations pack request fields differ")
    pack_index_text = parameters["packIndex"][0]
    terminal_text = parameters["terminal"][0]
    if not pack_index_text.isdigit() or terminal_text not in {"false", "true"}:
        raise RegulationsGovSourceError("Mirrulations pack request values are invalid")
    pack_index = int(pack_index_text)
    terminal = terminal_text == "true"
    if (
        _pack_request(
            collection=collection,
            agency=agency,
            pack_index=pack_index,
            terminal=terminal,
        )
        != value
    ):
        raise RegulationsGovSourceError("Mirrulations pack request is not canonical")
    return MirrulationsWindow(
        kind="pack",
        collection=collection,
        agency=agency,
        pack_index=pack_index,
        terminal=terminal,
    )


@dataclass(slots=True)
class MirrulationsAcquisitionCheck:
    """Validate one complete, bounded, strictly ordered source enumeration."""

    collection: str
    observed_agencies: list[str] = field(default_factory=list)
    observed_objects: int = 0
    current_agency: str | None = None
    next_pack_index: int = 0
    current_terminal: bool = True
    previous_key: str | None = None

    def add_window(
        self,
        response: Mapping[str, Any],
        *,
        page_window: object | None,
        records_included: bool,
        response_bytes: bytes,
    ) -> None:
        if not isinstance(page_window, MirrulationsWindow) or page_window.collection != self.collection:
            raise RegulationsGovSourceError("Mirrulations evidence request collection differs")
        del response_bytes
        if (
            response.get("_evidenceType") != EVIDENCE_PACK_TYPE
            or response.get("_collection") != self.collection
            or response.get("_agency") != page_window.agency
            or response.get("_packIndex") != page_window.pack_index
            or response.get("_terminal") is not page_window.terminal
            or records_included is not bool(response.get("results"))
        ):
            raise RegulationsGovSourceError("Mirrulations pack request and bytes differ")
        agency = page_window.agency
        if agency != self.current_agency:
            if self.current_agency is not None and not self.current_terminal:
                raise RegulationsGovSourceError("Mirrulations agency enumeration lacks a terminal pack")
            if self.observed_agencies and agency <= self.observed_agencies[-1]:
                raise RegulationsGovSourceError("Mirrulations enumeration agencies are not ASCII-sorted")
            if page_window.pack_index != 0:
                raise RegulationsGovSourceError("Mirrulations agency enumeration does not start at pack zero")
            self.observed_agencies.append(agency)
            self.current_agency = agency
            self.next_pack_index = 0
        elif self.current_terminal:
            raise RegulationsGovSourceError("Mirrulations agency enumeration continues after its terminal pack")
        if page_window.pack_index != self.next_pack_index:
            raise RegulationsGovSourceError("Mirrulations evidence packs are missing or reordered")
        entries = response.get("_objects")
        if not isinstance(entries, list):
            raise RegulationsGovSourceError("Mirrulations pack object inventory differs")
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise RegulationsGovSourceError("Mirrulations pack object inventory differs")
            key = entry.get("key")
            if (
                not isinstance(key, str)
                or not key.startswith(f"raw-data/{agency}/")
                or self.previous_key is not None
                and key <= self.previous_key
            ):
                raise RegulationsGovSourceError("Mirrulations object keys are not globally sorted and distinct")
            self.previous_key = key
            self.observed_objects += 1
        self.next_pack_index += 1
        self.current_terminal = page_window.terminal

    def finish(self, *, query_scope: Mapping[str, Any]) -> None:
        agencies = query_scope.get("agencies")
        if self.observed_agencies != agencies:
            raise RegulationsGovSourceError("Mirrulations enumeration does not cover exact agencies")
        if not self.current_terminal:
            raise RegulationsGovSourceError("Mirrulations enumeration is missing a terminal pack")


def _records_included(
    response: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
    collection: str,
) -> bool:
    if not isinstance(page_window, MirrulationsWindow) or page_window.collection != collection:
        raise RegulationsGovSourceError("Mirrulations page lacks a validated request")
    if (
        response.get("_evidenceType") != EVIDENCE_PACK_TYPE
        or response.get("_agency") != page_window.agency
        or response.get("_packIndex") != page_window.pack_index
        or response.get("_terminal") is not page_window.terminal
    ):
        raise RegulationsGovSourceError("Mirrulations pack request differs from its evidence")
    packed_records = response.get("_packedRecords")
    results = response.get("results")
    if not isinstance(packed_records, list) or not isinstance(results, list):
        raise RegulationsGovSourceError("Mirrulations evidence pack has no record inventory")
    expected_results: list[Mapping[str, Any]] = []
    for item in packed_records:
        if not isinstance(item, Mapping) or not isinstance(item.get("included"), bool):
            raise RegulationsGovSourceError("Mirrulations evidence-pack disposition differs")
        record = item.get("record")
        if not isinstance(record, Mapping):
            raise RegulationsGovSourceError("Mirrulations evidence pack has an invalid record")
        included = _record_in_scope(
            record,
            query_scope=query_scope,
            agency=page_window.agency,
            collection=collection,
        )
        if item["included"] is not included:
            raise RegulationsGovSourceError("Mirrulations evidence-pack disposition differs from the query scope")
        if included:
            expected_results.append(record)
    if results != expected_results:
        raise RegulationsGovSourceError("Mirrulations evidence-pack result inventory differs")
    return bool(expected_results)


def _record_in_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    agency: str,
    collection: str,
) -> bool:
    attributes = _data_attributes(record)
    record_agency = attributes.get("agencyId")
    if record_agency != agency:
        raise RegulationsGovSourceError("Mirrulations record agency differs from its object path")
    if record_agency not in query_scope["agencies"]:
        return False
    if collection == DOCUMENT_COLLECTION:
        value = _optional_record_date(attributes.get("postedDate"), "document postedDate")
        if value is None:
            # An undated document (2026-09-02: FMCSA-2007-0006-0015 and two
            # siblings publish postedDate: null) or one whose postedDate is
            # present but unparseable (2026-09-02: the FAA full-history
            # publish surfaced this) falls outside every date scope; §3
            # keeps it as evidence while it contributes no record.
            return False
        start = date.fromisoformat(str(query_scope["publishedFrom"]))
        end = date.fromisoformat(str(query_scope["publishedThrough"]))
    elif collection == DOCKET_COLLECTION:
        value = _record_date(attributes.get("modifyDate"), "docket modifyDate")
        start = date.fromisoformat(str(query_scope["modifiedFrom"]))
        end = date.fromisoformat(str(query_scope["modifiedThrough"]))
    else:
        value = _record_date(attributes.get("postedDate"), "comment postedDate")
        start = date.fromisoformat(str(query_scope["postedFrom"]))
        end = date.fromisoformat(str(query_scope["postedThrough"]))
    return start <= value <= end


def document_records_included(
    response: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> bool:
    return _records_included(
        response,
        query_scope=query_scope,
        page_window=page_window,
        collection=DOCUMENT_COLLECTION,
    )


def docket_records_included(
    response: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> bool:
    return _records_included(
        response,
        query_scope=query_scope,
        page_window=page_window,
        collection=DOCKET_COLLECTION,
    )


def comment_records_included(
    response: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> bool:
    return _records_included(
        response,
        query_scope=query_scope,
        page_window=page_window,
        collection=COMMENT_COLLECTION,
    )


def _validate_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
    collection: str,
) -> None:
    if not isinstance(page_window, MirrulationsWindow) or page_window.collection != collection:
        raise RegulationsGovSourceError("Mirrulations page lacks a validated request")
    if not _record_in_scope(
        record,
        query_scope=query_scope,
        agency=page_window.agency,
        collection=collection,
    ):
        raise RegulationsGovSourceError("Regulations.gov record falls outside its query scope")


def validate_document_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    _validate_record_scope(
        record,
        query_scope=query_scope,
        page_window=page_window,
        collection=DOCUMENT_COLLECTION,
    )


def validate_docket_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    _validate_record_scope(
        record,
        query_scope=query_scope,
        page_window=page_window,
        collection=DOCKET_COLLECTION,
    )


def validate_comment_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    _validate_record_scope(
        record,
        query_scope=query_scope,
        page_window=page_window,
        collection=COMMENT_COLLECTION,
    )


def _acquisition_policy(
    query_scope: Mapping[str, Any],
    *,
    validator: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    collection: str,
) -> dict[str, Any]:
    # Group by /data/id and keep the greatest normalized UTC instant.
    # Documents use modifyDate, then postedDate; dockets/comments use modifyDate.
    # Documents/dockets collapse equal digests; documents also allow differences
    # in declared volatile fields. Other tied differences refuse, as do all comment
    # repeats. Count and retain every discard. See source_issued_version.
    order_by = (
        "coalesce(/data/attributes/modifyDate, /data/attributes/postedDate) DESC NULLS LAST"
        if collection == DOCUMENT_COLLECTION
        else "/data/attributes/modifyDate DESC NULLS LAST"
    )
    return {
        "collection": collection,
        "coverageLimits": [
            "Membership follows one live listing of the requested agencies and collection, with dates applied afterward.",
            "The built-in transport fetches each listed object with its ETag as an IfMatch precondition.",
            "Individual object pins do not establish one frozen version of the whole listing or publisher.",
        ],
        "dateSelection": "after-full-agency-object-acquisition",
        "evidence": "bounded-zip-packs-of-listed-metadata-and-exact-object-bytes",
        "initialQueryScope": dict(validator(query_scope)),
        "maxObjectsPerEvidencePack": MAX_EVIDENCE_PACK_OBJECTS,
        "maxQueryDays": MAX_QUERY_DAYS,
        "maxRawBytesPerEvidencePack": MAX_EVIDENCE_PACK_RAW_BYTES,
        "maxObjectBytes": MAX_OBJECT_BYTES,
        "maxTraversals": MAX_TRAVERSALS,
        "observationSelection": {
            "groupBy": "/data/id",
            "orderBy": order_by,
            "tieDisposition": "refuse-differing-record-digest-at-normalized-instant",
        },
        "strategy": "complete-mirrulations-source-enumeration",
        "renditions": (
            {"positions": "original-file-format-indexes", "mediaType": media_type_policy()}
            if collection != DOCKET_COLLECTION
            else {"selection": "none-stated-by-docket-profile"}
        ),
    }


def document_acquisition_policy(query_scope: Mapping[str, Any]) -> dict[str, Any]:
    return _acquisition_policy(
        query_scope,
        validator=regulations_gov_document_query_scope,
        collection=DOCUMENT_COLLECTION,
    )


def docket_acquisition_policy(query_scope: Mapping[str, Any]) -> dict[str, Any]:
    return _acquisition_policy(
        query_scope,
        validator=regulations_gov_docket_query_scope,
        collection=DOCKET_COLLECTION,
    )


def comment_acquisition_policy(query_scope: Mapping[str, Any]) -> dict[str, Any]:
    return _acquisition_policy(
        query_scope,
        validator=regulations_gov_comment_query_scope,
        collection=COMMENT_COLLECTION,
    )
