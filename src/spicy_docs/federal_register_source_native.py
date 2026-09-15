"""Deprecated address for ``spicy_docs.source_native.federal_register``; remove after 0.19."""

import sys

from spicy_docs.source_native import federal_register as _moved

sys.modules[__name__] = _moved
