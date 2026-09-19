"""The one GovInfo error page and its two witnesses, importable on its own.

GovInfo answers a missing package or an unoffered rendition with a redirect to
``https://www.govinfo.gov/error``, and that page answers HTTP 200. A caller
that follows redirects therefore receives a 200 that is not the requested
object. Two independent witnesses say so: the final URL the response came
from, and the page's own link to that address in its bytes.

They stay separable because callers interleave them differently. The Federal
Register granule validator refuses an error-page URL, then a mismatched
locator, then the body marker, so a marker-bearing body at the wrong locator
reports the locator. The package body validator has no marker of its own to
fall back on and refuses on either witness at once.

This module imports nothing from ``spicy_docs``: a pure validator that needs
only this rule should not have to import a source family to get it. Checking
costs ``O(B)`` for body bytes ``B``; no request is made and no file is written.
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
