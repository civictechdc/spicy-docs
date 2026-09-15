"""Deprecated address for ``spicy_docs.sources.unified_agenda.records``; remove after 0.19."""

import sys

from spicy_docs.sources.unified_agenda import records as _moved

sys.modules[__name__] = _moved
