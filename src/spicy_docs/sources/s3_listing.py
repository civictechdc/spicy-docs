"""Deprecated address for ``spicy_docs.reading.s3_listing``; remove after 0.19."""

import sys

from spicy_docs.reading import s3_listing as _moved

sys.modules[__name__] = _moved
