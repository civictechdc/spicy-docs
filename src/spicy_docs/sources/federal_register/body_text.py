"""Identify the publisher's text rendition, which may have an HTML pre wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .body_sources import (
    FederalRegisterBodySourceError,
    _matching_document_marker,
    _validated_max_bytes,
    _validated_publication_date,
    _validated_source_id,
)


@dataclass(frozen=True, slots=True)
class PublisherTextIdentity:
    source_document_number: str
    marker_document_number: str
    publication_date: str
    match_kind: Literal["exact-source", "split-base"]


def publisher_text_locator(document_number: str, publication_date: str) -> str:
    """Return the canonical text URL for the explicit source record."""
    source_id = _validated_source_id(document_number, label="document_number")
    safe_date = _validated_publication_date(publication_date)
    return f"https://www.federalregister.gov/documents/full_text/text/{safe_date.replace('-', '/')}/{source_id}.txt"


def validate_publisher_text(
    body: bytes,
    *,
    source_document_number: str,
    publication_date: str,
    final_url: str,
    max_bytes: int,
) -> PublisherTextIdentity:
    """Check canonical URL and the printed header without rewriting bytes.

    The header establishes the document number; the URL binds the requested
    publication date. The footer's filing date and number remain separate facts.
    """
    exact = _validated_max_bytes(body, max_bytes, label="publisher text")
    source_id = _validated_source_id(source_document_number, label="document_number")
    safe_date = _validated_publication_date(publication_date)
    if final_url != publisher_text_locator(source_id, safe_date):
        raise FederalRegisterBodySourceError("publisher text final URL differs from the requested locator")
    matched = _matching_document_marker(exact, source_id)
    if matched is None:
        raise FederalRegisterBodySourceError("publisher text does not carry the requested document marker")
    marker_number, match_kind = matched
    return PublisherTextIdentity(source_id, marker_number, safe_date, match_kind)


__all__ = ["PublisherTextIdentity", "publisher_text_locator", "validate_publisher_text"]
