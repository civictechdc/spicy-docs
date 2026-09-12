"""Source-native reads and receipt mapping over Rulespec's local blob writer."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from rulespec_artifacts import BlobIntegrityError, BlobLimitError, LocalBlobSource, LocalBlobWriter

from spicy_docs.storage.publication import ImmutablePublicationError


@dataclass(frozen=True, slots=True)
class SourceNativeBlobWrite:
    """Observed effect of one conditional CAS write."""

    blob_ref: str
    byte_size: int
    reused: bool
    bytes_written: int


@runtime_checkable
class SourceNativeBlobStore(Protocol):
    """The one injected read/write boundary used by source-native publication."""

    def put_blob(
        self,
        blob_ref: str,
        byte_size: int,
        chunks: Iterable[bytes],
    ) -> SourceNativeBlobWrite: ...

    def open(self, blob_ref: str) -> AbstractContextManager[BinaryIO]: ...


class LocalSourceNativeBlobStore:
    """One explicitly selected local blob store with the source receipt shape."""

    def __init__(self, root: Path, *, create: bool = True) -> None:
        self._writer = LocalBlobWriter(root, create=create)
        self.root = self._writer.root
        self._reader = LocalBlobSource(self.root)

    @contextmanager
    def open(self, blob_ref: str) -> Iterator[BinaryIO]:
        with self._reader.open(blob_ref) as stream:
            yield stream

    def put_blob(
        self,
        blob_ref: str,
        byte_size: int,
        chunks: Iterable[bytes],
    ) -> SourceNativeBlobWrite:
        """Write within the declared size, or reuse independently verified bytes."""

        try:
            result = self._writer.put(chunks, max_bytes=byte_size, expected_digest=blob_ref, expected_size=byte_size)
        except (BlobIntegrityError, BlobLimitError) as error:
            raise ImmutablePublicationError(str(error)) from error
        return SourceNativeBlobWrite(result.digest, result.byte_size, result.reused, result.bytes_written)


__all__ = [
    "LocalSourceNativeBlobStore",
    "SourceNativeBlobStore",
    "SourceNativeBlobWrite",
]
