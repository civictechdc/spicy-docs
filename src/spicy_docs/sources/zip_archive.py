"""Deprecated address for ``spicy_docs.reading.zip_archive``; remove after 0.19."""

import sys

from spicy_docs.reading import zip_archive as _moved

sys.modules[__name__] = _moved
