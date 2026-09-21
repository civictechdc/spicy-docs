"""PypdfReader contract: a pinned backend version over a retained publisher PDF, one-based integer page
selection, explicit-password decryption, and distinct errors for unreadable sources, broken pages and a missing
optional backend -- with the backend imported only when a read is opened.
"""

import subprocess
import sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pypdf
import pytest
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from spicy_docs.extraction.pypdf import PdfEncryptedError, PdfPageError, PdfReadError, PypdfReader

SOURCE = (
    Path(__file__).parents[1] / "fixtures/regulations_gov_attachments/FAA-2016-6907-0001-content.pdf"
).read_bytes()
SOURCE_TEXT = (
    "Comment Info: =================\nGeneral Comment:Rank Investigation and Protection, Inc. - Exemption/Rulemaking"
)


def generated_pdf(*texts: str | None, password: str | None = None, broken_page: int | None = None) -> bytes:
    writer = pypdf.PdfWriter()
    for number, text in enumerate(texts, 1):
        page = writer.add_blank_page(width=612, height=792)
        if text is not None:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 72 720 Td (" + text.encode("ascii") + b") Tj ET")
            page[NameObject("/Contents")] = stream
        if number == broken_page:
            # A syntactically valid PDF whose page has the wrong Resources type.
            page[NameObject("/Resources")] = NumberObject(9)
    if password is not None:
        writer.encrypt(user_password=password, owner_password="owner", algorithm="RC4-128")
    out = BytesIO()
    writer.write(out)
    writer.close()
    return out.getvalue()


def test_complete_retained_publisher_pdf_has_known_text():
    assert len(SOURCE) == 2620
    assert sha256(SOURCE).hexdigest() == "f4494ea77d0f8a0ec0b6e7f64e20c6ffe6c53d3be47cd59245f42f74036a7fc0"
    with PypdfReader(expected_backend_version=pypdf.__version__).open(SOURCE) as document:
        assert document.backend_version == pypdf.__version__
        assert document.page_count == 1
        assert document.is_encrypted is False
        assert document.read_page(1) == SOURCE_TEXT


def test_actual_pdf_preserves_blank_and_whitespace_pages():
    source = generated_pdf("  Page one  ", None, "    ", "Page four")
    with PypdfReader().open(source) as document:
        assert document.page_count == 4
        assert [document.read_page(i) for i in range(1, 5)] == ["  Page one  ", "", "    ", "Page four"]


def test_real_page_failure_is_not_a_blank_page_and_does_not_hide_later_pages():
    source = generated_pdf("First", "broken", "Third", broken_page=2)
    with PypdfReader().open(source) as document:
        assert document.read_page(1) == "First"
        with pytest.raises(PdfPageError) as failure:
            document.read_page(2)
        assert failure.value.page == 2
        assert isinstance(failure.value.__cause__, TypeError)
        assert document.read_page(3) == "Third"


@pytest.mark.parametrize("password", ["", "secret"])
def test_encryption_requires_an_explicit_password_even_when_empty_opens_it(password):
    source = generated_pdf("Encrypted text", password=password)
    with pytest.raises(PdfEncryptedError, match="explicit password"), PypdfReader().open(source):
        pytest.fail("encrypted input entered the context")
    with PypdfReader().open(source, password=password) as document:
        assert document.is_encrypted is True
        assert document.read_page(1) == "Encrypted text"


def test_wrong_password_has_a_distinct_error():
    source = generated_pdf("Encrypted text", password="secret")
    with pytest.raises(PdfEncryptedError, match="not accepted"), PypdfReader().open(source, password=""):
        pytest.fail("wrong password entered the context")


@pytest.mark.parametrize("source", [b"not a PDF", SOURCE[:1000]])
def test_unreadable_source_retains_the_provider_failure(source):
    with pytest.raises(PdfReadError) as failure, PypdfReader().open(source):
        pytest.fail("unreadable input entered the context")
    assert failure.value.__cause__ is not None


@pytest.mark.parametrize("number", [0, -1, 2, True, 1.0, "1"])
def test_page_selection_is_one_based_and_requires_an_integer(number):
    with PypdfReader().open(SOURCE) as document, pytest.raises(ValueError, match="page number"):
        document.read_page(number)


def test_document_and_owned_stream_close_and_caller_exception_keeps_identity(monkeypatch):
    readers = []
    original_reader = pypdf.PdfReader

    def record_reader(stream, **kwargs):
        reader = original_reader(stream, **kwargs)
        readers.append((reader, stream))
        return reader

    monkeypatch.setattr(pypdf, "PdfReader", record_reader)
    marker = ValueError("caller failed")
    with pytest.raises(ValueError) as failure, PypdfReader().open(SOURCE) as document:
        raise marker
    assert failure.value is marker
    assert readers[0][1].closed
    assert readers[0][0].flattened_pages == []
    with pytest.raises(ValueError, match="closed"):
        document.read_page(1)


@pytest.mark.parametrize("mutation", ["expected", "loaded", "unidentified"])
def test_backend_identity_is_checked_before_pdf_construction(monkeypatch, mutation):
    def forbidden(*args, **kwargs):
        pytest.fail("constructed PDF before checking backend identity")

    provider = SimpleNamespace(PdfReader=forbidden)
    if mutation != "unidentified":
        provider.__version__ = "different" if mutation == "loaded" else pypdf.__version__
    monkeypatch.setattr("spicy_docs.extraction.pypdf.import_module", lambda _: provider)
    expected = "different" if mutation == "expected" else pypdf.__version__
    with pytest.raises(PdfReadError, match="version"), PypdfReader(expected_backend_version=expected).open(SOURCE):
        pytest.fail("mismatched backend entered the context")


@pytest.mark.parametrize("text", [None, b"wrong type"])
def test_backend_none_text_remains_none_and_wrong_types_fail(monkeypatch, text):
    reader = SimpleNamespace(
        is_encrypted=False,
        pages=[SimpleNamespace(extract_text=lambda: text)],
        close=lambda: None,
    )
    monkeypatch.setattr(pypdf, "PdfReader", lambda *args, **kwargs: reader)
    with PypdfReader().open(SOURCE) as document:
        if text is None:
            assert document.read_page(1) is None
        else:
            with pytest.raises(PdfPageError) as failure:
                document.read_page(1)
            assert isinstance(failure.value.__cause__, TypeError)


def test_missing_optional_backend_has_an_actionable_error(monkeypatch):
    def missing(_):
        raise ImportError("backend missing")

    monkeypatch.setattr("spicy_docs.extraction.pypdf.import_module", missing)
    with pytest.raises(PdfReadError, match=r"spicy-docs\[pdf-pypdf\]"), PypdfReader().open(SOURCE):
        pytest.fail("missing backend entered the context")


def test_import_and_configuration_do_not_load_optional_pdf_backends():
    probe = """
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
class RefusePdfImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pypdf', 'pymupdf', 'PIL'}:
            raise AssertionError('optional backend imported: ' + fullname)
sys.meta_path.insert(0, RefusePdfImports())
from spicy_docs.extraction.pypdf import PypdfReader
PypdfReader(expected_backend_version='6.14.2')
assert not {'pypdf', 'pymupdf', 'PIL'}.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(Path(__file__).parents[2] / "src")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_input_limit_is_a_configuration_error(limit):
    with pytest.raises(ValueError, match="max_input_bytes"):
        PypdfReader(max_input_bytes=limit)


def test_input_guard_runs_before_loading_optional_backend(monkeypatch):
    def forbidden(_):
        pytest.fail("loaded backend before checking source")

    monkeypatch.setattr("spicy_docs.extraction.pypdf.import_module", forbidden)
    with pytest.raises(ValueError, match="max_input_bytes"), PypdfReader(max_input_bytes=1).open(SOURCE):
        pytest.fail("over-limit source entered the context")
    for source in (b"", "not bytes"):
        with pytest.raises(ValueError, match="nonempty PDF bytes"), PypdfReader().open(source):
            pytest.fail("invalid source entered the context")
