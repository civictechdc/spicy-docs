"""Deprecated address for ``spicy_docs.source_native.store``; remove after 0.19."""

import sys

from spicy_docs.source_native import store as _moved

sys.modules[__name__] = _moved
