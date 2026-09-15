"""Deprecated address for ``spicy_docs.reading.pdf_bytes``; remove after 0.19."""

import sys

from spicy_docs.reading import pdf_bytes as _moved

sys.modules[__name__] = _moved
