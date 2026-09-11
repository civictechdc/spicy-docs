"""Publisher aliases and URL fallbacks produce stable rendition metadata."""

import pytest

from spicy_docs.sources.media_types import media_type


@pytest.mark.parametrize(
    ("stated", "locator", "expected"),
    [
        (" PDF ", "https://example.test/file.txt", "application/pdf"),
        (" Application/XML ", "", "application/xml"),
        ("doc", "", "application/msword"),
        ("docx", "", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("htm", "", "text/html"),
        (None, "https://example.test/file.TXT?download=1", "text/plain"),
        (None, "https://example.test/file.xml", "application/xml"),
        ("unknown", "https://example.test/file.pdf", "application/pdf"),
        (None, "https://example.test/file.bin", "application/octet-stream"),
        (None, "", "application/octet-stream"),
    ],
)
def test_publisher_type_takes_precedence_over_url(stated: object, locator: str, expected: str) -> None:
    assert media_type(stated, locator) == expected
