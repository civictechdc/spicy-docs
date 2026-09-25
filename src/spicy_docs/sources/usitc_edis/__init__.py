"""USITC EDIS investigation dockets: XML list pages, attachment metadata and the public notification feed.

The Electronic Document Information System serves investigation, document and
attachment metadata as XML under ``https://edis.usitc.gov/data`` (documented
in USITC's 2024 ``edis_data_web_service_guide.pdf``), and
notifies newly arriving documents through an RSS 2.0 feed under
``/external/rss/render.rss``. Both were verified alive on 2026-09-24.
"""

from __future__ import annotations

from spicy_docs.sources.usitc_edis.api import (
    DEFAULT_MAX_PAGES,
    PAGE_SIZE,
    EdisAcquirer,
    EdisBudget,
    EdisPage,
    attachment_url,
    check_edis_data_url,
    document_list_url,
    document_url,
    investigation_url,
)
from spicy_docs.sources.usitc_edis.attachments import (
    AttachmentDownload,
    attachment_download_locator,
    attachment_download_url,
    read_attachment_pdf,
)
from spicy_docs.sources.usitc_edis.bulk import EdisBulkArchive, EdisBulkIndexRow, inspect_bulk_archive
from spicy_docs.sources.usitc_edis.feed import EdisFeedItem, EdisNotificationFeed, parse_edis_feed
from spicy_docs.sources.usitc_edis.reader import UsitcEdisReader
from spicy_docs.sources.usitc_edis.records import (
    AttachmentRecord,
    DocumentRecord,
    Investigation,
    UsitcEdisSourceError,
    UsitcEdisUnavailableError,
    check_edis_id,
    parse_attachments,
    parse_documents,
    parse_investigations,
)

__all__ = [
    "DEFAULT_MAX_PAGES",
    "PAGE_SIZE",
    "AttachmentDownload",
    "AttachmentRecord",
    "DocumentRecord",
    "EdisAcquirer",
    "EdisBudget",
    "EdisBulkArchive",
    "EdisBulkIndexRow",
    "EdisFeedItem",
    "EdisNotificationFeed",
    "EdisPage",
    "Investigation",
    "UsitcEdisReader",
    "UsitcEdisSourceError",
    "UsitcEdisUnavailableError",
    "attachment_download_locator",
    "attachment_download_url",
    "attachment_url",
    "check_edis_data_url",
    "check_edis_id",
    "document_list_url",
    "document_url",
    "inspect_bulk_archive",
    "investigation_url",
    "parse_attachments",
    "parse_documents",
    "parse_edis_feed",
    "parse_investigations",
    "read_attachment_pdf",
]
