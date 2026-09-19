"""Locate and prove one GovInfo package body from its package id, offline.

A package id is the publisher's own address for a committee report, hearing
transcript, Congressional Record issue, congressional document, directory or
bill text. Congress.gov route URLs carry these ids as their file stems, so a
caller that has a route has a package id. The Record's split days mean a date
alone is not one: 2026-01-03 can publish ``CREC-2026-01-03-v172`` beside
``-v171``, so the suffix is part of the id and never inferred.

Source rules, each measured on 2026-09-19 (receipts in the fixture README):

- Body renditions are keyless at ``www.govinfo.gov/content/pkg/{id}/{folder}/
  {id}.{extension}``; summary and MODS are keyed at ``api.govinfo.gov``.
- The folder is not the format name: text is served from ``text/{id}.txt`` and
  HTML from ``html/{id}.htm``.
- Not every package offers every format. CRPT/CHRG/CDOC offer HTML and PDF,
  CREC offers PDF, CDIR offers PDF and text, BILLS offers HTML, PDF and XML.
  A format a package does not offer redirects to ``/error``, which answers
  HTTP 200 with the publisher's 44,165-byte "Page Not Found" page. A 200 that
  is not the requested object is a refusal with its bytes retained, never data
  and never absence.
- The package MODS states the offered renditions as ``location/url`` elements
  with ``access="raw object"``, and those statements agreed exactly, in both
  directions, with what the keyless routes served for every package measured.
  The summary's ``download`` block does not: it lists no body rendition at all
  for CRPT, CHRG and CDOC, and spells the BILLS HTML rendition ``txtLink``.
  So the offered set is read from MODS, and the summary's links are kept as
  evidence with nothing derived from them.
- A body carries no machine-readable package id (the CRPT-119hrpt1 HTML body
  never spells it), unlike a Federal Register granule's ``[FR Doc No: ...]``.
  Identity is therefore the locator the request named, the summary's
  ``packageId``, the MODS ``accessId``, the MODS rendition URL for the chosen
  format, and the error-page exclusion -- four publisher statements about the
  one URL whose bytes were retained.

For package id length ``I``, summary bytes ``S``, MODS bytes ``M`` and body
bytes ``B``: parsing and locators are ``O(I)``; summary validation is ``O(S)``;
MODS validation is ``O(M)``; body validation is ``O(B)`` time and ``O(I)``
auxiliary space. Every parser requires a positive byte bound. These helpers
make no network requests and write no files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from spicy_docs.reading.json_input import load_decimal_json
from spicy_docs.sources.congress.bill_status import BILL_TYPES
from spicy_docs.sources.govinfo.discovery import API
from spicy_docs.sources.govinfo.error_page import check_not_error_page
from spicy_docs.sources.govinfo.mods import MODS_NAMESPACE, GovInfoModsError, parse_govinfo_mods
from spicy_docs.transport.source_acquirer import check_final_url, check_payload

CONTENT = "https://www.govinfo.gov"
MAX_PACKAGE_ID = 128
_RAW_OBJECT = "raw object"
_MODS_URL = f"{{{MODS_NAMESPACE}}}url"
_CONGRESS = r"[1-9][0-9]*"
_NUMBER = r"[1-9][0-9]*"
# A hearing jacket is an opaque printing number, so leading zeros are kept.
_JACKET = r"[0-9]+"
# Longest first, then alphabetically: hconres must win over hr, whatever order
# the frozenset iterates in, so the compiled pattern is the same every run.
_BILL_TYPE = "|".join(sorted(BILL_TYPES, key=lambda name: (-len(name), name)))
_DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
_GRAMMARS: dict[str, tuple[re.Pattern[str], str]] = {
    "CRPT": (re.compile(rf"(?P<congress>{_CONGRESS})(?P<type>hrpt|srpt|erpt)(?P<number>{_NUMBER})"), "119hrpt1"),
    "CHRG": (re.compile(rf"(?P<congress>{_CONGRESS})(?P<type>hhrg|shrg|jhrg)(?P<number>{_JACKET})"), "119hhrg64242"),
    "CDOC": (re.compile(rf"(?P<congress>{_CONGRESS})(?P<type>hdoc|sdoc|tdoc)(?P<number>{_NUMBER})"), "119tdoc2"),
    "CREC": (re.compile(rf"(?P<date>{_DATE})(?:-(?P<suffix>[vi]{_NUMBER}))?"), "2026-01-02 or 2019-01-03-v164"),
    "CDIR": (re.compile(rf"(?P<date>{_DATE})"), "2026-02-20"),
    "BILLS": (
        re.compile(rf"(?P<congress>{_CONGRESS})(?P<type>{_BILL_TYPE})(?P<number>{_NUMBER})(?P<version>[a-z][a-z0-9]*)"),
        "119hr1enr",
    ),
}


class GovInfoBodySourceError(ValueError):
    """GovInfo evidence does not prove the requested package body."""


@dataclass(frozen=True, slots=True)
class BodyFormat:
    """One keyless rendition: its folder, file extension and accepted media types."""

    name: str
    folder: str
    extension: str
    media_types: tuple[str, ...]


#: The grammar: every rendition this module can address. The order callers
#: should ask for them in is ``BODY_PREFERENCE`` below.
PACKAGE_BODY_FORMATS: dict[str, BodyFormat] = {
    "htm": BodyFormat("htm", "html", "htm", ("text/html",)),
    "xml": BodyFormat("xml", "xml", "xml", ("application/xml", "text/xml")),
    "txt": BodyFormat("txt", "text", "txt", ("text/plain",)),
    "pdf": BodyFormat("pdf", "pdf", "pdf", ("application/pdf",)),
}

#: The one sealed body preference for every GovInfo caller: structure first,
#: page images last.
#:
#: The ruling this seals, verbatim: *"shouldn't we prefer xml? and accept pdf
#: as a final fallback?"* Before it, each caller carried its own order and
#: stopped early -- the bill family asked for ``("xml", "txt")`` and the
#: committee-report transform for ``("txt", "htm", "xml")`` -- so a package
#: offered only as PDF got no body at all, and two callers disagreed about
#: what the same publisher offers. One constant, one order, everywhere.
#:
#: XML is first because it is the only rendition that states the document's
#: own structure. PDF is last because it is a rendering, not a text stream,
#: and the measurement below says what that costs. Measured 2026-09-19 on
#: three real committee reports, each in the rendition it offers and in its
#: own PDF (receipts and per-package numbers in
#: ``docs/sources/govinfo-bodies.md``, "Why PDF is last"):
#:
#: - **Words split in half.** PyMuPDF's page text carries 1,863 and 1,894
#:   mid-word print wraps on CRPT-113srpt77 and CRPT-113hrpt135, which
#:   ``gpo_normalize`` rejoins only on a gutter-numbered document -- and a
#:   committee report never is one. The same packages' ``htm`` rendition
#:   carries 32 and 47 hyphens, and every sampled one is a real compound word
#:   (``man-made``, ``long-standing``), not a print wrap.
#: - **Table rows destroyed.** 841 and 190 appropriations account rows keep
#:   their label, leader dots and amount on one line in ``htm``; 0 and 3 do
#:   in the PDF text, which emits the label and its amount as separate lines
#:   in column order.
#: - **No font cue to buy back.** GPO sets section headings in the body face
#:   at body size: only 89 and 16 lines are bold against 297 and 201 heading
#:   lines the report-block parser matches, and only 15 and 12 matched lines
#:   carry any font cue at all. Reading PyMuPDF spans would label the table
#:   body font, not the headings, and would still have to rebuild rows from
#:   bounding boxes -- which the ``htm`` rendition already hands over joined.
#:
#: ``htm`` before ``txt`` is not a measured ranking: no package offers both
#: (CRPT/CHRG/CDOC offer htm and pdf, CDIR offers txt and pdf, BILLS offers
#: htm, xml and pdf), so the two never compete. They are ordered by the same
#: structure-first rule, since markup can only add to what plain text states.
BODY_PREFERENCE: tuple[str, ...] = ("xml", "htm", "txt", "pdf")

_FORMAT_BY_EXTENSION = {body_format.extension: name for name, body_format in PACKAGE_BODY_FORMATS.items()}
_PACKAGE_RENDITION = re.compile(
    rf"{re.escape(CONTENT)}/content/pkg/(?P<package>[^/]+)/[^/]+/[^/]+\.(?P<extension>[A-Za-z0-9]+)"
)


@dataclass(frozen=True, slots=True)
class PackageIdentity:
    """One parsed package id; every part is the publisher's own spelling."""

    package_id: str
    collection: str
    congress: int | None = None
    document_type: str | None = None
    number: str | None = None
    issue_date: str | None = None
    issue_suffix: str | None = None
    version: str | None = None


@dataclass(frozen=True, slots=True)
class PackageSummary:
    """The keyed summary's own statement about one package."""

    identity: PackageIdentity
    collection_code: str
    date_issued: str | None
    last_modified: str | None
    title: str | None
    #: Every ``download`` link as the publisher spelled it, ``(name, url)``,
    #: repeated names included. Evidence, not a statement of what is fetchable.
    download_links: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PackageModsIdentity:
    """The MODS accessIds and the renditions the publisher says it offers."""

    identity: PackageIdentity
    access_ids: tuple[str, ...]
    collection_code: str | None
    #: Formats whose stated rendition URL is exactly this module's locator.
    offered_formats: tuple[str, ...]
    #: ``(format, url)`` for a rendition of this package in a supported file
    #: type at an address this module does not derive: the publisher and this
    #: module disagree about where that format lives.
    moved_renditions: tuple[tuple[str, str], ...]
    #: ``(displayLabel, url)`` for every other raw-object rendition, verbatim.
    other_renditions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PackageBodyIdentity:
    """A body proved against its locator, media type and the publisher's error page."""

    identity: PackageIdentity
    format: str
    media_type: str
    final_url: str
    byte_size: int


def _checked_bytes(payload: object, max_bytes: object, *, label: str) -> bytes:
    """This family's spelling of the shared bounded-evidence rule.

    No GovInfo route here can mean an empty response: a package that is not
    there redirects or answers 404, so zero bytes is a refusal, not absence.
    """
    return check_payload(
        payload, max_bytes, label=f"GovInfo {label}", error_type=GovInfoBodySourceError, allow_empty=False
    )


def _checked_date(value: str, collection: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise GovInfoBodySourceError(f"{collection} package id date is not a calendar date") from error
    if parsed.isoformat() != value:
        raise GovInfoBodySourceError(f"{collection} package id date is not canonical")
    return value


def parse_package_id(package_id: object) -> PackageIdentity:
    """Parse one package id under its collection's grammar, or refuse it by name.

    The grammar is strict on purpose, and the refusal names what was expected.
    A ``published`` walk scoped to one collection also returns ids belonging to
    neighboring collections -- ``ERP-2009`` states ``collectionCode`` ``ERP``
    and ``GPO-J6-REPORT`` states ``GPO`` (79 of 1,681 CDOC-scoped and 3 of
    3,000 CRPT-scoped ids sampled on 2026-09-19). Those are other collections
    with other addresses, so they are refused here rather than guessed at.
    """
    if not isinstance(package_id, str) or not package_id:
        raise GovInfoBodySourceError("package id must be a nonempty string")
    if len(package_id) > MAX_PACKAGE_ID:
        raise GovInfoBodySourceError(f"package id exceeds {MAX_PACKAGE_ID} characters")
    collection, separator, remainder = package_id.partition("-")
    if not separator or collection not in _GRAMMARS:
        supported = ", ".join(sorted(_GRAMMARS))
        raise GovInfoBodySourceError(f"package id collection is unsupported; expected one of {supported}")
    grammar, example = _GRAMMARS[collection]
    match = grammar.fullmatch(remainder)
    if match is None:
        raise GovInfoBodySourceError(
            f"{collection} package id does not match its grammar; expected {collection}-{example}"
        )
    parts = match.groupdict()
    issue_date = parts.get("date")
    return PackageIdentity(
        package_id=package_id,
        collection=collection,
        congress=int(parts["congress"]) if parts.get("congress") else None,
        document_type=parts.get("type"),
        number=parts.get("number"),
        issue_date=_checked_date(issue_date, collection) if issue_date else None,
        issue_suffix=parts.get("suffix"),
        version=parts.get("version"),
    )


def _identity(value: PackageIdentity | str) -> PackageIdentity:
    return value if isinstance(value, PackageIdentity) else parse_package_id(value)


def _format(name: object) -> BodyFormat:
    if not isinstance(name, str) or name not in PACKAGE_BODY_FORMATS:
        offered = ", ".join(PACKAGE_BODY_FORMATS)
        raise GovInfoBodySourceError(f"body format must be one of {offered}")
    return PACKAGE_BODY_FORMATS[name]


def package_body_locator(package: PackageIdentity | str, format: str) -> str:
    """Return the keyless rendition locator in ``O(I)`` time."""
    identity = _identity(package)
    body_format = _format(format)
    package_id = identity.package_id
    return f"{CONTENT}/content/pkg/{package_id}/{body_format.folder}/{package_id}.{body_format.extension}"


def package_summary_locator(package: PackageIdentity | str) -> str:
    """Return the keyed summary locator; the credential travels as a header."""
    return f"{API}/packages/{_identity(package).package_id}/summary"


def package_mods_locator(package: PackageIdentity | str) -> str:
    """Return the keyed package MODS locator; the credential travels as a header."""
    return f"{API}/packages/{_identity(package).package_id}/mods"


def validate_package_summary(
    body: bytes,
    *,
    package: PackageIdentity | str,
    final_url: str,
    max_bytes: int,
) -> PackageSummary:
    """Prove the summary states the requested ``packageId`` and keep its download links.

    The links are kept as the publisher spelled them and nothing is derived
    from them: they address the API's own content routes, three collections
    list no body rendition at all while serving HTML and PDF, and BILLS spells
    its HTML rendition ``txtLink``. The offered set comes from the MODS.
    """
    identity = _identity(package)
    exact = _checked_bytes(body, max_bytes, label="package summary")
    check_final_url(
        final_url,
        package_summary_locator(identity),
        error_type=GovInfoBodySourceError,
        message="GovInfo summary final URL differs from the requested locator",
    )
    document = load_decimal_json(exact, source="GovInfo package summary", error_type=GovInfoBodySourceError)
    if not isinstance(document, dict):
        raise GovInfoBodySourceError("GovInfo package summary is not a JSON object")
    if document.get("packageId") != identity.package_id:
        raise GovInfoBodySourceError("GovInfo summary packageId differs from the requested package")
    collection_code = document.get("collectionCode")
    if not isinstance(collection_code, str) or collection_code != identity.collection:
        raise GovInfoBodySourceError("GovInfo summary collectionCode differs from the requested collection")
    download = document.get("download")
    if download is not None and not isinstance(download, dict):
        raise GovInfoBodySourceError("GovInfo summary download block is not a JSON object")
    links: list[tuple[str, str]] = []
    for name, value in sorted((download or {}).items()):
        # A link can repeat under one name: GPO-J6-REPORT states five jpegLink
        # entries as a list. Each stays under its own name; anything that is
        # not a URL string is an anomaly this block cannot state.
        for url in value if isinstance(value, list) else [value]:
            if not isinstance(url, str):
                raise GovInfoBodySourceError("GovInfo summary download link is not a URL string")
            links.append((name, url))
    return PackageSummary(
        identity=identity,
        collection_code=collection_code,
        date_issued=_text(document.get("dateIssued")),
        last_modified=_text(document.get("lastModified")),
        title=_text(document.get("title")),
        download_links=tuple(links),
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _package_rendition_format(url: str, identity: PackageIdentity) -> str | None:
    """Name the format of a rendition of this package that sits somewhere else.

    The file extension names the format, because the folder is exactly what
    disagrees. ``None`` means the URL is not this package's content address in
    a supported file type, so it says nothing about where a format lives.
    """
    match = _PACKAGE_RENDITION.fullmatch(url)
    if match is None or match["package"] != identity.package_id:
        return None
    return _FORMAT_BY_EXTENSION.get(match["extension"])


def validate_package_mods(
    body: bytes,
    *,
    package: PackageIdentity | str,
    final_url: str,
    max_bytes: int,
    max_elements: int = 200_000,
) -> PackageModsIdentity:
    """Prove every package-level ``accessId`` and read the renditions it states.

    Only the root's own ``extension`` children are read; a constituent's
    accessId names a granule, not this package. A rendition counts as offered
    when its stated URL is exactly this module's locator for a supported
    format, so the publisher's statement and the derived address must agree.

    The renditions that do not match are separated, because they mean
    different things. One at another address for this package in a supported
    file type -- BILLS states its USLM rendition at ``uslm/{id}.xml`` -- is a
    disagreement about where a format lives, and the caller can see the address
    the publisher gave. Anything else (another package, another file type,
    another host) is recorded verbatim and means nothing about this fetch.
    """
    identity = _identity(package)
    exact = _checked_bytes(body, max_bytes, label="package MODS")
    check_final_url(
        final_url,
        package_mods_locator(identity),
        error_type=GovInfoBodySourceError,
        message="GovInfo MODS final URL differs from the requested locator",
    )
    try:
        parsed = parse_govinfo_mods(exact, max_bytes=max_bytes, max_elements=max_elements)
    except GovInfoModsError as error:
        raise GovInfoBodySourceError(f"GovInfo package MODS is unreadable: {error}") from error
    root = parsed.package
    access_ids = tuple(element.text.strip() for element in root.fields("extension", "accessId"))
    if not access_ids:
        raise GovInfoBodySourceError("GovInfo package MODS states no accessId")
    if any(value != identity.package_id for value in access_ids):
        raise GovInfoBodySourceError("GovInfo MODS accessId differs from the requested package")
    codes = {element.text.strip() for element in root.fields("extension", "collectionCode")}
    if codes and codes != {identity.collection}:
        raise GovInfoBodySourceError("GovInfo MODS collectionCode differs from the requested collection")
    locators = {package_body_locator(identity, name): name for name in PACKAGE_BODY_FORMATS}
    offered: list[str] = []
    moved: list[tuple[str, str]] = []
    other: list[tuple[str, str]] = []
    for location in root.fields("location"):
        for element in location.findall(_MODS_URL):
            if element.attribute("access") != _RAW_OBJECT:
                continue
            url = element.text.strip()
            name = locators.get(url)
            if name is not None:
                if name not in offered:
                    offered.append(name)
                continue
            elsewhere = _package_rendition_format(url, identity)
            if elsewhere is None:
                other.append((element.attribute("displayLabel") or "", url))
            else:
                moved.append((elsewhere, url))
    return PackageModsIdentity(
        identity=identity,
        access_ids=access_ids,
        collection_code=next(iter(codes), None),
        offered_formats=tuple(offered),
        moved_renditions=tuple(moved),
        other_renditions=tuple(other),
    )


def validate_package_body(
    body: bytes,
    *,
    package: PackageIdentity | str,
    format: str,
    content_type: str | None,
    final_url: str,
    max_bytes: int,
) -> PackageBodyIdentity:
    """Prove a bounded body against its locator, media type and native magic.

    The body itself names no package, so the locator is the identity: the
    client refuses redirects, so a response at this URL is this package's
    rendition or it is the error page, which is refused here.
    """
    identity = _identity(package)
    body_format = _format(format)
    exact = _checked_bytes(body, max_bytes, label="package body")
    # The error page is refused first so a response that landed on it says so,
    # rather than reporting a URL mismatch the caller cannot interpret.
    check_not_error_page(
        exact,
        final_url,
        error_type=GovInfoBodySourceError,
        message="govinfo returned its HTTP-200 error page, not the requested package body",
    )
    check_final_url(
        final_url,
        package_body_locator(identity, format),
        error_type=GovInfoBodySourceError,
        message="GovInfo body final URL differs from the requested locator",
    )
    media_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if media_type not in body_format.media_types:
        raise GovInfoBodySourceError(f"GovInfo body Content-Type is not {body_format.name} for the requested format")
    if body_format.name == "pdf" and not exact.startswith(b"%PDF-"):
        raise GovInfoBodySourceError("GovInfo PDF body does not begin with %PDF-")
    return PackageBodyIdentity(
        identity=identity,
        format=body_format.name,
        media_type=media_type,
        final_url=final_url,
        byte_size=len(exact),
    )


__all__ = [
    "BODY_PREFERENCE",
    "PACKAGE_BODY_FORMATS",
    "BodyFormat",
    "GovInfoBodySourceError",
    "PackageBodyIdentity",
    "PackageIdentity",
    "PackageModsIdentity",
    "PackageSummary",
    "package_body_locator",
    "package_mods_locator",
    "package_summary_locator",
    "parse_package_id",
    "validate_package_body",
    "validate_package_mods",
    "validate_package_summary",
]
