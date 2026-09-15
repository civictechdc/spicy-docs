"""Deprecated address for ``spicy_docs.reading.xml``; remove after 0.19."""

import sys

from spicy_docs.reading import xml as _moved

sys.modules[__name__] = _moved
