"""Deprecated address for ``spicy_docs.sources.uscode.acquisition``; remove after 0.19."""

import sys

from spicy_docs.sources.uscode import acquisition as _moved

sys.modules[__name__] = _moved
