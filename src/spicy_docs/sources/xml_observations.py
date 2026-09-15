"""Deprecated address for ``spicy_docs.reading.xml_observations``; remove after 0.19."""

import sys

from spicy_docs.reading import xml_observations as _moved

sys.modules[__name__] = _moved
