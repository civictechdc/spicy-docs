"""Deprecated address for ``spicy_docs.sources.courtlistener.csv``; remove after 0.19."""

import sys

from spicy_docs.sources.courtlistener import csv as _moved

sys.modules[__name__] = _moved
