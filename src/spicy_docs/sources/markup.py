"""Deprecated address for ``spicy_docs.reading.markup``; remove after 0.19."""

import sys

from spicy_docs.reading import markup as _moved

sys.modules[__name__] = _moved
