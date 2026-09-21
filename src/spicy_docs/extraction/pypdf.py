"""Raw embedded PDF page text through the optional pypdf backend."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from typing import TYPE_CHECKING

from .model import ExtractionError

if TYPE_CHECKING:
    from pypdf import PdfReader


class PdfReadError(ExtractionError):
    """The configured PDF backend could not read the source."""


class PdfEncryptedError(PdfReadError):
    """The PDF requires an explicitly selected, accepted password."""


class PdfPageError(PdfReadError):
    """One page failed; its number and original exception remain available."""

    def __init__(self, page: int, message: str):
        super().__init__(message)
        self.page = page


class PypdfDocument:
    """An open PDF. Page strings retain the backend's exact whitespace.

    A closed document refuses further page reads with ``ValueError``.
    """

    def __init__(self, reader: PdfReader, backend_version: str):
        """Wrap an opened reader; ``backend_version`` is the verified installed distribution version."""
        self._reader = reader
        self.backend_version = backend_version
        self.is_encrypted = reader.is_encrypted
        self.page_count = len(reader.pages)
        self._closed = False

    def read_page(self, number: int) -> str | None:
        """Read a one-based page; no text and a failed read stay distinct."""
        if self._closed:
            raise ValueError("PDF document is closed")
        if type(number) is not int or not 1 <= number <= self.page_count:
            raise ValueError("page number must be an integer within the PDF's page count")
        try:
            text = self._reader.pages[number - 1].extract_text()
            if text is not None and not isinstance(text, str):
                raise TypeError("pypdf page text must be a string or None")
            return text
        except Exception as error:
            raise PdfPageError(number, f"PDF page {number} could not be read: {error}") from error


class PypdfReader:
    """Open retained PDF bytes without importing pypdf until use.

    The input byte limit does not bound PDF decompression, extraction time, or
    output size. Applications own those execution limits and all page policy.
    """

    def __init__(self, *, expected_backend_version: str | None = None, max_input_bytes: int = 64 * 1024**2):
        if type(max_input_bytes) is not int or max_input_bytes < 1:
            raise ValueError("max_input_bytes must be a positive integer")
        if expected_backend_version is not None and (
            not isinstance(expected_backend_version, str) or not expected_backend_version.strip()
        ):
            raise ValueError("expected_backend_version must be a nonempty version string")
        self.expected_backend_version = expected_backend_version
        self.max_input_bytes = max_input_bytes

    @contextmanager
    def open(self, source: bytes, *, password: str | None = None) -> Iterator[PypdfDocument]:
        """Own one reader until context exit; caller exceptions propagate intact.

        ``password=None`` refuses every encrypted PDF, including those readable
        with an empty password. Pass ``password=""`` to explicitly allow that
        attempt. A page error never becomes an empty page in this reader.
        """
        if not isinstance(source, bytes) or not source:
            raise ValueError("source must be nonempty PDF bytes")
        if len(source) > self.max_input_bytes:
            raise ValueError("source exceeds max_input_bytes")
        if password is not None and not isinstance(password, str):
            raise ValueError("password must be a string or None")
        try:
            installed_version = version("pypdf")
            provider = import_module("pypdf")
        except (ImportError, PackageNotFoundError) as error:
            raise PdfReadError("PDF page reading requires spicy-docs[pdf-pypdf]") from error
        if getattr(provider, "__version__", None) != installed_version:
            raise PdfReadError("loaded pypdf version differs from its installed distribution version")
        if self.expected_backend_version is not None and installed_version != self.expected_backend_version:
            raise PdfReadError("installed pypdf version differs from expected_backend_version")

        with BytesIO(source) as stream:
            try:
                reader = provider.PdfReader(stream, strict=False)
            except Exception as error:
                raise PdfReadError(f"PDF could not be opened: {error}") from error
            document = None
            try:
                try:
                    if reader.is_encrypted:
                        if password is None:
                            raise PdfEncryptedError("encrypted PDF requires an explicit password choice")
                        try:
                            accepted = reader.decrypt(password)
                        except Exception as error:
                            raise PdfEncryptedError(f"PDF password could not be applied: {error}") from error
                        if not accepted:
                            raise PdfEncryptedError("PDF password was not accepted")
                    document = PypdfDocument(reader, installed_version)
                except PdfReadError:
                    raise
                except Exception as error:
                    raise PdfReadError(f"PDF page inventory could not be read: {error}") from error
                yield document
            finally:
                if document is not None:
                    document._closed = True
                reader.close()
