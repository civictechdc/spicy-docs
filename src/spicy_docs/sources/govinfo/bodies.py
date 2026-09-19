"""Locate and prove one GovInfo package or granule body, offline.

A package id is the publisher's own address for a committee report, hearing
transcript, committee print, Congressional Record issue, congressional
document, directory or bill text. Congress.gov route URLs carry these ids as
their file stems, so a caller that has a route has a package id. The Record's
split days mean a date alone is not one: 2026-01-03 can publish
``CREC-2026-01-03-v172`` beside ``-v171``, so the suffix is part of the id and
never inferred.

A granule id names one constituent of a package -- one Record speech, one page
range -- and carries no address of its own: every granule locator addresses it
through its package's content path, the package id as the folder segment and
the granule id as the file stem (measured 2026-09-19 on CREC-2026-09-18's
granules). A granule's own summary and MODS state both its id and its host
package's, so membership is proved the same way a package proves its own
identity, not assumed from the URL a caller built.

Source rules, each measured on 2026-09-19 (receipts in the fixture README):

- Body renditions are keyless at ``www.govinfo.gov/content/pkg/{id}/{folder}/
  {id}.{extension}``; summary and MODS are keyed at ``api.govinfo.gov``.
- The folder is not the format name: text is served from ``text/{id}.txt`` and
  HTML from ``html/{id}.htm``.
- Not every package offers every format. CRPT/CHRG/CDOC offer HTML and PDF,
  CPRT offers HTML, PDF and XML, CREC offers PDF, CDIR offers PDF and text,
  BILLS offers HTML, PDF, XML and USLM. A format a package does not offer
  redirects to ``/error``, which answers
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
from spicy_docs.sources.govinfo.mods import MODS_NAMESPACE, GovInfoModsError, ModsRecord, parse_govinfo_mods
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
    # Verified on a real package summary 2026-09-19 (CPRT-118HPRT57104): the
    # chamber-plus-doctype token is spelled upper-case here, unlike CRPT's own
    # lower-case hrpt/srpt/erpt -- the two collections do not share a case
    # convention, so this is measured, not inferred from CRPT's shape.
    "CPRT": (re.compile(rf"(?P<congress>{_CONGRESS})(?P<type>HPRT|SPRT|JPRT)(?P<number>{_NUMBER})"), "118HPRT57104"),
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
    # United States Legislative Markup: a second, richer structured rendition
    # BILLS offers alongside its own xml -- same folder-not-format-name rule,
    # ``uslm/{id}.xml``, and the same media types, since GovInfo serves it as
    # plain XML (measured 2026-09-19, BILLS-119hconres11enr: content-type
    # application/xml). See ``extraction/body_text.py`` for why its text
    # derivation is the same markup reader as ``xml``, not a dedicated parser.
    "uslm": BodyFormat("uslm", "uslm", "xml", ("application/xml", "text/xml")),
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
#:
#: ``uslm`` sits right after ``xml``: it is the second structured rendition
#: (§B7, measured 2026-09-19 on BILLS-119hconres11enr), and BILLS offers both
#: on the same package, so an order was needed. XML wins the top slot because
#: every BILLS package that offers USLM offers XML too (both are Formatted-XML
#: siblings on the same publisher record), so nothing is lost by trying XML
#: first; USLM still outranks HTML and text, since it is markup over the same
#: structured source, not a plain-text reduction of it.
BODY_PREFERENCE: tuple[str, ...] = ("xml", "uslm", "htm", "txt", "pdf")

#: The granule counterpart of ``BODY_PREFERENCE``, for
#: ``GovInfoBodyAcquirer.acquire_granule``. Measured on CREC-2026-09-18 (§B2):
#: every one of its 11 granules states HTML and PDF, both through the granule's
#: own locator (``granule_body_locator``), never the whole-issue package's.
#: HTML wins because it is the Record's actual reading text; the package-level
#: PDF ``acquire(package_id)`` already reaches (CREC packages offer PDF alone,
#: see ``BODY_PREFERENCE`` above) stays available unchanged for a caller that
#: wants the whole issue rather than one granule.
GRANULE_BODY_PREFERENCE: tuple[str, ...] = ("htm", "pdf")

# uslm shares xml's file extension -- both are xml/{id}.xml-shaped, just in
# different folders -- so an extension alone cannot always name a rendition
# found at an unexpected folder (see _package_rendition_format). xml is kept
# as that fallback's answer for the shared extension, since it existed first
# and is the far more common of the two; setdefault leaves it untouched by
# uslm's later, colliding entry.
_FORMAT_BY_EXTENSION: dict[str, str] = {}
for _name, _body_format in PACKAGE_BODY_FORMATS.items():
    _FORMAT_BY_EXTENSION.setdefault(_body_format.extension, _name)
del _name, _body_format
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
class GranuleIdentity:
    """One granule id together with the package identity it was requested under.

    A granule carries no address of its own -- every locator reaches it
    through its package's content path -- so its identity is always this
    pair, never the granule id alone.
    """

    package: PackageIdentity
    granule_id: str


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
class GranuleSummary:
    """The keyed granule summary's own statement about one granule and its package.

    A granule summary states both ``packageId`` and ``granuleId`` directly --
    unlike a missing package, a granule that does not belong to the requested
    package answers HTTP 400, not 404 (measured 2026-09-19: a granule id from
    another day under CREC-2026-09-18, and that same real granule id requested
    under CREC-2026-09-17, both answer 400 ``invalid granuleId``), so this is
    read as an ordinary shape mismatch rather than a distinct refusal type.
    """

    identity: GranuleIdentity
    collection_code: str
    date_issued: str | None
    title: str | None
    download_links: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ModsBill:
    """One ``<bill>`` a package MODS names, in the publisher's own document order.

    ``context`` is the publisher's own priority marker (``PRIMARY``,
    ``OTHER``, ...), or the empty string when the publisher's ``<bill>``
    states none -- kept as a mention rather than dropped, since a ``<bill>``
    with no stated context is still evidence the MODS named it; dropping
    data silently is the wrong side of that choice. Document order is not
    priority order -- measured on CRPT-119hrpt1, whose MODS lists S. 5
    (``OTHER``), H. Res. 53 (``OTHER``), H. Res. 53 again (``PRIMARY``), then
    H.R. 471 (``OTHER``) -- so a caller wanting the bill a report is chiefly
    about reads ``PackageModsIdentity.primary_bill``, never ``bills[0]``.

    ``bill_type`` is the publisher's own spelling (``HRES``, ``S``, ``HR``,
    ...); ``normalized_bill_type`` lower-cases it to match
    ``sources.congress.bill_status.BILL_TYPES`` (already imported here for
    the package-id grammar), so a caller matching against that vocabulary
    does not normalize twice. It is ``None`` when the lower-cased spelling is
    not one of that vocabulary's entries.
    """

    congress: int
    bill_type: str
    number: str
    context: str
    normalized_bill_type: str | None


def _mods_bills(root: ModsRecord) -> tuple[ModsBill, ...]:
    """Read every root-level ``<bill>`` a package MODS states, in document order.

    Read the same way ``accessId`` and ``collectionCode`` are --
    ``root.fields("extension", "bill")`` reaches only the root's own
    ``extension`` children, so a constituent's own ``<bill>``, if any, is not
    read here, the same boundary ``access_ids`` already draws. A ``<bill>``
    missing ``congress``, ``type`` or a numeric ``number`` is skipped rather
    than guessed at; nothing here claims completeness beyond what was
    stated. A ``<bill>`` with no ``context`` is kept, with ``context=""``
    (see ``ModsBill``), not dropped.
    """
    bills: list[ModsBill] = []
    for element in root.fields("extension", "bill"):
        congress = element.attribute("congress")
        bill_type = element.attribute("type")
        number = element.attribute("number")
        context = element.attribute("context")
        if not (congress and congress.isdigit() and bill_type and number and number.isdigit()):
            continue
        normalized = bill_type.lower()
        bills.append(
            ModsBill(
                congress=int(congress),
                bill_type=bill_type,
                number=number,
                context=context or "",
                normalized_bill_type=normalized if normalized in BILL_TYPES else None,
            )
        )
    return tuple(bills)


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
    #: Every ``<bill>`` the MODS names, in document order. Empty for a
    #: package whose MODS states none.
    bills: tuple[ModsBill, ...]

    @property
    def primary_bill(self) -> ModsBill | None:
        """The ``<bill>`` this document is chiefly about, or ``None``.

        Never the first-listed one -- document order is not priority order
        (measured, CRPT-119hrpt1: S. 5 ``OTHER`` precedes H. Res. 53
        ``PRIMARY``).
        """
        return next((bill for bill in self.bills if bill.context == "PRIMARY"), None)


@dataclass(frozen=True, slots=True)
class GranuleModsIdentity:
    """The granule's own accessId, its host package's accessId, and offered renditions.

    A granule MODS states two identities: its own, directly under the root --
    the same shape a package MODS states its own accessId in -- and its host
    package's, nested inside a ``relatedItem type="host"``. The second is
    GovInfo's own proof that this granule belongs to that package, not an
    assumption drawn from the request URL.
    """

    identity: GranuleIdentity
    access_ids: tuple[str, ...]
    collection_code: str | None
    host_package_ids: tuple[str, ...]
    offered_formats: tuple[str, ...]
    moved_renditions: tuple[tuple[str, str], ...]
    other_renditions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PackageBodyIdentity:
    """A body proved against its locator, media type and the publisher's error page."""

    identity: PackageIdentity
    format: str
    media_type: str
    final_url: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class GranuleBodyIdentity:
    """A granule body proved against its locator, media type and the publisher's error page.

    Mirrors ``PackageBodyIdentity``: the body itself names no granule, so the
    locator -- the package's folder, the granule's own file stem -- is the
    identity.
    """

    identity: GranuleIdentity
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


# GovInfo publishes no per-collection granule-id grammar the way it does for
# package ids; a granule id is an opaque publisher-assigned path segment
# (measured: CREC-2026-09-18-pt1-PgS4837-4), so only its shape as a safe
# single path segment is checked, at the same bound as a package id.
_GRANULE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _checked_granule_id(value: object) -> str:
    if not isinstance(value, str) or _GRANULE_ID.fullmatch(value) is None:
        raise GovInfoBodySourceError(f"granule id must be a nonempty string of at most {MAX_PACKAGE_ID} characters")
    return value


def parse_granule_identity(package: PackageIdentity | str, granule_id: object) -> GranuleIdentity:
    """Parse one granule id against its package identity in ``O(I)`` time."""
    return GranuleIdentity(_identity(package), _checked_granule_id(granule_id))


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


def granule_summary_locator(package: PackageIdentity | str, granule_id: str) -> str:
    """Return the keyed granule summary locator; the credential travels as a header."""
    identity = parse_granule_identity(package, granule_id)
    return f"{API}/packages/{identity.package.package_id}/granules/{identity.granule_id}/summary"


def granule_mods_locator(package: PackageIdentity | str, granule_id: str) -> str:
    """Return the keyed granule MODS locator; the credential travels as a header."""
    identity = parse_granule_identity(package, granule_id)
    return f"{API}/packages/{identity.package.package_id}/granules/{identity.granule_id}/mods"


def granule_body_locator(package: PackageIdentity | str, granule_id: str, format: str) -> str:
    """Return the keyless granule rendition locator in ``O(I)`` time.

    The folder comes from ``PACKAGE_BODY_FORMATS`` exactly as it does for a
    package rendition; only the file stem differs -- the granule id, not the
    package id (measured 2026-09-19: ``content/pkg/CREC-2026-09-18/html/
    CREC-2026-09-18-pt1-PgS4837-4.htm``).
    """
    identity = parse_granule_identity(package, granule_id)
    body_format = _format(format)
    package_id = identity.package.package_id
    return f"{CONTENT}/content/pkg/{package_id}/{body_format.folder}/{identity.granule_id}.{body_format.extension}"


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
    return PackageSummary(
        identity=identity,
        collection_code=collection_code,
        date_issued=_text(document.get("dateIssued")),
        last_modified=_text(document.get("lastModified")),
        title=_text(document.get("title")),
        download_links=_download_links(document.get("download"), label="summary"),
    )


def validate_granule_summary(
    body: bytes,
    *,
    package: PackageIdentity | str,
    granule_id: str,
    final_url: str,
    max_bytes: int,
) -> GranuleSummary:
    """Prove the granule summary states the requested ``packageId`` and ``granuleId``.

    Both must agree, not just the one the request URL was built from: unlike a
    missing package, a granule that does not belong to the requested package
    answers HTTP 400 with no ``packageId``/``granuleId`` at all (measured
    2026-09-19), which this reads as an ordinary field mismatch rather than a
    distinct status-code rule.
    """
    identity = parse_granule_identity(package, granule_id)
    exact = _checked_bytes(body, max_bytes, label="granule summary")
    check_final_url(
        final_url,
        granule_summary_locator(identity.package, identity.granule_id),
        error_type=GovInfoBodySourceError,
        message="GovInfo granule summary final URL differs from the requested locator",
    )
    document = load_decimal_json(exact, source="GovInfo granule summary", error_type=GovInfoBodySourceError)
    if not isinstance(document, dict):
        raise GovInfoBodySourceError("GovInfo granule summary is not a JSON object")
    if document.get("packageId") != identity.package.package_id:
        raise GovInfoBodySourceError("GovInfo granule summary packageId differs from the requested package")
    if document.get("granuleId") != identity.granule_id:
        raise GovInfoBodySourceError("GovInfo granule summary granuleId differs from the requested granule")
    collection_code = document.get("collectionCode")
    if not isinstance(collection_code, str) or collection_code != identity.package.collection:
        raise GovInfoBodySourceError("GovInfo granule summary collectionCode differs from the requested collection")
    return GranuleSummary(
        identity=identity,
        collection_code=collection_code,
        date_issued=_text(document.get("dateIssued")),
        title=_text(document.get("title")),
        download_links=_download_links(document.get("download"), label="summary"),
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _download_links(download: object, *, label: str) -> tuple[tuple[str, str], ...]:
    """Keep every ``download`` link as the publisher spelled it; derive nothing from it.

    Shared by the package and granule summary readers: neither summary's
    links state the offered rendition set (three package collections list no
    body link at all while serving HTML and PDF, and BILLS spells its HTML
    rendition ``txtLink``), so both keep the links as evidence only.
    """
    if download is not None and not isinstance(download, dict):
        raise GovInfoBodySourceError(f"GovInfo {label} download block is not a JSON object")
    links: list[tuple[str, str]] = []
    for name, value in sorted((download or {}).items()):
        # A link can repeat under one name: GPO-J6-REPORT states five jpegLink
        # entries as a list. Each stays under its own name; anything that is
        # not a URL string is an anomaly this block cannot state.
        for url in value if isinstance(value, list) else [value]:
            if not isinstance(url, str):
                raise GovInfoBodySourceError(f"GovInfo {label} download link is not a URL string")
            links.append((name, url))
    return tuple(links)


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
    file type is a disagreement about where a format lives, and the caller
    can see the address the publisher gave. Anything else (another package,
    another file type, another host) is recorded verbatim and means nothing
    about this fetch.
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
    offered, moved, other = _read_offered_renditions(root, locators, identity)
    return PackageModsIdentity(
        identity=identity,
        access_ids=access_ids,
        collection_code=next(iter(codes), None),
        offered_formats=offered,
        moved_renditions=moved,
        other_renditions=other,
        bills=_mods_bills(root),
    )


def validate_granule_mods(
    body: bytes,
    *,
    package: PackageIdentity | str,
    granule_id: str,
    final_url: str,
    max_bytes: int,
    max_elements: int = 200_000,
) -> GranuleModsIdentity:
    """Prove the granule's own accessId and its host package's, then read its offered renditions.

    A granule MODS states its own identity the same way a package MODS states
    its own -- directly under the root, in the root's own ``extension``
    children -- and states its host package's identity nested inside a
    ``relatedItem type="host"``. Both are read and checked before any
    rendition is trusted, so membership rests on the publisher's own record,
    not on the package id the caller happened to request under.

    Renditions are read from the root's own ``location`` only (never the
    nested host's), the same rule and the same three-way split
    (offered/moved/other) ``validate_package_mods`` applies.
    """
    identity = parse_granule_identity(package, granule_id)
    exact = _checked_bytes(body, max_bytes, label="granule MODS")
    check_final_url(
        final_url,
        granule_mods_locator(identity.package, identity.granule_id),
        error_type=GovInfoBodySourceError,
        message="GovInfo granule MODS final URL differs from the requested locator",
    )
    try:
        parsed = parse_govinfo_mods(exact, max_bytes=max_bytes, max_elements=max_elements)
    except GovInfoModsError as error:
        raise GovInfoBodySourceError(f"GovInfo granule MODS is unreadable: {error}") from error
    root = parsed.package
    access_ids = tuple(element.text.strip() for element in root.fields("extension", "accessId"))
    if not access_ids:
        raise GovInfoBodySourceError("GovInfo granule MODS states no accessId")
    if any(value != identity.granule_id for value in access_ids):
        raise GovInfoBodySourceError("GovInfo granule MODS accessId differs from the requested granule")
    codes = {element.text.strip() for element in root.fields("extension", "collectionCode")}
    if codes and codes != {identity.package.collection}:
        raise GovInfoBodySourceError("GovInfo granule MODS collectionCode differs from the requested collection")
    hosts = [record for record in root.related_items if record.element.attribute("type") == "host"]
    host_ids = tuple(element.text.strip() for record in hosts for element in record.fields("extension", "accessId"))
    if not host_ids:
        raise GovInfoBodySourceError("GovInfo granule MODS states no host package")
    if any(value != identity.package.package_id for value in host_ids):
        raise GovInfoBodySourceError("GovInfo granule MODS host package differs from the requested package")
    locators = {
        granule_body_locator(identity.package, identity.granule_id, name): name for name in PACKAGE_BODY_FORMATS
    }
    offered, moved, other = _read_offered_renditions(root, locators, identity.package)
    return GranuleModsIdentity(
        identity=identity,
        access_ids=access_ids,
        collection_code=next(iter(codes), None),
        host_package_ids=host_ids,
        offered_formats=offered,
        moved_renditions=moved,
        other_renditions=other,
    )


def _read_offered_renditions(
    root: ModsRecord, locators: dict[str, str], identity: PackageIdentity
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    """Classify every raw-object rendition URL a MODS root's own ``location`` states.

    Shared by the package and granule MODS readers: both name their offered
    set from a root-level ``location`` (never a nested one -- a granule's own
    location sits directly under its root, its host package's sits nested
    inside ``relatedItem type="host"`` and is never read here), so the same
    three-way offered/moved/other split applies to either identity.
    """
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
    return tuple(offered), tuple(moved), tuple(other)


def _validate_body(
    body: bytes,
    *,
    format: str,
    content_type: str | None,
    final_url: str,
    expected_url: str,
    max_bytes: int,
    label: str,
) -> tuple[bytes, BodyFormat, str]:
    """The identity and shape checks every rendition needs, package or granule alike.

    The body itself names neither a package nor a granule, so the locator is
    the identity: the client refuses redirects, so a response at this URL is
    the requested object or it is the error page, which is refused first, so
    a response that landed on it says so rather than reporting a URL mismatch
    the caller cannot interpret.
    """
    body_format = _format(format)
    exact = _checked_bytes(body, max_bytes, label=label)
    check_not_error_page(
        exact,
        final_url,
        error_type=GovInfoBodySourceError,
        message=f"govinfo returned its HTTP-200 error page, not the requested {label}",
    )
    check_final_url(
        final_url,
        expected_url,
        error_type=GovInfoBodySourceError,
        message=f"GovInfo {label} final URL differs from the requested locator",
    )
    media_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if media_type not in body_format.media_types:
        raise GovInfoBodySourceError(f"GovInfo {label} Content-Type is not {body_format.name} for the requested format")
    if body_format.name == "pdf" and not exact.startswith(b"%PDF-"):
        raise GovInfoBodySourceError(f"GovInfo {label} does not begin with %PDF-")
    return exact, body_format, media_type


def validate_package_body(
    body: bytes,
    *,
    package: PackageIdentity | str,
    format: str,
    content_type: str | None,
    final_url: str,
    max_bytes: int,
) -> PackageBodyIdentity:
    """Prove a bounded body against its locator, media type and native magic."""
    identity = _identity(package)
    exact, body_format, media_type = _validate_body(
        body,
        format=format,
        content_type=content_type,
        final_url=final_url,
        expected_url=package_body_locator(identity, format),
        max_bytes=max_bytes,
        label="package body",
    )
    return PackageBodyIdentity(
        identity=identity,
        format=body_format.name,
        media_type=media_type,
        final_url=final_url,
        byte_size=len(exact),
    )


def validate_granule_body(
    body: bytes,
    *,
    package: PackageIdentity | str,
    granule_id: str,
    format: str,
    content_type: str | None,
    final_url: str,
    max_bytes: int,
) -> GranuleBodyIdentity:
    """Prove a bounded granule body against its locator, media type and native magic.

    Mirrors ``validate_package_body``: it differs only in which locator --
    the package's folder, the granule's own file stem -- and in the label its
    refusals carry.
    """
    identity = parse_granule_identity(package, granule_id)
    exact, body_format, media_type = _validate_body(
        body,
        format=format,
        content_type=content_type,
        final_url=final_url,
        expected_url=granule_body_locator(identity.package, identity.granule_id, format),
        max_bytes=max_bytes,
        label="granule body",
    )
    return GranuleBodyIdentity(
        identity=identity,
        format=body_format.name,
        media_type=media_type,
        final_url=final_url,
        byte_size=len(exact),
    )


__all__ = [
    "BODY_PREFERENCE",
    "GRANULE_BODY_PREFERENCE",
    "PACKAGE_BODY_FORMATS",
    "BodyFormat",
    "GovInfoBodySourceError",
    "GranuleBodyIdentity",
    "GranuleIdentity",
    "GranuleModsIdentity",
    "GranuleSummary",
    "ModsBill",
    "PackageBodyIdentity",
    "PackageIdentity",
    "PackageModsIdentity",
    "PackageSummary",
    "granule_body_locator",
    "granule_mods_locator",
    "granule_summary_locator",
    "package_body_locator",
    "package_mods_locator",
    "package_summary_locator",
    "parse_granule_identity",
    "parse_package_id",
    "validate_granule_body",
    "validate_granule_mods",
    "validate_granule_summary",
    "validate_package_body",
    "validate_package_mods",
    "validate_package_summary",
]
