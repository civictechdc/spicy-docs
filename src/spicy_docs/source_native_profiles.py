"""Deprecated address for ``spicy_docs.source_native.profiles``; remove after 0.19."""

import sys

from spicy_docs.source_native import profiles as _moved

sys.modules[__name__] = _moved
