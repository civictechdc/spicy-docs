"""Deprecated address for ``spicy_docs.reading.refusals``; remove after 0.19."""

import sys

from spicy_docs.reading import refusals as _moved

sys.modules[__name__] = _moved
