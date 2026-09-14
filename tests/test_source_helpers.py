"""The shared checks every document route calls: the final URL and the PDF bytes."""

import pytest

from spicy_docs.sources.pdf_bytes import TRAILER_WINDOW, check_pdf_bytes
from spicy_docs.transport.source_acquirer import check_final_url


class RouteError(ValueError):
    pass


def test_final_url_must_equal_the_locator():
    check_final_url("https://x.gov/a.pdf", "https://x.gov/a.pdf", error_type=RouteError, message="differs")
    with pytest.raises(RouteError, match="differs"):
        check_final_url("https://x.gov/a.pdf?x=1", "https://x.gov/a.pdf", error_type=RouteError, message="differs")


def test_pdf_bytes_need_the_magic_and_a_trailer_within_the_last_kilobyte():
    body = b"%PDF-1.7\n" + b"x" * 40 + b"\n%%EOF\n"
    assert check_pdf_bytes(body, error_type=RouteError, label="doc") == "1.7"
    assert check_pdf_bytes(bytearray(body), error_type=RouteError, label="doc") == "1.7"
    for bad, message in (
        (b"", "empty"),
        (b"<html>challenge</html>", "PDF- magic"),
        (b" %PDF-1.7\n%%EOF\n", "PDF- magic"),
        (b"%PDF1.7\n%%EOF\n", "PDF- magic"),
        (b"%PDF-1.7\n" + b"x" * 2048, "trailer"),
        (b"%PDF-1.7\n%%EOF\n" + b"x" * (TRAILER_WINDOW + 1), "trailer"),
    ):
        with pytest.raises(RouteError, match=message):
            check_pdf_bytes(bad, error_type=RouteError, label="doc")
