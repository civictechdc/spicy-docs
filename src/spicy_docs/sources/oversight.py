"""Deprecated address for ``spicy_docs.sources.agency_reports.oversight``; remove after 0.19."""

import sys

from spicy_docs.sources.agency_reports import oversight as _moved

sys.modules[__name__] = _moved
