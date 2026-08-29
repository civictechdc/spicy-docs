"""Acquisition readers included in the spicy-docs source-native layer.

Upstream spicy-regs' ``sources`` package re-exports many more readers
(bill_subjects, cfr_sections, congress_bills, fcc_ecfs, unified_agenda, pdf,
iceberg, r2, ...). Those belong to sibling/rollup products and were
deliberately left out of this extraction, so this ``__init__`` only
re-exports the readers that actually live in this repository.
"""

from spicy_docs.sources.base import Reader, Writer
from spicy_docs.sources.courtlistener_bulk import CourtListenerBulkReader
from spicy_docs.sources.mirrulations import MirrulationsReader

__all__ = [
    "CourtListenerBulkReader",
    "MirrulationsReader",
    "Reader",
    "Writer",
]
