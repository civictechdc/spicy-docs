"""Deprecated address for ``spicy_docs.sources.uscode.structure``; remove after 0.19."""

import sys

from spicy_docs.sources.uscode import structure as _moved

sys.modules[__name__] = _moved
