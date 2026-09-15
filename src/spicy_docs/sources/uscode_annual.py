"""Deprecated address for ``spicy_docs.sources.uscode.annual``; remove after 0.19."""

import sys

from spicy_docs.sources.uscode import annual as _moved

sys.modules[__name__] = _moved
