"""Back-fill BILLSTATUS one Congress and one bill type at a time from the GovInfo bulk zip.

The keyless route is ``bulkdata/BILLSTATUS/{congress}/{type}/BILLSTATUS-{congress}-{type}.zip``,
one zip per publisher folder; the bound is one Congress and one bill type per
call, never a whole Congress and never the collection. Every member proves its
identity twice: its file name must rebuild the single-file locator, and
``parse_bill_status`` must find that identity stated inside the XML. A member
that fails either check is a typed outcome inside the result, in archive order,
carrying its own bytes' digest and the refusal in the parser's own words, so
one unreadable file does not cost the other ten thousand. Archive-wide bounds
refuse the whole zip before any member is trusted, because those say the
response is not the archive that was asked for. Bulk lags the Congress.gov API
by days, so a backfill is a floor and an API pass by update date carries the
delta; an empty result for a real folder is a requested-empty observation,
never evidence that a Congress filed no bills.

The same folder also answers a keyless JSON listing
(``bulkdata/json/BILLSTATUS/{congress}/{type}``) naming every file it holds,
the zip included, with its own modified stamp and size; a caller that retains
the zip's listing entry from one run can read this small listing the next and
skip the zip download entirely when the entry has not moved -- see
``BulkStatusAcquirer.acquire``'s ``unchanged_since``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spicy_docs.reading.json_input import load_integer_json
from spicy_docs.reading.zip_archive import archive_members, open_archive, read_member
from spicy_docs.releases.format import MAX_EVIDENCE_BYTES
from spicy_docs.sources.congress.bill_acquisition import BillSourceUnavailableError
from spicy_docs.sources.congress.bill_status import (
    BILLSTATUS_BULKDATA,
    BillIdentity,
    BillSourceError,
    BillStatus,
    bill_status_locator,
    parse_bill_status,
)
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_payload,
    check_request_count,
    check_timing,
    named_challenge,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

# GovInfo serves the zip as application/zip; octet-stream is accepted because
# the bulkdata host has answered that for other archive folders.
ARCHIVE_MEDIA_TYPES = ("application/zip", "application/octet-stream")

# Measured on 2026-09-19 over the 119th Congress. Largest type zip: H.R. at
# 31,656,886 bytes, 10,503 entries, 144,870,036 decoded bytes, largest member
# BILLSTATUS-119hr1.xml at 1,979,603 bytes. A member is bounded by the same
# MAX_EVIDENCE_BYTES one bill's status capture uses; BILLSTATUS deflates about
# 4.6:1, so a zip at the byte cap can state roughly 1.2 GB of members.
DEFAULT_MAX_ENTRIES = 32_768
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_BULK_STATUS_BYTES = 256 * 1024 * 1024
MAX_BULK_STATUS_TOTAL_BYTES = 2 * 1024 * 1024 * 1024

# The listing host, keyless like the archive itself; its own path shares the
# archive host's collection segment (``BILLSTATUS``) but not the ``bulkdata``
# root, which the archive locator names as ``BILLSTATUS_BULKDATA``.
BULK_LISTING_JSON = "https://www.govinfo.gov/bulkdata/json/BILLSTATUS"
JSON_LISTING_MEDIA_TYPES = ("application/json",)
# Measured 2026-09-19: H.R., the largest of the eight 119th folders, listed
# 10,504 entries in 3,744,366 bytes. Headroom for a folder that grows before
# the next measurement, not a publisher-stated bound.
DEFAULT_MAX_LISTING_BYTES = 8 * 1024 * 1024

_LABEL = "BILLSTATUS archive"
_LISTING_LABEL = "BILLSTATUS bulk listing"
# ``formattedLastModifiedTime`` is always two-digit day/hour/minute and a
# four-digit year in every one of 18,964 entries measured 2026-09-19; the
# month is looked up in ``_LISTING_MONTHS`` rather than read by name.
_LISTING_STAMP = re.compile(
    r"(?P<day>[0-9]{2})-(?P<month>[A-Za-z]{3})-(?P<year>[0-9]{4}) (?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})"
)
_LISTING_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1
    )
}
# Both digit runs are bounded, not just anchored: an unbounded run lets a long
# enough name reach ``int()``, whose own digit limit raises a plain ValueError
# that would escape the per-member handler and abort the rest of the archive.
# Four digits cover any Congress and seven any bill number.
_MEMBER_NAME = re.compile(
    r"BILLSTATUS-([1-9][0-9]{0,3})(hconres|sconres|hjres|sjres|hres|sres|hr|s)([1-9][0-9]{0,6})\.xml"
)


def bulk_status_locator(congress: int, bill_type: str) -> str:
    """One zip per Congress and bill type, in the publisher's lowercase folder names.

    ``BillIdentity`` checks the Congress and the type, so a folder can never be
    spelled in a way a member of it could not be.
    """
    BillIdentity(congress, bill_type, 1)
    return f"{BILLSTATUS_BULKDATA}/{congress}/{bill_type}/BILLSTATUS-{congress}-{bill_type}.zip"


def bulk_listing_locator(congress: int, bill_type: str) -> str:
    """The same folder's keyless JSON listing: every file it holds, not just the zip.

    Shares ``bulk_status_locator``'s identity check, so a folder can never be
    listed in a way its own zip could not be located.
    """
    BillIdentity(congress, bill_type, 1)
    return f"{BULK_LISTING_JSON}/{congress}/{bill_type}"


def _member_identity(name: str, *, congress: int, bill_type: str) -> BillIdentity:
    """Prove the member's own base name states a bill of the requested folder.

    ``name`` is the entry's base name; a member the publisher files under a
    path is still read by its name. The single-file locator is the spelling
    authority: a base name that does not rebuild it exactly -- a padded number,
    another Congress, another type -- is refused rather than reinterpreted.
    """
    match = _MEMBER_NAME.fullmatch(name)
    if match is None:
        raise BillSourceError("BILLSTATUS archive entry name does not state a bill identity")
    identity = BillIdentity(int(match[1]), match[2], int(match[3]))
    if bill_status_locator(identity) != f"{BILLSTATUS_BULKDATA}/{congress}/{bill_type}/{name}":
        raise BillSourceError("BILLSTATUS archive entry belongs to another Congress or bill type")
    return identity


@dataclass(frozen=True, slots=True)
class BulkStatusMember:
    """One archive entry, in the publisher's order, with its own bytes' evidence.

    ``name`` is the entry's full path inside the zip, kept as it was found.
    Exactly one of ``status`` and ``refusal`` is set, and they say how far the
    entry got: on a parsed member ``identity`` is what the name declared *and*
    the XML confirmed, while on a refused one it is only what the name
    declared, or ``None`` when the name itself could not be read and the size
    and digest are the only facts.
    """

    name: str
    identity: BillIdentity | None
    byte_size: int
    sha256: str
    status: BillStatus | None
    refusal: str | None


@dataclass(frozen=True, slots=True)
class BulkStatusArchive:
    """Every entry of one folder's zip, parsed or refused, in archive order."""

    congress: int
    bill_type: str
    members: tuple[BulkStatusMember, ...]

    @property
    def parsed_count(self) -> int:
        return sum(member.status is not None for member in self.members)

    @property
    def refused_count(self) -> int:
        return sum(member.refusal is not None for member in self.members)


def read_bulk_status_archive(
    body: bytes,
    *,
    congress: int,
    bill_type: str,
    max_bytes: int = MAX_BULK_STATUS_BYTES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_entry_bytes: int = MAX_EVIDENCE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> BulkStatusArchive:
    """Read one retained folder zip offline; counts follow from the members, never beside them."""
    bulk_status_locator(congress, bill_type)
    members: list[BulkStatusMember] = []
    with open_archive(
        body,
        max_bytes=max_bytes,
        max_entries=max_entries,
        max_entry_bytes=max_entry_bytes,
        max_total_bytes=max_total_bytes,
        error_type=BillSourceError,
        label=_LABEL,
    ) as archive:
        for info in archive_members(archive, max_entries=max_entries, error_type=BillSourceError, label=_LABEL):
            name = info.filename.rsplit("/", 1)[-1]
            data = read_member(archive, info, max_bytes=max_entry_bytes, error_type=BillSourceError, label=_LABEL)
            identity: BillIdentity | None = None
            status: BillStatus | None = None
            refusal: str | None = None
            try:
                identity = _member_identity(name, congress=congress, bill_type=bill_type)
                status = parse_bill_status(data, identity=identity, max_bytes=max_entry_bytes)
            except BillSourceError as error:
                refusal = str(error)
            members.append(
                BulkStatusMember(
                    name=info.filename,
                    identity=identity,
                    byte_size=len(data),
                    sha256="sha256:" + hashlib.sha256(data).hexdigest(),
                    status=status,
                    refusal=refusal,
                )
            )
    return BulkStatusArchive(congress, bill_type, tuple(members))


@dataclass(frozen=True, slots=True)
class BulkListingEntry:
    """One entry of a GovInfo bulkdata folder listing, every field as the publisher spelled it.

    The four fields that describe a file rather than a folder
    (``formattedSize``/``fileExtension``/``mimeType``/``size``) stay optional
    because a sibling folder-level listing answers subfolder entries with
    ``folder: true`` and none of the four; this dataclass reads either shape.
    ``modified_at`` and ``size`` are the publisher's own stamp and size parsed
    into the types a caller compares -- a UTC instant and an int -- so
    comparing "has this changed" never restrings a diff.
    """

    name: str
    display_label: str
    just_file_name: str
    link: str
    folder: bool
    formatted_last_modified_time: str
    modified_at: datetime
    mime_type: str | None
    file_extension: str | None
    formatted_size: str | None
    size: int | None


@dataclass(frozen=True, slots=True)
class BulkListing:
    """One folder's complete listing: every entry, plus the zip entry proved to be this folder's own.

    ``folder_modified`` is the listing response's own ``formattedLastModifiedTime``,
    stated once for the whole folder when the publisher does; measured
    2026-09-19, the ``{congress}/{type}`` listing this module reads never does
    -- it answers only ``{"files": [...]}`` -- so this is ``None`` today. It
    stays typed because a sibling GovInfo bulkdata listing does state one, and
    a caller should not have to guess whether the publisher will resume here.
    """

    congress: int
    bill_type: str
    entries: tuple[BulkListingEntry, ...]
    zip_entry: BulkListingEntry
    folder_modified: datetime | None


def _parse_listing_instant(value: object, *, field: str) -> datetime:
    """Parse a GovInfo bulkdata stamp ``DD-Mon-YYYY HH:MM`` -- GMT, seconds truncated, English months.

    The month is read from an explicit English name-to-number map rather than
    ``strptime``'s ``%b``, which reads the process's ``LC_TIME`` locale: a
    publisher stamp that never changes should not parse on one machine and
    refuse on another because of a locale setting this module never chose.
    """
    match = _LISTING_STAMP.fullmatch(value) if isinstance(value, str) else None
    month = _LISTING_MONTHS.get(match["month"]) if match else None
    if match is None or month is None:
        raise BillSourceError(f"{_LISTING_LABEL} {field} is not the publisher's DD-Mon-YYYY HH:MM stamp")
    try:
        return datetime(
            int(match["year"]), month, int(match["day"]), int(match["hour"]), int(match["minute"]), tzinfo=UTC
        )
    except ValueError as error:
        raise BillSourceError(f"{_LISTING_LABEL} {field} is not a valid calendar date and time") from error


def _listing_entry(raw: object) -> BulkListingEntry:
    if not isinstance(raw, Mapping):
        raise BillSourceError(f"{_LISTING_LABEL} entry must be a JSON object")
    for field in ("name", "displayLabel", "justFileName", "link", "formattedLastModifiedTime"):
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise BillSourceError(f"{_LISTING_LABEL} entry must state a nonempty {field}")
    folder = raw.get("folder")
    if not isinstance(folder, bool):
        raise BillSourceError(f"{_LISTING_LABEL} entry folder flag must be true or false")
    for field in ("mimeType", "fileExtension", "formattedSize"):
        if field in raw and raw[field] is not None and not isinstance(raw[field], str):
            raise BillSourceError(f"{_LISTING_LABEL} entry {field} must be a string when stated")
    size = raw.get("size")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
        raise BillSourceError(f"{_LISTING_LABEL} entry size must be a non-negative integer when stated")
    return BulkListingEntry(
        name=raw["name"],
        display_label=raw["displayLabel"],
        just_file_name=raw["justFileName"],
        link=raw["link"],
        folder=folder,
        formatted_last_modified_time=raw["formattedLastModifiedTime"],
        modified_at=_parse_listing_instant(raw["formattedLastModifiedTime"], field="formattedLastModifiedTime"),
        mime_type=raw.get("mimeType"),
        file_extension=raw.get("fileExtension"),
        formatted_size=raw.get("formattedSize"),
        size=size,
    )


def read_bulk_listing(
    body: bytes, *, congress: int, bill_type: str, max_bytes: int = DEFAULT_MAX_LISTING_BYTES
) -> BulkListing:
    """Read one retained folder listing offline; every entry proved to belong to this folder.

    Every entry's own ``link`` must rebuild the single-file locator
    ``bulk_status_locator`` would spell for its ``name`` in this Congress and
    bill type -- the same "prove it, don't reinterpret it" rule
    ``_member_identity`` applies to a zip member's name. A listing that folds
    in another folder's entry, or a folder-shaped entry this route never
    states, refuses the whole read. "Empty success is not absence": a listing
    with no zip entry for this folder refuses by name, because
    ``{"files": []}`` is a well-formed answer that still cannot be this
    route's promise.
    """
    bulk_listing_locator(congress, bill_type)
    payload = check_payload(body, max_bytes, label=_LISTING_LABEL, error_type=BillSourceError, allow_empty=False)
    value = load_integer_json(payload, source=_LISTING_LABEL, error_type=BillSourceError)
    if not isinstance(value, Mapping):
        raise BillSourceError(f"{_LISTING_LABEL} response is not a JSON object")
    raw_files = value.get("files")
    if not isinstance(raw_files, list):
        raise BillSourceError(f"{_LISTING_LABEL} response omitted its files list")
    entries = tuple(_listing_entry(raw) for raw in raw_files)
    for entry in entries:
        if entry.link != f"{BILLSTATUS_BULKDATA}/{congress}/{bill_type}/{entry.name}":
            raise BillSourceError(f"{_LISTING_LABEL} entry belongs to another Congress or bill type")
    zip_name = bulk_status_locator(congress, bill_type).rsplit("/", 1)[-1]
    zip_entries = [entry for entry in entries if entry.name == zip_name]
    if not zip_entries:
        raise BillSourceError(f"{_LISTING_LABEL} has no zip entry for the requested folder")
    if len(zip_entries) > 1:
        raise BillSourceError(f"{_LISTING_LABEL} repeats the folder zip entry")
    own_stamp = value.get("formattedLastModifiedTime")
    folder_modified = _parse_listing_instant(own_stamp, field="formattedLastModifiedTime") if own_stamp else None
    return BulkListing(congress, bill_type, entries, zip_entries[0], folder_modified)


@dataclass(frozen=True, slots=True)
class BulkStatusBudget:
    """One zip per call. The entry bounds are the archive's, the byte bound the response's."""

    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float
    max_entries: int = DEFAULT_MAX_ENTRIES
    max_entry_bytes: int = MAX_EVIDENCE_BYTES
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_BULK_STATUS_BYTES)
        check_request_count(self.max_entries, "max_entries")
        check_byte_bound(self.max_entry_bytes, "max_entry_bytes", MAX_EVIDENCE_BYTES)
        check_byte_bound(self.max_total_bytes, "max_total_bytes", MAX_BULK_STATUS_TOTAL_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class BulkListingAcquisition:
    listing: BulkListing
    capture: CapturedBodyResponse
    request_count: int
    budget: BulkStatusBudget


@dataclass(frozen=True, slots=True)
class BulkStatusAcquisition:
    """The zip's archive and capture, or -- on a proven-unchanged skip -- neither.

    ``archive`` and ``capture`` are both ``None`` exactly when
    ``skipped_unchanged`` is True: ``acquire`` proved from the listing alone
    that the zip has not moved since ``unchanged_since`` and never requested
    it. ``listing_capture`` and ``listing_entry`` are set whenever ``acquire``
    read the listing at all -- every call that passes an explicit
    ``unchanged_since``, skipped or not -- so a caller that ends up
    downloading a changed zip still gets the entry to retain for its next
    run's ``unchanged_since``.
    """

    archive: BulkStatusArchive | None
    capture: CapturedBodyResponse | None
    request_count: int
    budget: BulkStatusBudget
    skipped_unchanged: bool = False
    listing_capture: CapturedBodyResponse | None = None
    listing_entry: BulkListingEntry | None = None


class BulkStatusAcquirer(SourceAcquirer):
    """Keyless capture of one BILLSTATUS folder zip; the caller retains the bytes.

    This is a thin capture-and-validate wrapper: ``read_bulk_status_archive``
    does the archive work offline, so a retained zip replays without the client.
    """

    def __init__(
        self,
        *,
        budget: BulkStatusBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, BulkStatusBudget):
            raise TypeError("budget must be a BulkStatusBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-bulk-status/1.0",
            label="BILLSTATUS bulk",
            error_type=BillSourceError,
            context_key="bulk_status_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> BulkStatusBudget:
        return self._budget

    def list_archives(self, congress: int, bill_type: str) -> BulkListingAcquisition:
        """Capture the folder's own bulkdata listing: every file it holds, with its own stamp and size.

        Bounded by the smaller of the caller's ``max_bytes`` (sized for the
        zip) and ``DEFAULT_MAX_LISTING_BYTES``: the listing is a fraction of
        the zip's own bytes, and a caller's zip-sized budget should not also
        become this route's own cap. Keyless like ``acquire``'s zip route;
        ``named_challenge`` recasts a 401/403 bot wall as ``BillSourceError``
        rather than ``CredentialRefusedError``, the way the package's other
        keyless ``www.govinfo.gov`` routes already do.
        """
        budget = self.budget
        url = bulk_listing_locator(congress, bill_type)
        with named_challenge(url, error_type=BillSourceError, context_key=self.context_key):
            listing, capture = self.capture_validated(
                url,
                media_types=JSON_LISTING_MEDIA_TYPES,
                parse=lambda response, limit: read_bulk_listing(
                    response.body, congress=congress, bill_type=bill_type, max_bytes=limit
                ),
                max_bytes=min(budget.max_bytes, DEFAULT_MAX_LISTING_BYTES),
                unavailable=BillSourceUnavailableError,
                context={
                    "operation": "bulk-status-listing",
                    "selection": {"congress": congress, "billType": bill_type},
                    "budget": asdict(budget),
                },
                request_headers={"Accept": "application/json"},
            )
        return BulkListingAcquisition(listing, capture, self.request_count, budget)

    def acquire(
        self, congress: int, bill_type: str, *, unchanged_since: BulkListingEntry | None = None
    ) -> BulkStatusAcquisition:
        """Capture one Congress and one bill type; a 404 means that folder, not that Congress.

        ``unchanged_since`` is a zip entry retained from a prior call's
        ``listing_entry`` (or a standalone ``list_archives``). When given, the
        folder's listing is read first -- one small request sharing this
        call's single ``max_requests`` budget rather than getting a fresh one,
        so a listing that spends the whole budget leaves none for the zip. If
        the listing's own zip entry names the same file as ``unchanged_since``
        and states the same ``modified_at`` and ``size``, the zip download is
        skipped entirely: the returned acquisition carries
        ``skipped_unchanged=True``, ``archive`` and ``capture`` both ``None``,
        and the listing's own capture and entry attached. An
        ``unchanged_since`` whose ``name`` or ``link`` differs from what this
        folder's listing names for its own zip is refused outright -- it
        describes a different file, so comparing its stamp would risk a false
        skip. Otherwise the zip downloads exactly as it always has, and the
        listing entry this call saw travels on the acquisition for the
        caller's next run. ``request_count`` is always the true total for this
        call, listing included.
        """
        if unchanged_since is not None and not isinstance(unchanged_since, BulkListingEntry):
            raise TypeError("unchanged_since must be a BulkListingEntry")
        budget = self.budget
        listing_acquisition = self.list_archives(congress, bill_type) if unchanged_since is not None else None
        if listing_acquisition is not None:
            seen = listing_acquisition.listing.zip_entry
            if (unchanged_since.name, unchanged_since.link) != (seen.name, seen.link):
                raise BillSourceError("unchanged_since names a different file than this folder's own zip entry")
            if (seen.modified_at, seen.size) == (unchanged_since.modified_at, unchanged_since.size):
                return BulkStatusAcquisition(
                    archive=None,
                    capture=None,
                    request_count=self.request_count,
                    budget=budget,
                    skipped_unchanged=True,
                    listing_capture=listing_acquisition.capture,
                    listing_entry=seen,
                )
        url = bulk_status_locator(congress, bill_type)
        with named_challenge(url, error_type=BillSourceError, context_key=self.context_key):
            archive, capture = self.capture_validated(
                url,
                media_types=ARCHIVE_MEDIA_TYPES,
                parse=lambda response, limit: read_bulk_status_archive(
                    response.body,
                    congress=congress,
                    bill_type=bill_type,
                    max_bytes=limit,
                    max_entries=budget.max_entries,
                    max_entry_bytes=budget.max_entry_bytes,
                    max_total_bytes=budget.max_total_bytes,
                ),
                max_bytes=budget.max_bytes,
                unavailable=BillSourceUnavailableError,
                context={
                    "operation": "bulk-status-archive",
                    "selection": {"congress": congress, "billType": bill_type},
                    "budget": asdict(budget),
                },
                # A listing already read in this call keeps its request count
                # rather than being granted a second, independent budget.
                reset_budget=listing_acquisition is None,
            )
        return BulkStatusAcquisition(
            archive=archive,
            capture=capture,
            request_count=self.request_count,
            budget=budget,
            skipped_unchanged=False,
            listing_capture=listing_acquisition.capture if listing_acquisition is not None else None,
            listing_entry=listing_acquisition.listing.zip_entry if listing_acquisition is not None else None,
        )


__all__ = [
    "BulkListing",
    "BulkListingAcquisition",
    "BulkListingEntry",
    "BulkStatusAcquirer",
    "BulkStatusAcquisition",
    "BulkStatusArchive",
    "BulkStatusBudget",
    "BulkStatusMember",
    "bulk_listing_locator",
    "bulk_status_locator",
    "read_bulk_listing",
    "read_bulk_status_archive",
]
