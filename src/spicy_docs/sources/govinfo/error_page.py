"""The one GovInfo error page and its two independent witnesses.

A missing package or an unoffered rendition redirects to
``https://www.govinfo.gov/error``, which answers HTTP 200, so a caller that
follows redirects receives a 200 that is not the requested object; the final URL
the response came from and the page's own link to that address in its bytes both
say so. The witnesses stay separable because callers interleave them
differently, and this module imports nothing from ``spicy_docs``.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

#: Where the publisher sends a request for an object it does not have.
ERROR_PAGE_URL = "https://www.govinfo.gov/error"
_ERROR_PAGE_HOST = ("https", "www.govinfo.gov", "/error")
#: The page links to its own address; its measured 44,165-byte length is that
#: page's size today, not an identity rule.
_ERROR_PAGE_MARKER = re.compile(rb"govinfo\.gov/error", re.IGNORECASE)


def is_error_page_url(final_url: str) -> bool:
    """The response came from the error page, whatever query it carries."""
    parsed = urlsplit(final_url)
    return (parsed.scheme, parsed.netloc, parsed.path) == _ERROR_PAGE_HOST


def has_error_page_marker(body: bytes) -> bool:
    """The bytes carry the error page's link to itself."""
    return _ERROR_PAGE_MARKER.search(body) is not None


def check_not_error_page(body: bytes, final_url: str, *, error_type: type[ValueError], message: str) -> None:
    """Refuse on either witness; the caller supplies its own wording."""
    if is_error_page_url(final_url) or has_error_page_marker(body):
        raise error_type(message)


__all__ = [
    "ERROR_PAGE_URL",
    "check_not_error_page",
    "has_error_page_marker",
    "is_error_page_url",
]
