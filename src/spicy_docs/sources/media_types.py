"""Deprecated address for ``spicy_docs.reading.media_types``; remove after 0.19."""

import sys

from spicy_docs.reading import media_types as _moved

sys.modules[__name__] = _moved
