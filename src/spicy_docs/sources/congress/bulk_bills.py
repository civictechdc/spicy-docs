"""Read bill text in bulk: one GovInfo ``BILLS`` folder zip per Congress, session and bill type.

The keyless route is ``bulkdata/BILLS/{congress}/{session}/{type}/BILLS-{congress}-{session}-{type}.zip``,
one zip per publisher folder, holding one XML file per printing named by its
package id (``BILLS-119hr1ih.xml``). The folder also answers a keyless JSON
listing (``bulkdata/json/BILLS/{congress}/{session}/{type}``) naming every
file it holds with its own stamp, size and media type, the zip included.

A caller reads the listing first, because it answers three questions without
the zip: whether the zip moved since a retained entry (``zip_entry_unchanged``,
the comparison the BILLSTATUS folders use), which printings the folder holds
(``BulkBillsListing.members``), and so whether the zip holds anything the
caller still needs. ``read_bulk_bills_archive`` then reads the zip once and
keeps only the members a ``keep`` predicate names, so one download serves every
printing it holds and a steady-state run holds only what it came for.

A kept member proves itself three ways before its bytes are returned: its name
must state a printing of the requested folder's Congress and bill type, the
listing must state a file of that name with the same byte count, and its bytes
must not be GovInfo's error page. Those are the checks the per-package route
makes (identity by address, media type, error page), moved from the response
onto the member. A member failing one is a typed refusal inside the result, in
archive order, carrying its own bytes' digest, so one bad file does not cost
the folder. Archive-wide bounds refuse the whole zip, because those say the
response is not the archive that was asked for.

The bytes are the per-package XML's own: every member of the 119th H.R. zips
equals the ``content/pkg/{id}/xml/{id}.xml`` body captured for it (3,516 of
3,516 by SHA-256, receipt ``fork-execution-2026-09-21/bill-family-bulk-2026-09-26/``).

Bulk begins with the 113th Congress (measured 2026-09-26: ``bulkdata/json/BILLS``
lists 113 through 119); an older printing has only its per-package route.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from spicy_docs.reading.media_types import bare_media_type
from spicy_docs.reading.zip_archive import archive_members, open_archive, read_member
from spicy_docs.releases.format import MAX_EVIDENCE_BYTES
from spicy_docs.sources.congress.bill_acquisition import BillSourceUnavailableError
from spicy_docs.sources.congress.bill_status import BillIdentity, BillSourceError, bill_xml_locator
from spicy_docs.sources.congress.bulk_status import (
    ARCHIVE_MEDIA_TYPES,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_LISTING_BYTES,
    DEFAULT_MAX_TOTAL_BYTES,
    JSON_LISTING_MEDIA_TYPES,
    MAX_BULK_STATUS_BYTES,
    BulkArchiveBudget,
    BulkListingEntry,
    read_folder_listing,
)
from spicy_docs.sources.govinfo.error_page import check_not_error_page
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import SourceAcquirer, named_challenge, utc_now

if TYPE_CHECKING:
    import httpx

BILLS_BULKDATA = "https://www.govinfo.gov/bulkdata/BILLS"
BILLS_LISTING_JSON = "https://www.govinfo.gov/bulkdata/json/BILLS"

#: The oldest Congress the BILLS bulk collection holds (measured 2026-09-26:
#: the collection listing names 113 through 119, and each of those Congresses
#: names sessions 1 and 2). A printing of an older Congress is reached only by
#: its per-package route.
BULK_BILLS_FLOOR = 113
BULK_BILLS_SESSIONS = (1, 2)

#: Measured 2026-09-26 over every folder of the 113th-119th: the largest zip is
#: 117/1/hr at 61,434,327 bytes, the most entries 8,043 (119/1/hr), the largest
#: decoded folder 228,149,005 bytes (116/2/hr) and the largest member
#: BILLS-117hr7776eah.xml at 10,421,178 bytes -- all inside the
#: ``BulkArchiveBudget`` bounds the BILLSTATUS folders use.
_LABEL = "BILLS archive"
_LISTING_LABEL = "BILLS bulk listing"
_XML_MEDIA_TYPES = ("application/xml", "text/xml")
# Bounded digit runs, as in ``bulk_status``: an unbounded run lets a long name
# reach ``int()``, whose digit limit raises a plain ValueError that would
# escape the per-member refusal. Four digits cover any Congress, seven any
# bill number, sixteen any version suffix the vocabulary spells.
_MEMBER_NAME = re.compile(
    r"(BILLS-([1-9][0-9]{0,3})(hconres|sconres|hjres|sjres|hres|sres|hr|s)([1-9][0-9]{0,6})[a-z][a-z0-9]{0,15})\.xml"
)


def _folder(congress: int, session: int, bill_type: str) -> str:
    """``{congress}/{session}/{type}``, with the Congress and type proved by ``BillIdentity``."""
    BillIdentity(congress, bill_type, 1)
    if session not in BULK_BILLS_SESSIONS:
        raise BillSourceError(f"BILLS bulk session must be one of {BULK_BILLS_SESSIONS}")
    return f"{congress}/{session}/{bill_type}"


def bulk_bills_locator(congress: int, session: int, bill_type: str) -> str:
    """One zip per Congress, session and bill type, in the publisher's lowercase folder names."""
    return f"{BILLS_BULKDATA}/{_folder(congress, session, bill_type)}/BILLS-{congress}-{session}-{bill_type}.zip"


def bulk_bills_listing_locator(congress: int, session: int, bill_type: str) -> str:
    """The same folder's keyless JSON listing: every file it holds, the zip included."""
    return f"{BILLS_LISTING_JSON}/{_folder(congress, session, bill_type)}"


@dataclass(frozen=True, slots=True)
class BulkBillsListing:
    """One folder's listing: every entry, the folder's own zip entry, and its printings by package id.

    ``members`` maps each ``.xml`` entry's package id to its entry -- what the
    zip should hold, stated by the publisher apart from the zip itself.
    """

    congress: int
    session: int
    bill_type: str
    entries: tuple[BulkListingEntry, ...]
    zip_entry: BulkListingEntry
    folder_modified: datetime | None
    members: Mapping[str, BulkListingEntry] = field(repr=False)


def read_bulk_bills_listing(
    body: bytes, *, congress: int, session: int, bill_type: str, max_bytes: int = DEFAULT_MAX_LISTING_BYTES
) -> BulkBillsListing:
    """Read one retained folder listing offline; every entry proved to belong to this folder.

    The same reader as the BILLSTATUS listings (``read_folder_listing``): an
    entry whose ``link`` is not this folder's refuses the whole read, and a
    listing with no zip entry for the folder refuses by name.
    """
    folder = _folder(congress, session, bill_type)
    locator = bulk_bills_locator(congress, session, bill_type)
    entries, zip_entry, folder_modified = read_folder_listing(
        body,
        folder_url=f"{BILLS_BULKDATA}/{folder}",
        zip_name=locator.rsplit("/", 1)[-1],
        label=_LISTING_LABEL,
        max_bytes=max_bytes,
    )
    members = {entry.name[: -len(".xml")]: entry for entry in entries if entry.name.endswith(".xml")}
    return BulkBillsListing(congress, session, bill_type, entries, zip_entry, folder_modified, members)


@dataclass(frozen=True, slots=True)
class BulkBillsBody:
    """One printing's bytes read out of a folder zip, in the shape a version capture's ``body`` carries.

    ``requested_url``, ``resolved_url`` and ``observed_at`` are the zip's: that
    is the request that returned these bytes, and the member is found in it
    under ``member`` (always ``{package_id}.xml``). ``content_type`` is the
    media type the folder listing states for the member, since a zip entry
    carries none. ``byte_size`` and ``sha256`` are the member's own bytes, so a
    printing read in bulk has the digest its per-package capture would.
    """

    requested_url: str
    resolved_url: str
    content_type: str
    observed_at: str
    member: str
    body: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", "sha256:" + hashlib.sha256(self.body).hexdigest())

    @property
    def byte_size(self) -> int:
        return len(self.body)


@dataclass(frozen=True, slots=True)
class BulkBillsMember:
    """One kept archive entry, in the publisher's order: its body, or why it has none.

    Exactly one of ``body`` and ``refusal`` is set. ``package_id`` and
    ``identity`` are what the entry's name declared, or ``None`` when the name
    itself could not be read; ``byte_size`` and ``sha256`` are the entry's
    bytes either way.
    """

    name: str
    package_id: str | None
    identity: BillIdentity | None
    byte_size: int
    sha256: str
    body: BulkBillsBody | None
    refusal: str | None


@dataclass(frozen=True, slots=True)
class BulkBillsArchive:
    """The kept entries of one folder's zip, read or refused, and how many were passed over."""

    congress: int
    session: int
    bill_type: str
    members: tuple[BulkBillsMember, ...]
    skipped_count: int

    @property
    def read_count(self) -> int:
        return sum(member.body is not None for member in self.members)

    @property
    def refused_count(self) -> int:
        return sum(member.refusal is not None for member in self.members)


def _member_package(name: str, listing: BulkBillsListing) -> tuple[str, BillIdentity]:
    """The package id and bill a member's base name states, proved to be this folder's."""
    match = _MEMBER_NAME.fullmatch(name)
    if match is None:
        raise BillSourceError("BILLS archive entry name does not state a printing")
    identity = BillIdentity(int(match[2]), match[3], int(match[4]))
    if (identity.congress, identity.bill_type) != (listing.congress, listing.bill_type):
        raise BillSourceError("BILLS archive entry belongs to another Congress or bill type")
    package_id = match[1]
    bill_xml_locator(identity, package_id)
    return package_id, identity


def _checked_member(data: bytes, name: str, listing: BulkBillsListing, capture: CapturedBodyResponse) -> BulkBillsBody:
    """The member as a body, once the listing and the bytes agree it is the XML the folder names."""
    entry = listing.members.get(name[: -len(".xml")])
    if entry is None:
        raise BillSourceError("BILLS archive entry is not named in the folder listing")
    if entry.size != len(data):
        raise BillSourceError("BILLS archive entry size differs from the folder listing's")
    if bare_media_type(entry.mime_type) not in _XML_MEDIA_TYPES:
        raise BillSourceError("BILLS folder listing does not state XML for the archive entry")
    check_not_error_page(
        data,
        capture.resolved_url,
        error_type=BillSourceError,
        message="BILLS archive entry is GovInfo's error page, not a printing",
    )
    assert entry.mime_type is not None
    return BulkBillsBody(
        requested_url=capture.requested_url,
        resolved_url=capture.resolved_url,
        content_type=entry.mime_type,
        observed_at=capture.observed_at,
        member=name,
        body=data,
    )


def read_bulk_bills_archive(
    capture: CapturedBodyResponse,
    *,
    listing: BulkBillsListing,
    keep: Callable[[str], bool] | None = None,
    max_bytes: int = MAX_BULK_STATUS_BYTES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_entry_bytes: int = MAX_EVIDENCE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> BulkBillsArchive:
    """Read one retained folder zip offline against its listing, keeping the members ``keep`` names.

    ``keep`` takes a package id; ``None`` keeps every member. A member whose
    name states no printing of this folder is refused whatever ``keep`` says,
    because it has no package id to ask about. Members not kept are never
    decompressed: a caller after a handful of new printings pays for their
    bytes, not the folder's.
    """
    locator = bulk_bills_locator(listing.congress, listing.session, listing.bill_type)
    if (capture.requested_url, capture.resolved_url) != (locator, locator):
        raise BillSourceError("BILLS archive capture is not the listed folder's zip")
    members: list[BulkBillsMember] = []
    skipped = 0
    with open_archive(
        capture.body,
        max_bytes=max_bytes,
        max_entries=max_entries,
        max_entry_bytes=max_entry_bytes,
        max_total_bytes=max_total_bytes,
        error_type=BillSourceError,
        label=_LABEL,
    ) as archive:
        for info in archive_members(archive, max_entries=max_entries, error_type=BillSourceError, label=_LABEL):
            name = info.filename.rsplit("/", 1)[-1]
            package_id: str | None = None
            identity: BillIdentity | None = None
            try:
                package_id, identity = _member_package(name, listing)
            except BillSourceError as error:
                refusal: str | None = str(error)
            else:
                refusal = None
                if keep is not None and not keep(package_id):
                    skipped += 1
                    continue
            data = read_member(archive, info, max_bytes=max_entry_bytes, error_type=BillSourceError, label=_LABEL)
            body: BulkBillsBody | None = None
            if refusal is None:
                try:
                    body = _checked_member(data, name, listing, capture)
                except BillSourceError as error:
                    refusal = str(error)
            members.append(
                BulkBillsMember(
                    name=info.filename,
                    package_id=package_id,
                    identity=identity,
                    byte_size=len(data),
                    sha256=body.sha256 if body is not None else "sha256:" + hashlib.sha256(data).hexdigest(),
                    body=body,
                    refusal=refusal,
                )
            )
    return BulkBillsArchive(listing.congress, listing.session, listing.bill_type, tuple(members), skipped)


@dataclass(frozen=True, slots=True)
class BulkBillsListingAcquisition:
    listing: BulkBillsListing
    capture: CapturedBodyResponse
    request_count: int
    budget: BulkArchiveBudget


@dataclass(frozen=True, slots=True)
class BulkBillsAcquisition:
    archive: BulkBillsArchive
    capture: CapturedBodyResponse
    request_count: int
    budget: BulkArchiveBudget


class BulkBillsAcquirer(SourceAcquirer):
    """Keyless capture of one BILLS folder's listing, then, if the caller wants it, its zip.

    Two calls rather than one, because the decision between them is the
    caller's: whether the zip moved since a retained entry, and whether it
    holds any printing the caller still needs, are both answered by the
    listing. ``read_bulk_bills_archive`` does the archive work offline, so a
    retained zip and listing replay without the client.
    """

    def __init__(
        self,
        *,
        budget: BulkArchiveBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, BulkArchiveBudget):
            raise TypeError("budget must be a BulkArchiveBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-bulk-bills/1.0",
            label="BILLS bulk",
            error_type=BillSourceError,
            context_key="bulk_bills_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> BulkArchiveBudget:
        return self._budget

    def list_folder(self, congress: int, session: int, bill_type: str) -> BulkBillsListingAcquisition:
        """Capture the folder's listing, bounded like the BILLSTATUS listings; a 404 means that folder."""
        budget = self.budget
        url = bulk_bills_listing_locator(congress, session, bill_type)
        with named_challenge(url, error_type=BillSourceError, context_key=self.context_key):
            listing, capture = self.capture_validated(
                url,
                media_types=JSON_LISTING_MEDIA_TYPES,
                parse=lambda response, limit: read_bulk_bills_listing(
                    response.body, congress=congress, session=session, bill_type=bill_type, max_bytes=limit
                ),
                max_bytes=min(budget.max_bytes, DEFAULT_MAX_LISTING_BYTES),
                unavailable=BillSourceUnavailableError,
                context={
                    "operation": "bulk-bills-listing",
                    "selection": {"congress": congress, "session": session, "billType": bill_type},
                    "budget": asdict(budget),
                },
                request_headers={"Accept": "application/json"},
            )
        return BulkBillsListingAcquisition(listing, capture, self.request_count, budget)

    def acquire(self, listing: BulkBillsListing, *, keep: Callable[[str], bool] | None = None) -> BulkBillsAcquisition:
        """Capture the listed folder's zip once and read the members ``keep`` names against ``listing``."""
        if not isinstance(listing, BulkBillsListing):
            raise TypeError("listing must be a BulkBillsListing")
        budget = self.budget
        url = bulk_bills_locator(listing.congress, listing.session, listing.bill_type)
        with named_challenge(url, error_type=BillSourceError, context_key=self.context_key):
            archive, capture = self.capture_validated(
                url,
                media_types=ARCHIVE_MEDIA_TYPES,
                parse=lambda response, limit: read_bulk_bills_archive(
                    response,
                    listing=listing,
                    keep=keep,
                    max_bytes=limit,
                    max_entries=budget.max_entries,
                    max_entry_bytes=budget.max_entry_bytes,
                    max_total_bytes=budget.max_total_bytes,
                ),
                max_bytes=budget.max_bytes,
                unavailable=BillSourceUnavailableError,
                context={
                    "operation": "bulk-bills-archive",
                    "selection": {
                        "congress": listing.congress,
                        "session": listing.session,
                        "billType": listing.bill_type,
                    },
                    "budget": asdict(budget),
                },
            )
        return BulkBillsAcquisition(archive, capture, self.request_count, budget)


__all__ = [
    "BILLS_BULKDATA",
    "BILLS_LISTING_JSON",
    "BULK_BILLS_FLOOR",
    "BULK_BILLS_SESSIONS",
    "BulkBillsAcquirer",
    "BulkBillsAcquisition",
    "BulkBillsArchive",
    "BulkBillsBody",
    "BulkBillsListing",
    "BulkBillsListingAcquisition",
    "BulkBillsMember",
    "bulk_bills_listing_locator",
    "bulk_bills_locator",
    "read_bulk_bills_archive",
    "read_bulk_bills_listing",
]
