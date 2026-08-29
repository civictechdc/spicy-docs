"""Shared data shapes that flow between sources and transforms.

``base`` holds the generic :class:`RecordType` contract; domain-specific
record definitions (e.g. the regulations.gov shapes) live alongside it and
are re-exported here for convenience.
"""

from spicy_docs.schemas.base import RecordType
from spicy_docs.schemas.regulations import COMMENT, DOCKET, DOCUMENT, RECORD_TYPES

__all__ = ["COMMENT", "DOCKET", "DOCUMENT", "RECORD_TYPES", "RecordType"]
