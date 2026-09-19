"""Back-fill BILLSTATUS one Congress and one bill type at a time from the GovInfo bulk zip.

The keyless route is ``bulkdata/BILLSTATUS/{congress}/{type}/BILLSTATUS-{congress}-{type}.zip``,
one zip per publisher folder, served as ``application/zip``. This is the crawl
the families record requires to state its own bound before it is built
(``docs/decisions.md``): **one Congress and one bill type per call**, never a
whole Congress and never the collection. The 119th cost 52,236,275 bytes across
its eight types on 2026-09-19, of which H.R. alone was 31,656,886 bytes and
10,503 files.

Measured the same day over the 108th, 113th and 119th Congresses -- 24 zips,
131 MB, 40,260 members -- every member parsed but one, a single 113th file
still in the publisher's superseded 1.0.0 schema, which arrives as one refused
member and costs the other 5,884 in its folder nothing.

Every member proves its identity twice. Its file name must parse to a
``BillIdentity`` whose single-file locator spells that same name, and
``parse_bill_status`` must find that identity stated inside the XML. A member
that fails either check is a typed outcome inside the result, in archive order,
carrying its own bytes' digest and the refusal in the parser's own words: one
unreadable file must not cost the other ten thousand. The archive-wide bounds
are different — too many entries, an entry over its limit, a decoded total over
its limit or a failed CRC refuse the whole zip before any member is trusted,
because those say the response is not the archive that was asked for.

Bulk lags the Congress.gov API by days, so a backfill is a floor and an API
pass by update date carries the delta. An empty result for a real folder is a
requested-empty observation, never evidence that a Congress filed no bills.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING

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
    check_request_count,
    check_timing,
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

_LABEL = "BILLSTATUS archive"
_MEMBER_NAME = re.compile(r"BILLSTATUS-([1-9][0-9]*)(hconres|sconres|hjres|sjres|hres|sres|hr|s)([1-9][0-9]*)\.xml")


def bulk_status_locator(congress: int, bill_type: str) -> str:
    """One zip per Congress and bill type, in the publisher's lowercase folder names.

    ``BillIdentity`` checks the Congress and the type, so a folder can never be
    spelled in a way a member of it could not be.
    """
    BillIdentity(congress, bill_type, 1)
    return f"{BILLSTATUS_BULKDATA}/{congress}/{bill_type}/BILLSTATUS-{congress}-{bill_type}.zip"


def _member_identity(name: str, *, congress: int, bill_type: str) -> BillIdentity:
    """Prove the member's own name states a bill of the requested folder.

    The single-file locator is the one spelling authority: a name that does not
    rebuild it exactly -- a padded number, another Congress, another type, a
    stray path -- is refused rather than reinterpreted.
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

    Exactly one of ``status`` and ``refusal`` is set. ``identity`` is what the
    entry's name declared and the XML confirmed; it is ``None`` when the name
    itself could not be read, so the digest and size remain the only facts.
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
class BulkStatusAcquisition:
    archive: BulkStatusArchive
    capture: CapturedBodyResponse
    request_count: int
    budget: BulkStatusBudget


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

    def acquire(self, congress: int, bill_type: str) -> BulkStatusAcquisition:
        """Capture one Congress and one bill type; a 404 means that folder, not that Congress."""
        budget = self.budget
        archive, capture = self.capture_validated(
            bulk_status_locator(congress, bill_type),
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
        )
        return BulkStatusAcquisition(archive, capture, self.request_count, budget)


__all__ = [
    "BulkStatusAcquirer",
    "BulkStatusAcquisition",
    "BulkStatusArchive",
    "BulkStatusBudget",
    "BulkStatusMember",
    "bulk_status_locator",
    "read_bulk_status_archive",
]
