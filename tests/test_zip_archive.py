"""Expansion refusals happen before CRC decompression, even for ignored entries.

Entry count, per-entry, and total byte bounds plus duplicate and directory members refuse in preflight; CRC still
checks ignored entries; read_member never requests unbounded inflation."""

import io
import zipfile

import pytest

from spicy_docs.reading.zip_archive import inspect_archive_stream, open_archive, read_member


def archive(*members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in members:
            bundle.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize(
    "body,limits,reason",
    [
        (archive(("large.xml", b"x" * 4096)), {"max_entry_bytes": 1024}, "max_entry_bytes"),
        (archive(("a", b"a"), ("b", b"b")), {"max_entries": 1}, "max_entries"),
        (archive(("a", b"a" * 60), ("ignored.css", b"b" * 60)), {"max_total_bytes": 100}, "max_total_bytes"),
        (archive(("one/a.xml", b"a"), ("two/a.xml", b"b")), {}, "repeats"),
        (archive(("directory/", b"payload")), {}, "directory"),
    ],
)
def test_preflight_refuses_before_decompression(monkeypatch, body, limits, reason):
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda _: pytest.fail("Decompressed before preflight"))
    options = {"max_bytes": 1024 * 1024, "max_entries": 10, "max_entry_bytes": 8192} | limits
    with pytest.raises(ValueError, match=reason):
        open_archive(body, **options, error_type=ValueError, label="test archive")


def test_crc_still_checks_every_file_including_ignored_entries():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as bundle:
        bundle.writestr("source.xml", b"source")
        bundle.writestr("ignored.css", b"ignored payload")
    body = output.getvalue().replace(b"ignored payload", b"damaged payload")
    with pytest.raises(ValueError, match="CRC"):
        open_archive(body, max_bytes=4096, max_entries=2, max_entry_bytes=128, error_type=ValueError, label="zip")


@pytest.mark.parametrize("compression", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_codecs_without_bounded_inflater_output_refuse_before_crc(monkeypatch, compression):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression) as bundle:
        bundle.writestr("source.xml", b"x" * 1000)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda _: pytest.fail("Decompressed unsupported codec"))
    with pytest.raises(ValueError, match="compression"):
        open_archive(
            output.getvalue(), max_bytes=4096, max_entries=2, max_entry_bytes=4096, error_type=ValueError, label="zip"
        )


def test_member_read_never_requests_unbounded_inflation(monkeypatch):
    body = archive(("source.xml", b"source"))
    with open_archive(
        body, max_bytes=4096, max_entries=2, max_entry_bytes=128, error_type=ValueError, label="zip"
    ) as bundle:
        original = zipfile.ZipExtFile.read
        requests = []

        def bounded(stream, size=-1):
            requests.append(size)
            assert 0 <= size <= 129
            return original(stream, size)

        monkeypatch.setattr(zipfile.ZipExtFile, "read", bounded)
        assert read_member(bundle, bundle.infolist()[0], max_bytes=128, error_type=ValueError, label="zip") == b"source"
        assert requests == [129]


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_inventory_hands_each_member_to_its_observer_in_the_single_pass(monkeypatch, compression):
    payload = bytes(range(256)) * 700  # larger than one 64 KiB decoded chunk
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression) as bundle:
        bundle.writestr("a.bin", payload)
        bundle.writestr("b.bin", b"small")
    body = output.getvalue()
    monkeypatch.setattr(zipfile.ZipExtFile, "read", lambda *_a, **_k: pytest.fail("a member was decoded twice"))
    seen: dict[int, list[bytes]] = {}

    def observe(ordinal, info):
        assert info.filename in ("a.bin", "b.bin")
        return seen.setdefault(ordinal, []).append

    inventory = inspect_archive_stream(
        io.BytesIO(body),
        byte_size=len(body),
        max_entries=4,
        max_decoded_bytes=1 << 20,
        max_metadata_bytes=1 << 16,
        observe=observe,
    )
    assert b"".join(seen[0]) == payload and b"".join(seen[1]) == b"small"
    assert max(len(chunk) for chunk in seen[0]) <= 64 * 1024
    assert [member["crcVerified"] for member in inventory["members"]] == [True, True]
