"""Deprecated address for ``spicy_docs.source_native.regulations_gov``; remove after 0.19."""

import sys

from spicy_docs.source_native import regulations_gov as _moved

sys.modules[__name__] = _moved
