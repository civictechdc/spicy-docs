"""Deprecated address for ``spicy_docs.reading.xml_tree``; remove after 0.19."""

import sys

from spicy_docs.reading import xml_tree as _moved

sys.modules[__name__] = _moved
