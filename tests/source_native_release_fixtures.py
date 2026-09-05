"""Hand-built source-native release fixtures for the receipt-helper tools.

``tools/fr_discarded_distinctness.py`` and
``tools/compare_source_native_releases.py`` both read a release the same
low-level way -- manifest, receipt, and blobs through
``LocalSourceNativeBlobStore`` -- without going through
``SourceNativeReleaseReader``/``admit_artifact``. So both need the same
fixture shape, and it lived twice until 2026-09-05.

These fixtures are written by hand rather than produced by the publisher on
purpose: a fixture the writer generates cannot catch the writer being wrong,
and these tools exist to check the writer.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from spicy_docs.source_native import ROLE_EVIDENCE, ROLE_RECORDS
from spicy_docs.source_native_store import LocalSourceNativeBlobStore


def store_at(tmp_path: Path) -> LocalSourceNativeBlobStore:
    """Open (creating if needed) the blob store every fixture release shares."""
    return LocalSourceNativeBlobStore(tmp_path / "blobs")


def put_bytes(store: LocalSourceNativeBlobStore, data: bytes) -> str:
    blob_ref = "sha256:" + hashlib.sha256(data).hexdigest()
    store.put_blob(blob_ref, len(data), [data])
    return blob_ref


def put_json(store: LocalSourceNativeBlobStore, obj: Any) -> str:
    return put_bytes(store, json.dumps(obj).encode())


def put_jsonl(store: LocalSourceNativeBlobStore, rows: list[dict[str, Any]]) -> str:
    return put_bytes(store, ("\n".join(json.dumps(row) for row in rows) + "\n").encode())


def member(role: str, blob_ref: str) -> dict[str, str]:
    return {"role": role, "blobRef": blob_ref}


def write_release(
    release_root: Path,
    *,
    members: list[dict[str, str]],
    receipt: dict[str, Any],
) -> Path:
    """Write the manifest and receipt a tool reads directly. Returns the root."""
    manifests_dir = release_root / "manifests"
    manifests_dir.mkdir(parents=True)
    (manifests_dir / "source-native.json").write_text(json.dumps({"members": members}))
    receipts_dir = release_root / "receipts"
    receipts_dir.mkdir(parents=True)
    (receipts_dir / "publication.json").write_text(json.dumps(receipt))
    # Real releases carry artifact.json, and tools read artifactDigest from it to
    # pin which corpus a derived row was computed against. Deriving it from the
    # members keeps it deterministic and gives two different fixtures two
    # different digests, which is what a guard against mixing them needs.
    digest = hashlib.sha256(json.dumps(members, sort_keys=True).encode()).hexdigest()
    (release_root / "artifact.json").write_text(
        json.dumps({"artifactDigest": f"sha256:{digest}"})
    )
    return release_root


def records_release(
    tmp_path: Path,
    name: str,
    record_lines: list[dict[str, Any]],
    receipt: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """A release carrying only records. Returns (release_root, blob_store_path)."""
    store = store_at(tmp_path)
    blob = put_jsonl(store, record_lines)
    root = write_release(
        tmp_path / name,
        members=[member(ROLE_RECORDS, blob)],
        receipt=receipt if receipt is not None else {"publishedRecordCount": len(record_lines)},
    )
    return root, tmp_path / "blobs"


def evidence_and_records_release(
    tmp_path: Path,
    *,
    evidence_rows: list[dict[str, Any]],
    record_lines: list[dict[str, Any]],
    receipt: dict[str, int],
    name: str = "release",
) -> tuple[Path, Path]:
    """A release carrying one evidence page and one records member."""
    store = store_at(tmp_path)
    evidence_blob = put_json(store, {"results": evidence_rows})
    records_blob = put_jsonl(store, record_lines)
    root = write_release(
        tmp_path / name,
        members=[member(ROLE_EVIDENCE, evidence_blob), member(ROLE_RECORDS, records_blob)],
        receipt=receipt,
    )
    return root, tmp_path / "blobs"
