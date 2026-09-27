"""Keep a read attachment relationship distinct from document content renditions."""

import json
from collections.abc import Mapping
from typing import Any

from .api import AttachmentRelationship, document_attachments_url, read_attachment_relationship
from .attachments import declared_files


def attachment_records_json(document: Mapping[str, Any], relationship: AttachmentRelationship | None) -> str | None:
    """Caller supplies edition association; this helper verifies identity, never fetches.

    Included records alone do not establish that the complete relationship was read.
    Native records retain their array order, IDs, restrictions and format alternatives.
    """
    if relationship is None:
        return None
    if relationship.document_id != document.get("data", {}).get("id"):
        raise ValueError("Attachment relationship names a different document")
    expected_url = document_attachments_url(relationship.document_id)
    capture = relationship.capture
    if capture.status_code != 200 or capture.requested_url != expected_url or capture.resolved_url != expected_url:
        raise ValueError("Attachment capture is not a successful response for this document relationship")
    checked = read_attachment_relationship(relationship.capture, identity=relationship.document_id)
    if checked.records != relationship.records:
        raise ValueError("Attachment records differ from captured response")
    for record in checked.records:
        declared_files(record)
    return json.dumps(list(relationship.records), ensure_ascii=False)
