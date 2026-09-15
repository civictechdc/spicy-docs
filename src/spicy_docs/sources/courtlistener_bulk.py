"""Deprecated address for ``spicy_docs.sources.courtlistener.bulk``; remove after 0.19."""

import sys

from spicy_docs.sources.courtlistener import bulk as _moved

sys.modules[__name__] = _moved
