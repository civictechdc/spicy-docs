"""Deprecated address for ``spicy_docs.sources.agency_reports.foia``; remove after 0.19."""

import sys

from spicy_docs.sources.agency_reports import foia as _moved

sys.modules[__name__] = _moved
