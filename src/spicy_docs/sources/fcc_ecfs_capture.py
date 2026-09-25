"""Durable FCC filing-to-document capture over the existing blob store.

The backfill caller pins each date window's filings and exact list pages. A
completed window verifies by replaying those pages through the counted
traversal; this journal links each document to the pinned filing that offered
it, and verifies stored bytes before skipping a download. Each invocation
writes a fresh blob store, so reacquiring a damaged blob preserves the damaged
evidence instead of overwriting an immutable object. This is acquisition state,
not a release. One process owns an output directory at a time.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Self
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from rulespec_artifacts import BlobIntegrityError

from spicy_docs.reading.paged_json import DEFAULT_MAX_PAGE_BYTES, JsonPage, PagedJsonBudget
from spicy_docs.sources.fcc_ecfs import FccEcfsReader
from spicy_docs.sources.fcc_ecfs_attachments import (
    PER_DOCUMENT_REFUSALS,
    FccEcfsDocumentAcquirer,
    FccEcfsDocumentError,
    FccEcfsDocumentRefusedError,
    FccEcfsDocumentUnavailableError,
    declared_documents,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore, iter_verified_blob
from spicy_docs.transport.captured import CapturedBodyResponse, attached_capture
from spicy_docs.transport.credentials import CredentialRefusedError, scrub_credential, scrub_record


def json_line(value: object) -> bytes:
    """One JSONL line: sorted keys and ASCII escapes, shared by pinned outputs and their replay."""
    return (json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n").encode()


def _store(output: Path, run_id: str, *, create: bool = False) -> LocalSourceNativeBlobStore:
    if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
        raise ValueError("FCC capture store must name a canonical run UUID")
    return LocalSourceNativeBlobStore(output / "captures" / run_id, create=create)


def retained_body(output: Path, receipt: dict) -> bytes:
    """Read a pinned capture, refusing missing, changed or oversized bytes."""
    if type(receipt["bytes"]) is not int or not 0 <= receipt["bytes"] <= DEFAULT_MAX_PAGE_BYTES:
        raise ValueError("FCC retained page exceeds its capture bound")
    return b"".join(iter_verified_blob(_store(output, receipt["runId"]), receipt["sha256"], receipt["bytes"]))


def replay_window(output: Path, window: dict) -> None:
    """Rerun the counted traversal offline over a window's retained pages; it must reproduce the pinned records."""
    import httpx

    pages = window.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("FCC completed window has no retained page evidence")
    served = iter(pages)

    def respond(request: httpx.Request) -> httpx.Response:
        page = next(served, None)
        if page is None or (request.method, str(request.url), str(request.url)) != (
            page["method"],
            page["requestedUrl"],
            page["resolvedUrl"],
        ):
            raise ValueError("FCC retained pages differ from the replayed request sequence")
        body = retained_body(output, page)
        return httpx.Response(
            page["status"], headers={"Content-Type": page["contentType"] or ""}, stream=httpx.ByteStream(body)
        )

    limit = int(parse_qs(urlsplit(pages[0]["requestedUrl"]).query, strict_parsing=True)["limit"][0])
    hasher, size, count = hashlib.sha256(), 0, 0
    # A random key cannot occur in a retained body, so the echo check stays meaningful.
    with FccEcfsReader(
        budget=PagedJsonBudget(1, DEFAULT_MAX_PAGE_BYTES, 60, 0),
        api_key=uuid4().hex,
        transport=httpx.MockTransport(respond),
    ) as reader:
        for record in reader.iter_filings(received_from=window["start"], received_to=window["end"], limit=limit):
            body = json_line(record)
            hasher.update(body)
            size += len(body)
            count += 1
    if next(served, None) is not None:
        raise ValueError("FCC retained window holds pages its replay never requested")
    if ("sha256:" + hasher.hexdigest(), size, count) != (window["sha256"], window["bytes"], window["records"]):
        raise ValueError("FCC retained pages differ from the completed window's records")


def verified_pages(output: Path, window: dict) -> bool:
    """Completion requires reproducible pages as well as a filings JSONL file."""
    try:
        replay_window(output, window)
    except (OSError, ValueError, KeyError, TypeError, BlobIntegrityError, CredentialRefusedError):
        return False
    return True


def read_capture_journal(path: Path, *, repair_tail: bool = False) -> Iterator[dict]:
    """Read durable rows, optionally preserving/removing an interrupted tail.

    A malformed complete row refuses. A final row without its newline has
    not committed and cannot settle an item; read-only planning ignores it.
    """
    if not path.exists():
        return
    with path.open("rb+" if repair_tail else "rb") as stream:
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.endswith(b"\n"):
                if repair_tail:
                    tail = path.with_name(f"{path.stem}-interrupted-{uuid4()}.partial")
                    with tail.open("xb") as partial:
                        partial.write(line)
                        partial.flush()
                        os.fsync(partial.fileno())
                    stream.truncate(start)
                    stream.flush()
                    os.fsync(stream.fileno())
                break
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError("FCC capture journal row is not an object")
            yield row


class FccCaptureJournal:
    """Append-only file outcomes; retry unsuccessful files and keep verified successes."""

    def __init__(
        self,
        output: Path,
        *,
        secrets: Iterable[str] = (),
        max_document_attempts: int | None = None,
        scope: dict | None = None,
    ) -> None:
        if max_document_attempts is not None and (type(max_document_attempts) is not int or max_document_attempts < 1):
            raise ValueError("max_document_attempts must be a positive integer")
        self.output = output
        self.run_id = str(uuid4())
        self._secrets = tuple(secret for secret in secrets if secret)
        # scrub_credential replaces literals of eight or more characters; check both JSON spellings of each.
        self._literals = {
            form for secret in self._secrets if len(secret) >= 8 for form in (secret, json_line(secret)[1:-2].decode())
        }
        self.max_document_attempts = max_document_attempts
        self.attempts = 0
        self.reused = 0
        self.invalid_filings = 0
        self.state: dict[str, dict] = {}
        self.results: dict[str, str] = {}
        self.filings: set[str] = set()
        self.empty_filings: set[str] = set()
        output.mkdir(parents=True, exist_ok=True)
        self.path = output / "documents.jsonl"
        for row in read_capture_journal(self.path, repair_tail=True):
            if row.get("kind") == "document":
                self.state[row["key"]] = row
        self.store = _store(output, self.run_id, create=True)
        self._sink = self.path.open("ab")
        self.emit(
            {
                "kind": "started",
                "maxDocumentAttempts": max_document_attempts,
                "scope": scope,
                "packageVersion": version("spicy-docs"),
                "captureCodeSha256": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._sink.closed:
            self.commit()
            self._sink.close()

    def commit(self) -> None:
        """Make every row written so far durable; the caller commits once per window."""
        self._sink.flush()
        os.fsync(self._sink.fileno())

    def emit(self, row: dict) -> None:
        """Scrub every string and key, then refuse to write a row whose serialization still carries a credential."""
        payload = json_line(
            scrub_record({"runId": self.run_id, "recordedAt": datetime.now(UTC).isoformat(), **row}, *self._secrets)
        )
        if any(literal in payload.decode() for literal in self._literals):
            raise ValueError("FCC capture journal row kept a credential; it was not written")
        # The row as a reader will decode it: one more pattern pass must find nothing to change.
        decoded = json.loads(payload)
        if scrub_record(decoded) != decoded:
            raise ValueError("FCC capture journal row kept a credential parameter; it was not written")
        self._sink.write(payload)
        self._sink.flush()

    def _put(self, body: bytes, digest: str | None = None) -> dict:
        if any(len(secret) >= 8 and secret.encode() in body for secret in self._secrets):
            raise CredentialRefusedError("FCC response reflected a credential; exact bytes were not retained")
        digest = digest or "sha256:" + hashlib.sha256(body).hexdigest()
        self.store.put_blob(digest, len(body), (body,))
        return {"runId": self.run_id, "sha256": digest, "bytes": len(body)}

    def retain(self, capture: CapturedBodyResponse) -> dict:
        return {
            **self._put(capture.body, capture.sha256),
            "requestedUrl": capture.requested_url,
            "resolvedUrl": capture.resolved_url,
            "method": capture.method,
            "status": capture.status_code,
            "contentType": capture.content_type,
            "observedAt": capture.observed_at,
        }

    def retain_page(self, page: JsonPage) -> dict:
        """The ``on_page`` receipt a completed window pins for offline replay."""
        return self.retain(page.capture)

    def _verified_success(self, key: str, locator) -> dict | None:
        row = self.state.get(key)
        if row is None or row.get("status") not in {"captured", "requested-empty"}:
            return None
        try:
            capture = row["capture"]
            if capture["requestedUrl"] != locator.byte_url or capture["resolvedUrl"] != locator.byte_url:
                return None
            if not 200 <= capture["status"] < 300 or capture["method"] != "GET":
                return None
            if (capture["bytes"] == 0) != (row["status"] == "requested-empty"):
                return None
            for _ in iter_verified_blob(_store(self.output, capture["runId"]), capture["sha256"], capture["bytes"]):
                pass
        except (OSError, ValueError, KeyError, TypeError, BlobIntegrityError):
            return None
        return row

    def _record(self, key: str, row: dict) -> None:
        self.emit(row)
        self.state[key] = row
        self.results[key] = row["status"]

    def acquire_filing(self, record: dict, pointer: dict, acquirer: FccEcfsDocumentAcquirer) -> None:
        """Reconcile every declaration, including filings that offer no files.

        A viewer shell or redirect refuses one file and the run continues;
        every other refusal is recorded and aborts the run.
        """
        try:
            documents = declared_documents(record)
        except FccEcfsDocumentError as error:
            self.invalid_filings += 1
            self.emit(
                {
                    "kind": "invalid-filing",
                    "source": pointer,
                    "message": scrub_credential(str(error), *self._secrets)[:2000],
                }
            )
            return
        identity = str(record["id_submission"])
        if documents:
            self.empty_filings.discard(identity)
        elif identity not in self.filings:
            self.empty_filings.add(identity)
        self.filings.add(identity)
        for document in documents:
            key = json_line([document.locator.url, document.locator.filename]).decode().strip()
            if key in self.results:
                continue
            if previous := self._verified_success(key, document.locator):
                self.results[key] = previous["status"]
                self.reused += 1
                continue
            if self.max_document_attempts is not None and self.attempts >= self.max_document_attempts:
                self.results[key] = "not-requested"
                continue
            self.attempts += 1
            row = {"kind": "document", "key": key, "source": pointer, "idSubmission": identity}
            try:
                acquired = acquirer.acquire(document)
            except (FccEcfsDocumentError, CredentialRefusedError) as error:
                refused = isinstance(error, CredentialRefusedError)
                row["status"] = (
                    "refused"
                    if refused
                    else "unavailable"
                    if isinstance(error, FccEcfsDocumentUnavailableError)
                    else "failed"
                )
                row["message"] = scrub_credential(str(error), *self._secrets)[:2000]
                capture = attached_capture(error)
                if capture is not None and not refused:
                    row["capture"] = self.retain(capture)
                if isinstance(error, FccEcfsDocumentRefusedError):
                    # The document host is keyless; its refusal bytes are evidence.
                    row["refusalKind"] = error.refusal_kind
                    response = getattr(error, "refused_response", None)
                    if response is not None and response.response_bytes is not None:
                        row["refusal"] = {**self._put(response.response_bytes), "mediaType": response.media_type}
                self._record(key, row)
                if refused and getattr(error, "refusal_kind", None) not in PER_DOCUMENT_REFUSALS:
                    raise
                continue
            row.update(
                status="requested-empty" if acquired.requested_empty else "captured",
                capture=self.retain(acquired.capture),
                transport=acquired.transport.value,
                providerRequestId=acquired.request_id,
                requestCount=acquired.request_count,
            )
            self._record(key, row)

    def finish(self, *, discovery_complete: bool) -> dict:
        counts = dict(Counter(self.results.values()))
        complete = (
            discovery_complete
            and not self.invalid_filings
            and not any(counts.get(status) for status in ("failed", "refused", "not-requested"))
        )
        row = {
            "kind": "finished",
            "discoveryComplete": discovery_complete,
            "complete": complete,
            "filings": len(self.filings),
            "filingsWithoutDocuments": len(self.empty_filings),
            "invalidFilings": self.invalid_filings,
            "declaredDocuments": len(self.results),
            "outcomes": counts,
            "reusedDocuments": self.reused,
            "documentAttempts": self.attempts,
        }
        self.emit(row)
        self.commit()
        return row
