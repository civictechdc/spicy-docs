"""Deprecated address for ``spicy_docs.reading.json_input``; remove after 0.19."""

import sys

from spicy_docs.reading import json_input as _moved

sys.modules[__name__] = _moved
