"""Deprecated address for ``spicy_docs.reading.evidence_zip``; remove after 0.19."""

import sys

from spicy_docs.reading import evidence_zip as _moved

sys.modules[__name__] = _moved
