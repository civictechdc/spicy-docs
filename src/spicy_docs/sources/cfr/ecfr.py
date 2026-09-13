"""Dated eCFR API sources and the separate latest GovInfo bulk title route."""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urlencode

from ._xml import IdentityXmlScan
from .models import (
    DEFAULT_MAX_BYTES,
    CfrSourceError,
    CfrXmlMetadata,
    EcfrSelection,
    EcfrTitle,
    EcfrTitles,
    _date,
    _limit,
    _title,
)


def ecfr_titles_locator() -> str:
    return "https://www.ecfr.gov/api/versioner/v1/titles.json"


def ecfr_xml_locator(selection: EcfrSelection) -> str:
    """Name an explicit date and scope without claiming availability."""
    if not isinstance(selection, EcfrSelection):
        raise CfrSourceError("selection must be an EcfrSelection")
    url = f"https://www.ecfr.gov/api/versioner/v1/full/{selection.date}/title-{selection.title}.xml"
    query = {
        key: value for key, value in (("part", selection.part), ("section", selection.section)) if value is not None
    }
    return url + ("?" + urlencode(query) if query else "")


def ecfr_bulk_xml_locator(title: int) -> str:
    """The bulk route is latest-only; its URL does not select an API date."""
    return f"https://www.govinfo.gov/bulkdata/ECFR/title-{_title(title)}/ECFR-title{title}.xml"


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CfrSourceError("eCFR JSON contains a duplicate field")
        result[key] = value
    return result


def parse_ecfr_titles(body: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> EcfrTitles:
    """Read the complete roster; currency and processing fields stay distinct."""
    _limit(max_bytes)
    if not isinstance(body, bytes) or not body or len(body) > max_bytes:
        raise CfrSourceError("eCFR titles must be nonempty bytes within max_bytes")
    try:
        root = json.loads(body, object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise CfrSourceError("eCFR titles JSON is malformed") from error
    if not isinstance(root, dict) or not isinstance(root.get("titles"), list) or not isinstance(root.get("meta"), dict):
        raise CfrSourceError("eCFR titles requires titles and meta")
    meta = root["meta"]
    if type(meta.get("import_in_progress")) is not bool:
        raise CfrSourceError("eCFR titles requires boolean meta.import_in_progress")
    as_of = _date(meta.get("date"))
    titles = []
    for row in root["titles"]:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
            raise CfrSourceError("eCFR title requires a literal name")
        number = _title(row.get("number"), allow_reserved=True)
        if type(row.get("reserved")) is not bool:
            raise CfrSourceError("eCFR title requires a boolean reserved field")
        processing = row.get("processing_in_progress")
        if processing is not None and type(processing) is not bool:
            raise CfrSourceError("eCFR title processing_in_progress must be boolean when present")
        dates = [row.get(field) for field in ("latest_amended_on", "latest_issue_date", "up_to_date_as_of")]
        for value in dates:
            if value is not None:
                _date(value)
        titles.append(
            EcfrTitle(
                number,
                row["name"],
                row["reserved"],
                dates[0],
                dates[1],
                dates[2],
                processing,
            )
        )
    if len(titles) != 50 or {title.number for title in titles} != set(range(1, 51)):
        raise CfrSourceError("eCFR titles must contain every title from 1 to 50 exactly once")
    return EcfrTitles(as_of, meta["import_in_progress"], tuple(titles))


_BULK = ("DLPSTEXTCLASS", "TEXT", "BODY", "ECFRBRWS")
_HEADER = ("DLPSTEXTCLASS", "HEADER", "FILEDESC")
_ID = (*_HEADER, "PUBLICATIONSTMT", "IDNO")
_BULK_DATE = (*_HEADER, "PUBLICATIONSTMT", "DATE")
_BULK_TITLE = (*_HEADER, "TITLESTMT", "TITLE")
_BULK_HEAD = (*_BULK, "DIV1", "HEAD")


def _check_title_heading(value: str | None, title: int) -> None:
    if value is None:
        return
    match = re.match(r"\s*Title\s+([0-9]+)(?=\s|[—–:-]|$)", value)
    if match is not None and int(match[1]) != title:
        raise CfrSourceError("eCFR native title heading differs from the request")


class _EcfrScan(IdentityXmlScan):
    def __init__(self, title: int, selection: EcfrSelection | None) -> None:
        super().__init__(
            {
                ("ECFR", "AMDDATE"),
                ("ECFR", "DATE"),
                ("ECFR", "DIV1", "HEAD"),
                ("DIV5", "HEAD"),
                ("DIV8", "HEAD"),
                _ID,
                _BULK_DATE,
                _BULK_TITLE,
                _BULK_HEAD,
                (*_BULK, "AMDDATE"),
            }
        )
        self.title = title
        self.selection = selection
        self.native_title: int | None = None
        self.native_part: str | None = None
        self.native_section: str | None = None
        self.title_count = 0
        self.section_count = 0
        self.bulk_blocks = 0
        self.block_titles = 0
        self.block_body = False
        self.volume_dates: list[str] = []
        self._head_tail = ""

    def _hierarchy(self, attributes: dict[str, str]) -> None:
        value = attributes.get("hierarchy_metadata")
        if value is None or self.selection is None:
            return
        if len(value) > 8192:
            raise CfrSourceError("eCFR hierarchy metadata is too large")
        try:
            # Retained API part roots escape the JSON quotes twice; child
            # sections escape them once. No source text is rewritten.
            metadata = json.loads(
                value if value.lstrip().startswith('{"') else unescape(value), object_pairs_hook=_object
            )
        except (ValueError, RecursionError) as error:
            raise CfrSourceError("eCFR hierarchy metadata is malformed") from error
        path = metadata.get("path") if isinstance(metadata, dict) else None
        match = (
            re.fullmatch(
                r"/on/(_SUBSTITUTE_DATE_|[0-9]{4}-[0-9]{2}-[0-9]{2})/title-([0-9]+)/(part|section)-([^/]+)", path
            )
            if isinstance(path, str)
            else None
        )
        if match is None:
            raise CfrSourceError("eCFR hierarchy path is unsupported")
        date, title, scope, number = match.groups()
        if title != str(self.title) or (date != "_SUBSTITUTE_DATE_" and date != self.selection.date):
            raise CfrSourceError("eCFR hierarchy metadata contradicts the requested title or date")
        expected = self.selection.part if scope == "part" else self.selection.section
        if expected is not None and number != expected:
            raise CfrSourceError("eCFR hierarchy metadata contradicts the requested scope")
        native_scope = {"PART": "part", "SECTION": "section"}.get(attributes.get("TYPE", ""))
        if native_scope is not None and (
            native_scope != scope or number != attributes.get("N", "").strip().removeprefix("§").strip()
        ):
            raise CfrSourceError("eCFR hierarchy metadata contradicts its native scope")

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        path = self.path
        self._hierarchy(attributes)
        if tag == "HEAD":
            self._head_tail = ""
        if len(path) == 1:
            allowed = {"DLPSTEXTCLASS"} if self.selection is None else {"ECFR", "DIV5", "DIV8"}
            if tag not in allowed:
                raise CfrSourceError("eCFR XML has the wrong source root")
            if self.selection is not None:
                expected = "ECFR" if self.selection.part is None else "DIV5"
                if tag != expected and not (self.selection.section is not None and tag == "DIV8"):
                    raise CfrSourceError("eCFR XML root differs from the requested scope")
        elif tag in {"ECFR", "DLPSTEXTCLASS"}:
            raise CfrSourceError("eCFR XML contains a nested document root")
        if path == _BULK:
            self.bulk_blocks += 1
            self.block_titles = 0
            self.block_body = False
        if path == _ID and attributes.get("TYPE") != "title":
            raise CfrSourceError("bulk eCFR header IDNO must identify the title")
        if self.selection is not None and path == ("ECFR", "VOLUME") and "AMDDATE" in attributes:
            if len(self.volume_dates) >= 128:
                raise CfrSourceError("eCFR XML has too many volume amendment dates")
            self.volume_dates.append(attributes["AMDDATE"])
        native_type = attributes.get("TYPE")
        if native_type == "TITLE":
            if tag != "DIV1":
                raise CfrSourceError("eCFR native TITLE must use DIV1")
            if self.selection is None:
                if path != (*_BULK, "DIV1"):
                    raise CfrSourceError("bulk eCFR title appears outside ECFRBRWS")
                self.block_titles += 1
                # Bulk DIV1 N is a volume coordinate, not the title number.
            else:
                if path != ("ECFR", "DIV1") or attributes.get("N") != str(self.title):
                    raise CfrSourceError("eCFR native title differs from the request")
                self.native_title = self.title
            self.title_count += 1
        if self.selection is not None and native_type == "PART":
            if tag != "DIV5":
                raise CfrSourceError("eCFR native PART must use DIV5")
            if self.selection.part is not None:
                if attributes.get("N") != self.selection.part:
                    raise CfrSourceError("eCFR native part differs from the request")
                self.native_part = attributes["N"]
        if native_type == "SECTION":
            if tag != "DIV8":
                raise CfrSourceError("eCFR native SECTION must use DIV8")
            self.section_count += 1
            number = attributes.get("N", "").strip().removeprefix("§").strip()
            if self.selection is not None and self.selection.section is not None:
                if number != self.selection.section:
                    raise CfrSourceError("eCFR native section differs from the request")
                self.native_section = number
        if len(path) == 1 and tag in {"DIV5", "DIV8"} and native_type != {"DIV5": "PART", "DIV8": "SECTION"}[tag]:
            raise CfrSourceError("eCFR subset root lacks its native scope")
        if (
            tag.lower() == "img"
            and attributes.get("src", "").strip()
            and self._source_scope()
            and any(attrs.get("TYPE") in {"SECTION", "APPENDIX"} for _tag, attrs in self.stack)
        ):
            self.body_found = self.block_body = True

    def _source_scope(self) -> bool:
        path = self.path
        if self.selection is None:
            return path[: len(_BULK)] == _BULK and any(attrs.get("TYPE") == "TITLE" for _tag, attrs in self.stack)
        if self.selection.part is None:
            return path[:2] == ("ECFR", "DIV1")
        return path[0] in {"DIV5", "DIV8"}

    def observe_text(self, text: str) -> None:
        if not text.strip():
            return
        in_source = self._source_scope()
        native_scope = any(attrs.get("TYPE") in {"SECTION", "APPENDIX"} for _tag, attrs in self.stack)
        content = any(tag.upper() in {"P", "PSPACE", "FP", "TD", "ENTRY", "ENT"} for tag, _attrs in self.stack)
        if self.stack[-1][0] == "HEAD":
            self._head_tail = (self._head_tail + text)[-32:]
        reserved = self.stack[-1][0] == "HEAD" and "[Reserved]" in self._head_tail
        if in_source and ((native_scope and content) or reserved):
            self.body_found = self.block_body = True

    def observe_end(self, tag: str) -> None:
        if self.path == _BULK and (self.block_titles < 1 or not self.block_body):
            raise CfrSourceError("each bulk eCFR block must contain title structure and source content")


def validate_ecfr_xml(
    body: bytes,
    *,
    selection: EcfrSelection,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> CfrXmlMetadata:
    """Validate native scope; the API date is supported by the exact response URL."""
    if final_url != ecfr_xml_locator(selection):
        raise CfrSourceError("eCFR response URL differs from the requested date and scope")
    scan = _EcfrScan(selection.title, selection)
    scan.read(body, max_bytes)
    if not scan.body_found or (selection.part is None and scan.title_count != 1):
        raise CfrSourceError("eCFR XML lacks the requested title or source content")
    if selection.part is not None and scan.root == "DIV5" and scan.native_part is None:
        raise CfrSourceError("eCFR XML lacks the requested part")
    if selection.section is not None and (scan.native_section is None or scan.section_count != 1):
        raise CfrSourceError("eCFR XML must contain exactly the requested section")
    _check_title_heading(scan.field(("ECFR", "DIV1", "HEAD")), selection.title)
    basis = ["title:native" if scan.native_title is not None else "title:request-url", "date:request-url"]
    if selection.part is not None:
        basis.append("part:native" if scan.native_part is not None else "part:request-url")
    if selection.section is not None:
        basis.append("section:native")
    return CfrXmlMetadata(
        "ecfr-api",
        scan.native_title,
        None,
        scan.native_part,
        scan.native_section,
        scan.root,
        scan.field(("ECFR", "DIV1", "HEAD")) if selection.part is None else scan.field((scan.root, "HEAD")),
        scan.field(("ECFR", "DATE")),
        None,
        tuple(scan.values.get(("ECFR", "AMDDATE"), [])) + tuple(scan.volume_dates),
        tuple(basis),
    )


def validate_ecfr_bulk_xml(
    body: bytes,
    *,
    title: int,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> CfrXmlMetadata:
    """Validate the latest bulk title without equating it to a dated API response."""
    if final_url != ecfr_bulk_xml_locator(title):
        raise CfrSourceError("bulk eCFR response URL differs from the requested title")
    scan = _EcfrScan(title, None)
    scan.read(body, max_bytes)
    number = scan.field(_ID, required=True)
    if number is None or number.strip() != str(title):
        raise CfrSourceError("bulk eCFR native title differs from the request")
    if scan.bulk_blocks < 1 or not scan.body_found:
        raise CfrSourceError("bulk eCFR XML lacks its source body")
    for heading in [scan.field(_BULK_TITLE), *scan.values.get(_BULK_HEAD, [])]:
        _check_title_heading(heading, title)
    return CfrXmlMetadata(
        "ecfr-bulk",
        title,
        None,
        None,
        None,
        scan.root,
        scan.field(_BULK_TITLE),
        scan.field(_BULK_DATE),
        None,
        tuple(scan.values.get((*_BULK, "AMDDATE"), [])),
        ("title:native", "currency:latest-route"),
    )
