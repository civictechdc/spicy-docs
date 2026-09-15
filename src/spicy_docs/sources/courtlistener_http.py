"""Deprecated address for ``spicy_docs.sources.courtlistener.http``; remove after 0.19."""

import sys

from spicy_docs.sources.courtlistener import http as _moved

sys.modules[__name__] = _moved
