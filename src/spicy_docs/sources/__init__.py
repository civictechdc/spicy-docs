"""Acquisition readers included in the spicy-docs source-native layer.

Import readers from their own submodule
(``from spicy_docs.sources.mirrulations import MirrulationsReader``) rather
than from here. Re-exporting them at package level made every
``spicy_docs.sources.*`` import — including the stdlib-only Zyte transport the
source-native read path needs — drag in boto3, loguru, and tqdm, which broke
DocSpec's ``--no-deps`` install of the producer wheel.

Upstream spicy-regs' ``sources`` package carries many more readers
(bill_subjects, cfr_sections, congress_bills, fcc_ecfs, unified_agenda, pdf,
iceberg, r2, ...). Those belong to sibling/rollup products and were
deliberately left out of this extraction.
"""

from spicy_docs.sources.base import Reader, Writer

__all__ = ["Reader", "Writer"]
