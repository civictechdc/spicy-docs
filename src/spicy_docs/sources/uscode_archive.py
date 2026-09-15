"""Deprecated address for ``spicy_docs.sources.uscode.archive``; remove after 0.19."""

import sys

from spicy_docs.sources.uscode import archive as _moved

sys.modules[__name__] = _moved
