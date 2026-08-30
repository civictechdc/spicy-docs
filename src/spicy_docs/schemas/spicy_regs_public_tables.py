"""Stable spicy-regs public-table columns and their faithful projection.

The spicy-regs project publishes its collected regulations.gov rows as public
Parquet on ``data.spicy-regs.dev``.  Comments are published twice: as one flat
monolith and as a Hive-partitioned tree keyed by agency,
``comments/agency/agency_code={X}/part-0.parquet``.  The partition writer drops
``agency_code`` from the file — the value lives in the directory name — so the
bytes carry fifteen columns and the logical row carries sixteen.

This module states both column lists and the one projection between them.  It
holds data and a pure function only; the acquisition profile in
:mod:`spicy_docs.spicy_regs_public_tables_source_native` owns the JSON Schema,
the capture format, and every refusal.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# The partition key the publisher encodes in the directory name.
PUBLIC_COMMENT_PARTITION_KEY: str = "agency_code"

# The logical comment row, in the publisher's own column order.
PUBLIC_COMMENT_COLUMNS: tuple[str, ...] = (
    "comment_id",
    "docket_id",
    "agency_code",
    "first_name",
    "last_name",
    "organization",
    "category",
    "title",
    "comment",
    "document_type",
    "posted_date",
    "modify_date",
    "receive_date",
    "attachments_json",
    "text_content",
    "text_extraction_status",
)

# The columns the partition file itself carries: the logical row minus the
# partition key, with the publisher's order preserved.
PUBLIC_COMMENT_FILE_COLUMNS: tuple[str, ...] = tuple(
    name for name in PUBLIC_COMMENT_COLUMNS if name != PUBLIC_COMMENT_PARTITION_KEY
)

# Columns the source profile treats as this row's identity and its version.
PUBLIC_COMMENT_IDENTITY_COLUMN: str = "comment_id"
PUBLIC_COMMENT_VERSION_COLUMN: str = "modify_date"


def project_public_comment_row(
    row: Mapping[str, Any],
    *,
    agency_code: str,
) -> dict[str, str | None]:
    """Rejoin one partition-file row with its partition key, faithfully.

    Every declared column appears in the publisher's order, including the
    columns the publisher left null.  Nothing is cleaned, trimmed, or dropped:
    a ``comment`` reading ``See attached`` is a fact about the source at this
    layer, not noise.
    """

    projected: dict[str, str | None] = {}
    for name in PUBLIC_COMMENT_COLUMNS:
        if name == PUBLIC_COMMENT_PARTITION_KEY:
            projected[name] = agency_code
            continue
        projected[name] = row[name]
    return projected


__all__ = [
    "PUBLIC_COMMENT_COLUMNS",
    "PUBLIC_COMMENT_FILE_COLUMNS",
    "PUBLIC_COMMENT_IDENTITY_COLUMN",
    "PUBLIC_COMMENT_PARTITION_KEY",
    "PUBLIC_COMMENT_VERSION_COLUMN",
    "project_public_comment_row",
]
