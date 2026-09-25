"""One public P8 original from a retained eLibrary accession file list.

The browser's Download File action POSTs ``File/DownloadP8File`` with the
selected file GUID in ``fileidLst``. A live 2026-09-25 capture returned the
same original PDF through the browser and direct HTTP; see ``docs/sources/ferc.md``.
This is distinct from ``DownloadPDF``, which generates an accession-level PDF.

Only source-stated public GUID files are selected here. Legacy numeric file
identities and multi-file ZIP generation have not been qualified. The exact
declared size and media type bind the response to its metadata; PDF originals
also require PDF magic and a trailer. Other originals remain uninterpreted bytes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from spicy_docs.reading.media_types import bare_media_type
from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.sources.ferc.download import FercElibraryDownloadBudget
from spicy_docs.sources.ferc.elibrary import (
    API,
    BROWSER_USER_AGENT,
    FercElibraryAccessRefusedError,
    FercElibraryError,
    FileList,
    elibrary_transport,
)
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.download import validate_body_prefix
from spicy_docs.transport.source_acquirer import SourceAcquirer, named_challenge, narrow_byte_limit, utc_now

if TYPE_CHECKING:
    import httpx

ORIGINAL_DOWNLOAD_URL = f"{API}/File/DownloadP8File"
_FILE_ID = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}")


class FercElibraryOriginalError(FercElibraryError):
    """The selected metadata or response cannot establish this public original."""


class FercElibraryOriginalUnavailableError(FercElibraryOriginalError):
    """Only this requested original answered 404/410, never accession absence."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"FERC eLibrary DownloadP8File answered HTTP {capture.status_code} for the selected file")
        self.capture = capture


def original_download_body(file_id: str) -> bytes:
    """The browser's single-GUID request; numeric legacy identifiers are a different route selection."""
    if not isinstance(file_id, str) or _FILE_ID.fullmatch(file_id) is None:
        raise FercElibraryOriginalError("FERC original file ID must be a publisher-stated GUID")
    return json.dumps(
        {"FileType": "", "accession": "", "fileid": 0, "FileIDAll": "", "fileidLst": [file_id], "Islegacy": False},
        separators=(",", ":"),
    ).encode()


def _selected_file(files: FileList, file_id: str) -> Mapping[str, Any]:
    if not isinstance(files, FileList):
        raise TypeError("files must be a captured FileList")
    matches = [row for row in files.records if row.get("ID") == file_id]
    if len(matches) != 1:
        raise FercElibraryOriginalError("file list must state the selected original exactly once")
    row = matches[0]
    if row.get("Accession_Number") != files.accession:
        raise FercElibraryOriginalError("selected original belongs to a different accession")
    if row.get("Availability_Mode") != "P":
        raise FercElibraryOriginalError("selected original does not state public availability")
    size = row.get("File_Size_Num")
    if type(size) is not int or size < 0:
        raise FercElibraryOriginalError("selected original must state a nonnegative byte size")
    if not isinstance(row.get("Orig_File_Name"), str) or not row["Orig_File_Name"].strip():
        raise FercElibraryOriginalError("selected original omitted its file name")
    if not isinstance(row.get("MimeType"), str) or not row["MimeType"].strip():
        raise FercElibraryOriginalError("selected original omitted its media type")
    return row


@dataclass(frozen=True, slots=True)
class OriginalAcquisition:
    """The exact original and the retained file-list row that selected it."""

    accession: str
    file_id: str
    metadata: Mapping[str, Any]
    file_list_sha256: str
    capture: CapturedBodyResponse
    request_count: int
    budget: FercElibraryDownloadBudget
    requested_empty: bool

    @property
    def sha256(self) -> str:
        return self.capture.sha256


class FercElibraryOriginalAcquirer(SourceAcquirer):
    """One bounded direct POST per selected public file; keep this client open to preserve pacing."""

    def __init__(
        self,
        *,
        budget: FercElibraryDownloadBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, FercElibraryDownloadBudget):
            raise TypeError("budget must be a FercElibraryDownloadBudget")
        self.budget = budget
        super().__init__(
            max_requests=1,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=BROWSER_USER_AGENT,
            label="FERC eLibrary original file",
            error_type=FercElibraryOriginalError,
            context_key="ferc_elibrary_original_acquisition",
            transport=elibrary_transport(transport),
            clock=clock,
            keyless=True,
        )

    def acquire(self, files: FileList, *, file_id: str, max_bytes: int | None = None) -> OriginalAcquisition:
        """Acquire one metadata-stated original, preserving bytes and refusing a metadata/body disagreement."""
        body = original_download_body(file_id)
        row = _selected_file(files, file_id)
        limit = narrow_byte_limit(self.budget.max_bytes, max_bytes)
        if row["File_Size_Num"] > limit:
            raise FercElibraryOriginalError("selected original exceeds the requested byte bound")
        media_type = bare_media_type(row["MimeType"])

        def check(capture: CapturedBodyResponse, _limit: int) -> bool:
            validate_body_prefix(
                capture.body[:65536], media_type=media_type, allow_html=False, error_type=FercElibraryOriginalError
            )
            if capture.byte_size != row["File_Size_Num"]:
                raise FercElibraryOriginalError("original byte size differs from the file list's declared size")
            if not capture.body:
                return True
            if media_type == "application/pdf" or row.get("File_Type_Code") == "PDF":
                check_pdf_bytes(capture.body, error_type=FercElibraryOriginalError, label="FERC original PDF")
            return False

        with named_challenge(
            ORIGINAL_DOWNLOAD_URL, error_type=FercElibraryAccessRefusedError, context_key=self.context_key
        ):
            requested_empty, capture = self.capture_validated(
                ORIGINAL_DOWNLOAD_URL,
                media_types=(media_type, "application/octet-stream"),
                parse=check,
                max_bytes=limit,
                unavailable=FercElibraryOriginalUnavailableError,
                context={
                    "operation": "original-file",
                    "accession": files.accession,
                    "fileId": file_id,
                    "fileListSha256": files.capture.sha256,
                    "maxBytes": limit,
                },
                method="POST",
                content=body,
                request_headers={"Content-Type": "application/json"},
            )
        return OriginalAcquisition(
            files.accession,
            file_id,
            dict(row),
            files.capture.sha256,
            capture,
            self.request_count,
            self.budget,
            requested_empty,
        )


__all__ = [
    "ORIGINAL_DOWNLOAD_URL",
    "FercElibraryOriginalAcquirer",
    "FercElibraryOriginalError",
    "FercElibraryOriginalUnavailableError",
    "OriginalAcquisition",
    "original_download_body",
]
