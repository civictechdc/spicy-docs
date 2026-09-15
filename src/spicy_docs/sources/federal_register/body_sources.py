"""Derive Federal Register body locators and validate response identity offline.

Source rules:
- body_html_url paths have sibling XML and text paths.
- GovInfo granules use publication date and printed document number. Check the
  [FR Doc No: ...] marker because a missing granule can return HTTP 200.
- A FederalRegister.gov split suffix may differ from the printed marker.
- Resolve synthetic X numbers through issue MODS start pages while preserving
  the original source identity.

body_acquisition prefers publisher XML, then the chosen GovInfo route after
XML 404/410. body_xml validates XML identity. DocSpec owns dataset selection;
SpicySearch Validation owns text agreement. Timing is not an identity rule.

For URL length U, granule bytes B, and MODS bytes M: locator time and output space are O(U);
granule validation is O(B) time and O(U) auxiliary space; MODS resolution is
O(M) time and O(D + A) auxiliary space, with XML depth D and largest retained
start/accessId text A. Both parsers require a positive byte bound. These helpers
make no network requests and write no files.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import urlsplit
from xml.parsers import expat

_BODY_HTML_PATH = re.compile(
    r"^/documents/full_text/html/"
    r"(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/"
    r"(?P<document_number>[A-Za-z0-9.-]+)\.html$"
)
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$")
_SPLIT_DOCUMENT_NUMBER = re.compile(r"^(?P<base>(?:\d{2}|\d{4})-\d{1,6})-\d+$")
_SOFT_404_BODY_MARKER = re.compile(rb"govinfo\.gov/error", re.IGNORECASE)
_MODS_NAMESPACE = "http://www.loc.gov/mods/v3"


class FederalRegisterBodySourceError(ValueError):
    """Federal Register body-source evidence does not prove the named item."""


@dataclass(frozen=True, slots=True)
class FederalRegisterBodyLocators:
    """Source and derived locators, intentionally without preference order."""

    document_number: str
    publication_date: str
    publisher_body_html_url: str
    publisher_text_url: str
    publisher_xml_url: str
    govinfo_granule_url: str
    govinfo_mods_url: str


@dataclass(frozen=True, slots=True)
class GovInfoGranuleIdentity:
    """The requested source identity and the exact printed marker that proved it."""

    access_id: str
    marker_document_number: str
    match_kind: Literal["exact-source", "split-base", "resolved-access-id"]
    publication_date: str
    source_document_number: str


@dataclass(frozen=True, slots=True)
class GovInfoModsResolution:
    """A start-page match that preserves the issue date and govinfo access ID."""

    access_id: str
    granule_url: str
    publication_date: str
    start_page: int


def _validated_source_id(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _SOURCE_ID.fullmatch(value):
        raise FederalRegisterBodySourceError(f"Federal Register {label} is invalid")
    return value


def _validated_publication_date(value: object) -> str:
    if not isinstance(value, str):
        raise FederalRegisterBodySourceError("Federal Register publication_date is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise FederalRegisterBodySourceError("Federal Register publication_date is invalid") from error
    if parsed.isoformat() != value:
        raise FederalRegisterBodySourceError("Federal Register publication_date is not canonical")
    return value


def _validated_max_bytes(payload: object, max_bytes: object, *, label: str) -> bytes:
    if not isinstance(payload, bytes):
        raise FederalRegisterBodySourceError(f"{label} must be exact bytes")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise FederalRegisterBodySourceError(f"{label} byte bound must be a positive integer")
    if len(payload) > max_bytes:
        raise FederalRegisterBodySourceError(f"{label} exceeds its {max_bytes}-byte bound")
    return payload


def govinfo_granule_locator(access_id: str, publication_date: str) -> str:
    """Return one canonical govinfo FR granule locator in ``O(U)`` time."""

    safe_access_id = _validated_source_id(access_id, label="govinfo accessId")
    safe_date = _validated_publication_date(publication_date)
    return f"https://www.govinfo.gov/content/pkg/FR-{safe_date}/html/{safe_access_id}.htm"


def govinfo_mods_locator(publication_date: str) -> str:
    """Return the canonical issue MODS locator in ``O(U)`` time."""

    safe_date = _validated_publication_date(publication_date)
    return f"https://www.govinfo.gov/metadata/pkg/FR-{safe_date}/mods.xml"


def _matching_document_marker(body: bytes, source_id: str) -> tuple[str, Literal["exact-source", "split-base"]] | None:
    """Both publisher text and GovInfo HTML print the same document header."""
    if f"[FR Doc No: {source_id}]".encode("ascii") in body:
        return source_id, "exact-source"
    split = _SPLIT_DOCUMENT_NUMBER.fullmatch(source_id)
    if split is not None:
        base = split.group("base")
        if f"[FR Doc No: {base}]".encode("ascii") in body:
            return base, "split-base"
    return None


def body_source_locators(record: Mapping[str, object]) -> FederalRegisterBodyLocators:
    """Derive all known body locators without choosing a DocSpec candidate.

    The source-stated HTML locator is cross-checked against the record's date
    and document number before its sibling paths are derived.  This fixes the
    old global-string-replacement behavior, which could manufacture a plausible
    URL from a locator for a different document.
    """

    document_number = _validated_source_id(
        record.get("document_number"),
        label="document_number",
    )
    publication_date = _validated_publication_date(record.get("publication_date"))
    body_html_url = record.get("body_html_url")
    if not isinstance(body_html_url, str):
        raise FederalRegisterBodySourceError("Federal Register body_html_url is invalid")
    parsed = urlsplit(body_html_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.federalregister.gov"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise FederalRegisterBodySourceError("Federal Register body_html_url is not canonical")
    match = _BODY_HTML_PATH.fullmatch(parsed.path)
    if match is None:
        raise FederalRegisterBodySourceError("Federal Register body_html_url path is invalid")
    locator_date = "-".join((match.group("year"), match.group("month"), match.group("day")))
    if locator_date != publication_date:
        raise FederalRegisterBodySourceError("Federal Register body_html_url publication date differs from the record")
    if match.group("document_number") != document_number:
        raise FederalRegisterBodySourceError("Federal Register body_html_url document number differs from the record")

    prefix = (
        "https://www.federalregister.gov/documents/full_text/"
        f"{{carrier}}/{publication_date.replace('-', '/')}/{document_number}"
    )
    return FederalRegisterBodyLocators(
        document_number=document_number,
        publication_date=publication_date,
        publisher_body_html_url=body_html_url,
        publisher_text_url=prefix.format(carrier="text") + ".txt",
        publisher_xml_url=prefix.format(carrier="xml") + ".xml",
        govinfo_granule_url=govinfo_granule_locator(document_number, publication_date),
        govinfo_mods_url=govinfo_mods_locator(publication_date),
    )


def validate_govinfo_granule(
    body: bytes,
    *,
    source_document_number: str,
    publication_date: str,
    access_id: str,
    final_url: str,
    max_bytes: int,
) -> GovInfoGranuleIdentity:
    """Prove a bounded govinfo body against its URL and printed FR number.

    ``access_id`` equals ``source_document_number`` for the ordinary path.  It
    differs only after an independently parsed MODS start-page match.  In that
    case the body must print the resolved access ID; merely being nonempty is
    not enough.  This closes the old alternate-granule validation gap.
    """

    exact_body = _validated_max_bytes(body, max_bytes, label="govinfo granule")
    if not exact_body:
        raise FederalRegisterBodySourceError("govinfo granule is empty")
    source_id = _validated_source_id(
        source_document_number,
        label="document_number",
    )
    resolved_id = _validated_source_id(access_id, label="govinfo accessId")
    safe_date = _validated_publication_date(publication_date)
    expected_url = govinfo_granule_locator(resolved_id, safe_date)
    parsed_final = urlsplit(final_url)
    if parsed_final.scheme == "https" and parsed_final.netloc == "www.govinfo.gov" and parsed_final.path == "/error":
        raise FederalRegisterBodySourceError("govinfo returned its HTTP-200 soft-404")
    if final_url != expected_url:
        raise FederalRegisterBodySourceError("govinfo granule final URL differs from the requested locator")
    if _SOFT_404_BODY_MARKER.search(exact_body):
        raise FederalRegisterBodySourceError("govinfo returned its HTTP-200 soft-404")

    if resolved_id != source_id:
        marker = f"[FR Doc No: {resolved_id}]".encode("ascii")
        if marker not in exact_body:
            raise FederalRegisterBodySourceError("govinfo granule does not carry the resolved access ID marker")
        return GovInfoGranuleIdentity(
            access_id=resolved_id,
            marker_document_number=resolved_id,
            match_kind="resolved-access-id",
            publication_date=safe_date,
            source_document_number=source_id,
        )

    matched = _matching_document_marker(exact_body, source_id)
    if matched is not None:
        marker_number, match_kind = matched
        return GovInfoGranuleIdentity(
            access_id=resolved_id,
            marker_document_number=marker_number,
            match_kind=match_kind,
            publication_date=safe_date,
            source_document_number=source_id,
        )
    raise FederalRegisterBodySourceError("govinfo granule does not carry the requested document marker")


def _xml_name(value: str) -> tuple[str | None, str]:
    if "}" not in value:
        return None, value
    namespace, local_name = value.rsplit("}", 1)
    return namespace, local_name


class _GovInfoModsHandler:
    """Streaming start-page resolver with memory bounded by XML depth and text."""

    def __init__(self, target_start_page: int) -> None:
        self.target_start_page = str(target_start_page)
        self.depth = 0
        self.element_path: list[tuple[str, bool]] = []
        self.constituent_depth: int | None = None
        self.target_start_seen = False
        self.access_id: str | None = None
        self.access_id_count = 0
        self.capture_depth: int | None = None
        self.capture_kind: Literal["start", "accessId"] | None = None
        self.capture_text: list[str] = []
        self.match: str | None = None

    def start(self, name: str, attributes: Mapping[str, str]) -> None:
        self.depth += 1
        namespace, source_local_name = _xml_name(name)
        if self.depth == 1 and (namespace, source_local_name) != (_MODS_NAMESPACE, "mods"):
            raise FederalRegisterBodySourceError("govinfo MODS XML root or namespace differs")
        local_name = source_local_name if namespace == _MODS_NAMESPACE else ""
        self.element_path.append((local_name, local_name == "extent" and attributes.get("unit") == "pages"))
        if local_name == "relatedItem" and attributes.get("type") == "constituent":
            if self.constituent_depth is not None:
                raise FederalRegisterBodySourceError("govinfo MODS nests constituent records ambiguously")
            self.constituent_depth = self.depth
            self.target_start_seen = False
            self.access_id = None
            self.access_id_count = 0
        is_page_start = (
            self.constituent_depth is not None
            and self.depth == self.constituent_depth + 3
            and self.element_path[self.constituent_depth][0] == "part"
            and self.element_path[self.constituent_depth + 1] == ("extent", True)
            and local_name == "start"
        )
        is_access_id = (
            self.constituent_depth is not None
            and self.depth == self.constituent_depth + 2
            and self.element_path[self.constituent_depth][0] == "extension"
            and local_name == "accessId"
        )
        if self.capture_kind is None and (is_page_start or is_access_id):
            self.capture_depth = self.depth
            self.capture_kind = "start" if is_page_start else "accessId"
            self.capture_text.clear()

    def data(self, value: str) -> None:
        if self.capture_kind is not None:
            self.capture_text.append(value)

    def end(self, name: str) -> None:
        namespace, source_local_name = _xml_name(name)
        local_name = source_local_name if namespace == _MODS_NAMESPACE else ""
        if self.capture_depth == self.depth and self.capture_kind is not None:
            value = "".join(self.capture_text).strip()
            if self.capture_kind == "start":
                self.target_start_seen = self.target_start_seen or value == self.target_start_page
            else:
                self.access_id_count += 1
                if value and self.access_id is None:
                    self.access_id = value
            self.capture_depth = None
            self.capture_kind = None
            self.capture_text.clear()
        if local_name == "relatedItem" and self.constituent_depth == self.depth:
            self._finish_constituent()
            self.constituent_depth = None
            self.target_start_seen = False
            self.access_id = None
            self.access_id_count = 0
        self.element_path.pop()
        self.depth -= 1

    def _finish_constituent(self) -> None:
        if not self.target_start_seen:
            return
        if self.access_id_count != 1 or self.access_id is None:
            raise FederalRegisterBodySourceError("govinfo MODS matching constituent has no single accessId")
        safe_id = _validated_source_id(self.access_id, label="MODS accessId")
        if self.match is not None:
            raise FederalRegisterBodySourceError("govinfo MODS has more than one constituent for the start page")
        self.match = safe_id


def resolve_govinfo_granule_from_mods(
    mods_bytes: bytes,
    *,
    publication_date: str,
    start_page: int,
    max_bytes: int,
) -> GovInfoModsResolution:
    """Resolve one synthetic publisher number through bounded issue MODS bytes.

    The parser visits each constituent once and refuses zero or multiple start
    page matches.  It neither fetches the issue nor chooses the resulting
    granule; it turns already captured source evidence into an exact locator.
    """

    exact_mods = _validated_max_bytes(mods_bytes, max_bytes, label="govinfo MODS")
    if not exact_mods:
        raise FederalRegisterBodySourceError("govinfo MODS is empty")
    if isinstance(start_page, bool) or not isinstance(start_page, int) or start_page <= 0:
        raise FederalRegisterBodySourceError("Federal Register start_page is invalid")
    safe_date = _validated_publication_date(publication_date)
    handler = _GovInfoModsHandler(start_page)
    parser = expat.ParserCreate(namespace_separator="}")
    parser.StartElementHandler = handler.start
    parser.EndElementHandler = handler.end
    parser.CharacterDataHandler = handler.data

    def refuse_doctype(*_values: object) -> None:
        raise FederalRegisterBodySourceError("govinfo MODS DTD declarations are forbidden")

    parser.StartDoctypeDeclHandler = refuse_doctype
    try:
        parser.Parse(exact_mods, True)
    except FederalRegisterBodySourceError:
        raise
    except expat.ExpatError as error:
        raise FederalRegisterBodySourceError("govinfo MODS XML is malformed") from error
    if handler.match is None:
        raise FederalRegisterBodySourceError("govinfo MODS has no constituent for the start page")
    return GovInfoModsResolution(
        access_id=handler.match,
        granule_url=govinfo_granule_locator(handler.match, safe_date),
        publication_date=safe_date,
        start_page=start_page,
    )


__all__ = [
    "FederalRegisterBodyLocators",
    "FederalRegisterBodySourceError",
    "GovInfoGranuleIdentity",
    "GovInfoModsResolution",
    "body_source_locators",
    "govinfo_granule_locator",
    "govinfo_mods_locator",
    "resolve_govinfo_granule_from_mods",
    "validate_govinfo_granule",
]
