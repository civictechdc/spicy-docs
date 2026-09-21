"""media_type maps publisher aliases and URL fallbacks to stable rendition media types.

A stated publisher type wins over the URL; otherwise the last path segment's suffix decides, and anything
unrecognized becomes application/octet-stream."""

import pytest

from spicy_docs.reading.media_types import media_type


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
        (" JSON ", "https://example.test/file.pdf", "application/json"),
        (None, "https://example.test/file.JSON?download=1#content", "application/json"),
        (None, "https://www.fec.gov/data/", "application/octet-stream"),
        (None, "https://example.test/path.xml/child", "application/octet-stream"),
        (None, "https://example.test/path.xml/", "application/octet-stream"),
        (None, "https://example.test/file.csv#columns", "text/csv"),
        (None, "https://example.test/?download=file.pdf", "application/octet-stream"),
        (None, "https://[invalid/file.json", "application/octet-stream"),
        ("unknown", "https://example.test/file.pdf", "application/pdf"),
        (None, "https://example.test/file.bin", "application/octet-stream"),
        (None, "", "application/octet-stream"),
    ],
)
def test_publisher_type_takes_precedence_over_url(stated: object, locator: str, expected: str) -> None:
    assert media_type(stated, locator) == expected


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("xhtml", "application/xhtml+xml"),
        ("csv", "text/csv"),
        ("ics", "text/calendar"),
        ("fec", "text/plain"),
        ("zip", "application/zip"),
        ("gz", "application/gzip"),
        ("bz2", "application/x-bzip2"),
        ("xls", "application/vnd.ms-excel"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("mp3", "audio/mpeg"),
        ("mp4", "video/mp4"),
    ],
)
def test_additional_publisher_aliases(alias: str, expected: str) -> None:
    assert media_type(alias, "") == expected
