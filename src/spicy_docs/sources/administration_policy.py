"""Read commit-pinned community administration-policy metadata and its archived PDFs.

The archive states bill associations; it does not supply a structured political
position. Every record survives, including statements with no identified bill.
See docs/sources/administration-policy.md for source scope and validation evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

from spicy_docs.reading.literal_dates import literal_date_status
from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.reading.yaml_input import load_bounded_yaml
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_final_url,
    check_request_count,
    check_timing,
    named_challenge,
    utc_now,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    import httpx

_RAW = "https://raw.githubusercontent.com/unitedstates/statements-of-administration-policy"
_COMMIT = re.compile(r"[0-9a-f]{40}")
_ADMINISTRATION = re.compile(r"[0-9]{2}-[A-Za-z]+")
_BILL = re.compile(r"(?:hr|s|hres|sres|hjres|sjres|hconres|sconres)[1-9][0-9]*")
# The dated archive survey in the source guide establishes headroom for these
# per-file budgets. They bound one selected metadata file or archived PDF.
MAX_METADATA_BYTES = 4 * 1024**2
MAX_PDF_BYTES = 16 * 1024**2


class AdministrationPolicyError(ValueError):
    """The selected archive input could not be read without losing source meaning."""


class AdministrationPolicyUnavailable(AdministrationPolicyError):
    """The archive answered 404/410 for the pinned locator; the capture is retained."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"administration-policy archive answered HTTP {capture.status_code}")
        self.capture = capture


class AdministrationPolicyRefused(AdministrationPolicyError):
    """The keyless community archive refused a request; its evidence is retained."""

    def __init__(self, url: str) -> None:
        super().__init__(f"administration-policy archive refused access to {url}")


def metadata_url(commit: str, administration: str) -> str:
    """Locate one metadata file at a full commit, never a moving branch."""
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise AdministrationPolicyError("commit must be a full lowercase Git commit SHA")
    if not isinstance(administration, str) or not _ADMINISTRATION.fullmatch(administration):
        raise AdministrationPolicyError("administration must be an archive stem such as 47-Trump")
    return f"{_RAW}/{commit}/archive/{administration}.yaml"


def _pdf_url(commit: str, administration: str, filename: str) -> str:
    metadata_url(commit, administration)
    parts = filename.split("/")
    if (
        len(parts) < 4
        or parts[:2] != ["statements", administration]
        or any(part in ("", ".", "..") for part in parts)
        or any(char in filename for char in "\\?#%\r\n\x00")
        or not filename.endswith(".pdf")
    ):
        raise AdministrationPolicyError("file must name a PDF inside the selected administration's archive")
    return f"{_RAW}/{commit}/archive/{quote(filename, safe='/')}"


@dataclass(frozen=True, slots=True)
class PolicyStatement:
    source_record_index: int
    source_id: str
    congress: int
    bills: tuple[str, ...]
    document_title: str
    date_issued: str
    archived_pdf_url: str | None
    raw_json: str

    @property
    def bill_ids(self) -> tuple[str, ...]:
        """Explicit source links, qualified by Congress; an empty tuple stays empty."""
        return tuple(f"{bill}-{self.congress}" for bill in self.bills)

    @property
    def date_issued_status(self) -> str:
        return literal_date_status(self.date_issued)


@dataclass(frozen=True, slots=True)
class PolicyMetadata:
    commit: str
    administration: str
    input_sha256: str
    records: tuple[PolicyStatement, ...]


def parse_policy_metadata(
    body: bytes, *, commit: str, administration: str, max_bytes: int = MAX_METADATA_BYTES
) -> PolicyMetadata:
    """Read every record in source order; refuse ambiguous input as a whole.

    ``raw_json`` keeps all stated fields, including rescinded, URLs, capture
    dates and unknown additions. Retain the input bytes alongside their digest.
    Repeated statements and repeated bill links are never collapsed.
    """
    url = metadata_url(commit, administration)
    check_byte_bound(max_bytes, "max_bytes", MAX_METADATA_BYTES)
    value = load_bounded_yaml(
        body, source="administration-policy metadata", error_type=AdministrationPolicyError, max_bytes=max_bytes
    )
    if not isinstance(value, list):
        raise AdministrationPolicyError("archive metadata must be a YAML list")
    records = []
    for index, row in enumerate(value):
        prefix = f"archive record {index}"
        if not isinstance(row, dict) or any(not isinstance(key, str) for key in row):
            raise AdministrationPolicyError(f"{prefix} must be a string-keyed object")
        congress = row.get("congress")
        if type(congress) is not int or congress <= 0:
            raise AdministrationPolicyError(f"{prefix} congress must be a positive integer")
        bills = row.get("bills")
        if not isinstance(bills, list) or any(not isinstance(b, str) or not _BILL.fullmatch(b) for b in bills):
            raise AdministrationPolicyError(f"{prefix} bills must be a list of literal bill identifiers")
        for field in ("document_title", "date_issued"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise AdministrationPolicyError(f"{prefix} needs {field} text")
        if "rescinded" in row and type(row["rescinded"]) is not bool:
            raise AdministrationPolicyError(f"{prefix} rescinded must be boolean when present")
        for field in ("file", "url", "fetched_from_url", "date_fetched", "source"):
            if field in row and (not isinstance(row[field], str) or not row[field]):
                raise AdministrationPolicyError(f"{prefix} {field} must be nonempty text when present")
        if "file" not in row and "url" not in row:
            raise AdministrationPolicyError(f"{prefix} needs a file or external page locator")
        pdf = _pdf_url(commit, administration, row["file"]) if "file" in row else None
        try:
            raw_json = json.dumps(row, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as error:
            raise AdministrationPolicyError(f"{prefix} contains unsupported YAML values") from error
        records.append(
            PolicyStatement(
                index,
                f"{url}#record={index}",
                congress,
                tuple(bills),
                row["document_title"],
                row["date_issued"],
                pdf,
                raw_json,
            )
        )
    return PolicyMetadata(commit, administration, "sha256:" + hashlib.sha256(body).hexdigest(), tuple(records))


@dataclass(frozen=True, slots=True)
class PolicyBudget:
    max_requests: int = 2
    max_metadata_bytes: int = MAX_METADATA_BYTES
    max_pdf_bytes: int = MAX_PDF_BYTES
    timeout_seconds: float = 30.0
    min_request_interval_seconds: float = 0.2

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_metadata_bytes, "max_metadata_bytes", MAX_METADATA_BYTES)
        check_byte_bound(self.max_pdf_bytes, "max_pdf_bytes", MAX_PDF_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class PolicyAcquisition:
    file: PolicyMetadata
    capture: CapturedBodyResponse
    request_count: int


class AdministrationPolicyAcquirer(SourceAcquirer):
    """Capture one caller-selected metadata file or its separately selected PDF."""

    def __init__(
        self,
        *,
        budget: PolicyBudget | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        budget = budget or PolicyBudget()
        self.budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-administration-policy/1.0",
            label="administration-policy archive",
            error_type=AdministrationPolicyError,
            context_key="administration_policy_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    def acquire_metadata(self, *, commit: str, administration: str) -> PolicyAcquisition:
        url = metadata_url(commit, administration)

        def parse(capture: CapturedBodyResponse, limit: int) -> PolicyMetadata:
            check_final_url(
                capture.resolved_url,
                url,
                error_type=AdministrationPolicyError,
                message="archive response left the pinned metadata URL",
            )
            return parse_policy_metadata(capture.body, commit=commit, administration=administration, max_bytes=limit)

        with named_challenge(url, error_type=AdministrationPolicyRefused, context_key=self.context_key):
            result, capture = self.capture_validated(
                url,
                media_types=("text/plain", "application/yaml", "text/yaml", "application/octet-stream"),
                parse=parse,
                max_bytes=self.budget.max_metadata_bytes,
                unavailable=AdministrationPolicyUnavailable,
                context={"operation": "metadata", "commit": commit, "administration": administration},
            )
        return PolicyAcquisition(result, capture, self.request_count)

    def acquire_pdf(self, metadata: PolicyMetadata, *, record_index: int) -> CapturedBodyResponse:
        """Acquire the literal archived file; external UCSB pages remain locators."""
        if type(record_index) is not int or not 0 <= record_index < len(metadata.records):
            raise AdministrationPolicyError("record_index must select a metadata record")
        row = json.loads(metadata.records[record_index].raw_json)
        if "file" not in row:
            raise AdministrationPolicyError("this statement has an external page, not an archived PDF")
        url = _pdf_url(metadata.commit, metadata.administration, row["file"])

        def parse(capture: CapturedBodyResponse, _limit: int) -> str:
            check_final_url(
                capture.resolved_url,
                url,
                error_type=AdministrationPolicyError,
                message="archive response left the pinned PDF URL",
            )
            return check_pdf_bytes(
                capture.body, error_type=AdministrationPolicyError, label="archived policy statement"
            )

        with named_challenge(url, error_type=AdministrationPolicyRefused, context_key=self.context_key):
            _, capture = self.capture_validated(
                url,
                media_types=("application/pdf", "application/octet-stream"),
                parse=parse,
                max_bytes=self.budget.max_pdf_bytes,
                unavailable=AdministrationPolicyUnavailable,
                context={"operation": "pdf", "statement": metadata.records[record_index].source_id},
            )
        return capture
