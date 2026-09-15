"""Deprecated address for ``spicy_docs.reading.paged_json``; remove after 0.19."""

import sys

from spicy_docs.reading import paged_json as _moved

sys.modules[__name__] = _moved
