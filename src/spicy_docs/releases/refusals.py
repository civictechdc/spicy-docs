"""Retain bounded diagnostic evidence without publishing a partial release."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from itertools import islice
from typing import Any

from rulespec_artifacts import MemberDescriptor

from spicy_docs.releases.format import MAX_EVIDENCE_BYTES
from spicy_docs.releases.profile import SourceNativePage
from spicy_docs.sources.refusals import RefusedResponse, attach_refused_response
from spicy_docs.storage.blobs import SourceNativeBlobStore
from spicy_docs.transport.credentials import scrub_credential

_CONTEXT_LIMIT = 8
_MEDIA_TYPES = {"application/json", "application/zip", "text/html", "application/octet-stream"}


@contextmanager
def capture_refused_page(page: SourceNativePage) -> Iterator[None]:
    """Only this page's checks may identify it as the refused response.

    Iteration happens outside this context: a later fetch failure must never
    inherit the last successful page's bytes.
    """
    try:
        yield
    except Exception as error:
        payload = page.response_bytes
        size = len(payload) if isinstance(payload, bytes) else None
        reason = None
        if size is None:
            reason = "unsupported-response"
        elif size > MAX_EVIDENCE_BYTES:
            reason = "response-byte-limit"
        attach_refused_response(
            error,
            RefusedResponse(
                request_key=page.request_key,
                stage="page-validation",
                response_bytes=payload if reason is None else None,
                media_type=page.evidence_media_type,
                unavailable_reason=reason,
                observed_byte_size=size,
            ),
        )
        raise


def _retain_response(
    response: RefusedResponse | None,
    *,
    blob_store: SourceNativeBlobStore,
    evidence_members: Mapping[str, MemberDescriptor],
) -> dict[str, Any]:
    if response is None:
        return {"status": "not-retained", "reason": "response-unavailable"}
    request_key = scrub_credential(response.request_key, "")
    result: dict[str, Any] = {
        "requestKey": request_key[:4096],
        "requestKeyTruncated": len(request_key) > 4096,
        "stage": response.stage,
        "status": "not-retained",
    }
    payload = response.response_bytes
    size = len(payload) if payload is not None else response.observed_byte_size
    if size is not None:
        result["byteSize"] = size
    if response.unavailable_reason is not None or payload is None:
        result["reason"] = response.unavailable_reason or "response-unavailable"
        return result
    if len(payload) > MAX_EVIDENCE_BYTES:
        result["reason"] = "response-byte-limit"
        return result
    blob_ref = "sha256:" + hashlib.sha256(payload).hexdigest()
    try:
        if blob_ref not in evidence_members:
            blob_store.put_blob(blob_ref, len(payload), (payload,))
    except Exception:  # noqa: BLE001 - diagnostic storage must not replace the original failure
        # Storage diagnostics can include credentials/paths. The original
        # source error remains the cause of failure; report only this status.
        result["reason"] = "storage-failed"
        return result
    result.update(
        status="retained",
        blobRef=blob_ref,
        mediaType=response.media_type if response.media_type in _MEDIA_TYPES else "application/octet-stream",
    )
    return result


def record_failed_acquisition(
    error: Exception,
    *,
    source_system_id: str,
    blob_store: SourceNativeBlobStore,
    evidence_members: dict[str, MemberDescriptor],
) -> None:
    """Expose the error's response and a bounded sample of earlier page evidence.

    The sample is context, not a claim that earlier responses were rejected.
    Caller-held errors and the CLI's stderr report are the existing failed-run
    output; no sibling artifact or successful-looking release is created.
    """
    response = getattr(error, "refused_response", None)
    if not isinstance(response, RefusedResponse):
        response = None
    references = [
        {"blobRef": ref, "byteSize": evidence_members[ref].byte_size, "mediaType": evidence_members[ref].media_type}
        for ref in islice(reversed(evidence_members), _CONTEXT_LIMIT)
    ]
    error.__dict__["failed_acquisition"] = {
        "sourceSystemId": source_system_id,
        "response": _retain_response(response, blob_store=blob_store, evidence_members=evidence_members),
        "retainedPageEvidence": {
            "contextOnly": True,
            "count": len(evidence_members),
            "references": references,
            "truncated": len(evidence_members) > len(references),
        },
    }
