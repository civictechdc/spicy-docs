"""Archive delivery preserves the checked bytes without retaining every title body."""

import hashlib
import io
import zipfile
from dataclasses import asdict
from pathlib import Path

import pytest

from spicy_docs.sources import uscode_archive as reader
from spicy_docs.sources.uscode import ReleasePoint, TitleSelection, UsCodeSourceError

FIXTURES = Path(__file__).parent / "fixtures" / "uscode"
TITLE_ZIP = (FIXTURES / "xml_usc01@119-103.zip").read_bytes()
with zipfile.ZipFile(io.BytesIO(TITLE_ZIP)) as _archive:
    TITLE_XML = _archive.read("usc01.xml")
APPENDIX_XML = (FIXTURES / "usc50A.xml").read_bytes()
CURRENT = ReleasePoint(119, 103)
SELECTION = TitleSelection(CURRENT, "01")
CURRENT_APPENDIX = APPENDIX_XML.replace(b"Online@119-102", b"Online@119-103")
ANNUAL_HTML = (FIXTURES / "annual-2024usc01-head.htm").read_bytes()


def archive(*members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in members:
            bundle.writestr(name, data)
    return buffer.getvalue()


def observe_validation(monkeypatch):
    validated = []
    original = reader.validate_title_xml

    def validate(body, **kwargs):
        validated.append((id(body), kwargs["selection"].title))
        return original(body, **kwargs)

    monkeypatch.setattr(reader, "validate_title_xml", validate)
    return validated


def test_real_title_returns_the_exact_once_validated_member(monkeypatch):
    validated = observe_validation(monkeypatch)
    result = reader.read_title_archive(TITLE_ZIP, selection=SELECTION)
    assert result.xml_bytes == TITLE_XML
    assert validated == [(id(result.xml_bytes), "01")]
    assert result.entry.byte_size == len(result.xml_bytes)
    assert result.entry.sha256 == "sha256:" + hashlib.sha256(result.xml_bytes).hexdigest()
    assert result.entry.metadata.title == "01"


def test_corpus_delivers_exact_once_validated_bytes_and_returns_only_metadata(monkeypatch):
    validated = observe_validation(monkeypatch)
    observed = []

    def observe(entry, body):
        assert validated[-1] == (id(body), entry.metadata.title)
        observed.append((entry.name, hashlib.sha256(body).hexdigest(), len(body)))

    result = reader.read_corpus_archive(
        archive(("folder/usc01.xml", TITLE_XML), ("usc50A.xml", CURRENT_APPENDIX)),
        release_point=CURRENT,
        on_entry=observe,
    )
    assert [title for _, title in validated] == ["01", "50a"]
    assert observed == [(entry.name, entry.sha256.removeprefix("sha256:"), entry.byte_size) for entry in result.entries]
    assert list(asdict(result)) == ["release_point", "entries"]
    assert all(set(asdict(entry)) == {"name", "sha256", "byte_size", "metadata"} for entry in result.entries)
    assert not hasattr(result, "xml_bytes")


@pytest.mark.parametrize("error", [ValueError("sink"), zipfile.BadZipFile("sink"), RuntimeError("sink")])
def test_callback_error_is_unchanged_stops_before_next_title_and_closes_archive(monkeypatch, error):
    opened = []
    original = reader.open_archive
    validated = observe_validation(monkeypatch)

    def open_zip(*args, **kwargs):
        bundle = original(*args, **kwargs)
        opened.append(bundle)
        return bundle

    monkeypatch.setattr(reader, "open_archive", open_zip)

    def fail(entry, body):
        raise error

    with pytest.raises(type(error)) as raised:
        reader.read_corpus_archive(
            archive(("usc01.xml", TITLE_XML), ("usc50A.xml", CURRENT_APPENDIX)),
            release_point=CURRENT,
            on_entry=fail,
        )
    assert raised.value is error
    assert len(validated) == 1
    assert len(opened) == 1 and opened[0].fp is None


def test_later_wrong_release_refuses_after_only_a_provisional_prefix():
    observed = []
    with pytest.raises(UsCodeSourceError, match="native release point"):
        reader.read_corpus_archive(
            archive(("usc01.xml", TITLE_XML), ("usc50A.xml", APPENDIX_XML)),
            release_point=CURRENT,
            on_entry=lambda entry, body: observed.append(entry.name),
        )
    assert observed == ["usc01.xml"]


def test_directory_only_zip_cannot_establish_a_successful_empty_corpus():
    # Named divergence: the old reader accepted this ZIP without a single title.
    with pytest.raises(UsCodeSourceError, match="holds no title member"):
        reader.read_corpus_archive(
            archive(("empty/", b"")),
            release_point=CURRENT,
            on_entry=lambda *args: pytest.fail("Directory is not a title"),
        )


def test_aggregate_expansion_bound_precedes_crc_or_callback(monkeypatch):
    body = archive(("usc01.xml", TITLE_XML), ("usc50A.xml", CURRENT_APPENDIX))

    def unexpected(*args):
        pytest.fail("CRC or callback started despite the declared expansion refusal")

    monkeypatch.setattr(zipfile.ZipFile, "testzip", unexpected)
    with pytest.raises(UsCodeSourceError, match="max_total_bytes"):
        reader.read_corpus_archive(
            body,
            release_point=CURRENT,
            max_total_bytes=len(TITLE_XML) + len(CURRENT_APPENDIX) - 1,
            on_entry=unexpected,
        )


def test_exact_aggregate_expansion_bound_admits_both_members():
    result = reader.read_corpus_archive(
        archive(("usc01.xml", TITLE_XML), ("usc50A.xml", CURRENT_APPENDIX)),
        release_point=CURRENT,
        max_total_bytes=len(TITLE_XML) + len(CURRENT_APPENDIX),
    )
    assert len(result.entries) == 2


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "1000"])
def test_aggregate_bound_is_an_explicit_positive_integer(limit):
    with pytest.raises(UsCodeSourceError, match="max_total_bytes"):
        reader.read_corpus_archive(TITLE_ZIP, release_point=CURRENT, max_total_bytes=limit)


def test_annual_callback_preserves_mixed_order_and_native_carried_year(monkeypatch):
    stale = ANNUAL_HTML.replace(b"AUTHORITIES-PUBLICATION-YEAR:2024", b"AUTHORITIES-PUBLICATION-YEAR:2015").replace(
        b"AUTHORITIES-USC-TITLE-ENUM:1", b"AUTHORITIES-USC-TITLE-ENUM:50"
    )
    members = [
        ("2024/usc.css", b"body{}"),
        ("2024/2024usc01.htm", ANNUAL_HTML),
        ("2024/index.html", b"<html/>"),
        ("2024/2024usc50a.htm", stale),
    ]
    observed = []
    validated = []
    original = reader.validate_annual_title_html

    def validate(body, **kwargs):
        validated.append(id(body))
        return original(body, **kwargs)

    def observe(entry, body):
        if entry.metadata is not None:
            assert id(body) == validated[-1]
        assert entry.sha256 == "sha256:" + hashlib.sha256(body).hexdigest()
        observed.append((entry, body))

    monkeypatch.setattr(reader, "validate_annual_title_html", validate)
    result = reader.read_annual_archive(
        archive(*members),
        year=2024,
        max_total_bytes=sum(len(body) for _, body in members),
        on_entry=observe,
    )
    assert len(validated) == 2
    assert [(entry.name, body) for entry, body in observed] == members
    assert [entry.metadata is None for entry, _ in observed] == [True, False, True, False]
    assert observed[-1][0].metadata.publication_year == "2015"
    assert result.carried_forward == ("2024/2024usc50a.htm",)
    assert [entry.name for entry in result.others] == ["2024/usc.css", "2024/index.html"]


@pytest.mark.parametrize("error", [ValueError("sink"), zipfile.BadZipFile("sink")])
def test_annual_callback_error_preserves_identity_closes_and_stops_at_sidecar(monkeypatch, error):
    opened = []
    original = reader.open_archive

    def open_zip(*args, **kwargs):
        bundle = original(*args, **kwargs)
        opened.append(bundle)
        return bundle

    monkeypatch.setattr(reader, "open_archive", open_zip)
    monkeypatch.setattr(reader, "validate_annual_title_html", lambda *a, **kw: pytest.fail("Read next title"))

    def fail(entry, body):
        assert entry.metadata is None
        raise error

    with pytest.raises(type(error)) as raised:
        reader.read_annual_archive(
            archive(("usc.css", b"body{}"), ("2024usc01.htm", ANNUAL_HTML)), year=2024, on_entry=fail
        )
    assert raised.value is error
    assert len(opened) == 1 and opened[0].fp is None


@pytest.mark.parametrize("member_kind", ["sidecar", "carried", "wrong-title"])
def test_annual_final_refusal_does_not_turn_provisional_members_into_success(member_kind):
    observed = []
    if member_kind == "sidecar":
        members = [("usc.css", b"body{}")]
        message = "holds no title"
    elif member_kind == "carried":
        stale = ANNUAL_HTML.replace(b"AUTHORITIES-PUBLICATION-YEAR:2024", b"AUTHORITIES-PUBLICATION-YEAR:2015")
        members = [("2024usc01.htm", stale)]
        message = "states no member of the requested year"
    else:
        members = [("usc.css", b"body{}"), ("2024usc02.htm", ANNUAL_HTML)]
        message = "enum differs"
    with pytest.raises(UsCodeSourceError, match=message):
        reader.read_annual_archive(
            archive(*members), year=2024, on_entry=lambda entry, body: observed.append(entry.name)
        )
    assert observed == [members[0][0]]


def test_annual_aggregate_bound_counts_sidecars_before_crc_or_callback(monkeypatch):
    def unexpected(*args):
        pytest.fail("CRC or callback started despite the declared expansion refusal")

    monkeypatch.setattr(zipfile.ZipFile, "testzip", unexpected)
    with pytest.raises(UsCodeSourceError, match="max_total_bytes"):
        reader.read_annual_archive(
            archive(("2024usc01.htm", ANNUAL_HTML), ("usc.css", b"body{}")),
            year=2024,
            max_total_bytes=len(ANNUAL_HTML),
            on_entry=unexpected,
        )
