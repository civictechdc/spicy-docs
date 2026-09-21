"""One bounded zip reader for the archive routes: a proved shape, bounded entries, checked sizes.

Publishers serve bulk collections as zips whose headers prove nothing: GovInfo's
bulkdata omits ``Content-Length`` and OLRC's download routes send no
``Content-Type`` at all. The shape is therefore read from the bytes -- a local
file header, then a CRC check of the whole archive before any entry is trusted --
and every bound is the caller's. Each caller keeps its own refusal words through
``error_type`` and ``label``; nothing here decides what an entry means.
"""

from __future__ import annotations

import hashlib
import io
import struct
import zipfile
import zlib
from contextlib import contextmanager
from tempfile import TemporaryFile

from rulespec_artifacts import canonical_json_bytes


def _check_codec(info: zipfile.ZipInfo, error_type: type[ValueError], label: str) -> None:
    # These codecs bound inflater output by the requested read size. Python's
    # BZIP2/LZMA zip readers may inflate an unbounded buffer before slicing it.
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise error_type(f"{label} uses an unsupported compression method")


def open_archive(
    body: bytes,
    *,
    max_bytes: int,
    max_entries: int,
    max_entry_bytes: int,
    error_type: type[ValueError],
    label: str,
    max_total_bytes: int | None = None,
    bound: str = "max_entry_bytes",
) -> zipfile.ZipFile:
    """Check declared expansion bounds before decompressing every entry for CRC.

    The aggregate bound defaults to the product of the entry count and size
    limits. Callers can set a tighter total without weakening any per-file bound.
    """
    for name, value in (("max_bytes", max_bytes), ("max_entries", max_entries), ("max_entry_bytes", max_entry_bytes)):
        if type(value) is not int or value <= 0:
            raise error_type(f"{name} must be a positive integer")
    if max_total_bytes is None:
        max_total_bytes = max_entries * max_entry_bytes
    if type(max_total_bytes) is not int or max_total_bytes <= 0:
        raise error_type("max_total_bytes must be a positive integer")
    if not isinstance(body, bytes) or not body or len(body) > max_bytes:
        raise error_type(f"{label} must be nonempty bytes within max_bytes")
    if body[:4] != b"PK\x03\x04":
        raise error_type(f"{label} does not start with a zip local file header")
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as error:
        raise error_type(f"{label} is malformed") from error
    try:
        archive_members(archive, max_entries=max_entries, error_type=error_type, label=label)
        total = 0
        for info in archive.infolist():
            _check_codec(info, error_type, label)
            if info.is_dir() and info.file_size:
                raise error_type(f"{label} directory entry contains data")
            if info.file_size > max_entry_bytes:
                raise error_type(f"{label} entry exceeds {bound}")
            total += info.file_size
            if total > max_total_bytes:
                raise error_type(f"{label} exceeds max_total_bytes")
        if archive.testzip() is not None:
            raise error_type(f"{label} fails its CRC check")
    except BaseException:
        archive.close()
        raise
    return archive


def archive_members(
    archive: zipfile.ZipFile, *, max_entries: int, error_type: type[ValueError], label: str
) -> list[zipfile.ZipInfo]:
    """Every file entry in the publisher's own order, refusing too many or a repeated base name.

    A directory is not an entry. Base names are compared rather than paths,
    because two folders carrying one file name would otherwise pass two entries
    claiming a single identity.
    """
    members = [info for info in archive.infolist() if not info.is_dir()]
    if len(members) > max_entries:
        raise error_type(f"{label} contains more entries than max_entries")
    seen: set[str] = set()
    for info in members:
        name = info.filename.rsplit("/", 1)[-1]
        if name in seen:
            raise error_type(f"{label} repeats an entry name")
        seen.add(name)
    return members


def read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_bytes: int,
    error_type: type[ValueError],
    label: str,
    bound: str = "max_entry_bytes",
) -> bytes:
    """One entry's bytes, bounded by the size its header states before reading and checked against it."""
    if info.file_size > max_bytes:
        raise error_type(f"{label} entry exceeds {bound}")
    _check_codec(info, error_type, label)
    with archive.open(info) as stream:
        data = stream.read(max_bytes + 1)
    if len(data) != info.file_size:
        raise error_type(f"{label} entry size differs from its header")
    return data


class _BoundedZipReads:
    """Limit directory allocation before ZipFile loads it; leave the caller's stream open."""

    def __init__(self, stream, *, byte_size, max_read):
        self.stream, self.byte_size, self.max_read = stream, byte_size, max_read

    def read(self, size=-1):
        """Read within ``max_read`` bytes of the stream's end, so directory allocation is bounded before it happens."""
        requested = self.byte_size - self.tell() if size < 0 else size
        if requested > self.max_read:
            raise ValueError("ZIP metadata read exceeds its byte bound")
        return self.stream.read(requested)

    def seek(self, *args):
        return self.stream.seek(*args)

    def tell(self):
        return self.stream.tell()

    def seekable(self):
        return True


def inspect_archive_stream(stream, *, byte_size, max_entries, max_decoded_bytes, max_metadata_bytes):
    """Inventory every ZIP entry, including directories and repeated full names.

    The caller supplies a seekable pinned stream. No extraction paths are used.
    Directory allocation, entry count, decompression and returned metadata are
    bounded before reading payloads. Every member is fully read for CRC and SHA-256.
    """
    for bound in (byte_size, max_entries, max_decoded_bytes, max_metadata_bytes):
        if type(bound) is not int or bound < 1:
            raise ValueError("ZIP inspection bounds must be positive integers")
    with seekable_stream(stream, byte_size=byte_size) as selected:
        return _inspect_seekable_archive(
            selected,
            byte_size=byte_size,
            max_entries=max_entries,
            max_decoded_bytes=max_decoded_bytes,
            max_metadata_bytes=max_metadata_bytes,
        )


@contextmanager
def seekable_stream(stream, *, byte_size):
    """Reuse a seekable original or spool bounded reads once without closing the caller."""
    if stream.seekable():
        yield stream
        return
    with TemporaryFile() as seekable:
        observed = 0
        while True:
            requested = min(64 * 1024, byte_size - observed + 1)
            chunk = stream.read(requested)
            if not isinstance(chunk, bytes) or len(chunk) > requested:
                raise ValueError("ZIP stream did not return bounded binary bytes")
            if not chunk:
                break
            observed += len(chunk)
            if observed > byte_size:
                raise ValueError("ZIP stream exceeds its selected byte size")
            seekable.write(chunk)
        if observed != byte_size:
            raise ValueError("ZIP stream is short")
        seekable.seek(0)
        yield seekable


def _inspect_seekable_archive(stream, *, byte_size, max_entries, max_decoded_bytes, max_metadata_bytes):
    stream.seek(0)
    if stream.read(4) not in (b"PK\x03\x04", b"PK\x05\x06"):
        raise ValueError("ZIP original lacks a local file or empty-archive header")
    # ZipFile accepts truncated comments; exact inventory requires the whole EOCD.
    stream.seek(max(0, byte_size - 65557))
    tail = stream.read(min(byte_size, 65557))
    end = tail.rfind(b"PK\x05\x06")
    if end < 0 or len(tail) - end < 22 or end + 22 + int.from_bytes(tail[end + 20 : end + 22], "little") != len(tail):
        raise ValueError("ZIP end record or comment is truncated or has trailing bytes")
    if tail[end + 4 : end + 8] != b"\0" * 4:
        raise ValueError("split ZIP archives require a separate representation")
    view = _BoundedZipReads(stream, byte_size=byte_size, max_read=max_metadata_bytes)
    with zipfile.ZipFile(view) as archive:
        infos = archive.infolist()
        if len(infos) > max_entries:
            raise ValueError("ZIP entry count exceeds its bound")
        if sum(info.file_size for info in infos) > max_decoded_bytes:
            raise ValueError("ZIP decoded size exceeds its bound")
        rows = []
        metadata_bytes = len(archive.comment.hex())
        for ordinal, info in enumerate(infos):
            row = {
                "ordinal": ordinal,
                "name": info.orig_filename,
                "isDirectory": info.is_dir(),
                "byteSize": info.file_size,
                "compressedBytes": info.compress_size,
                "compressionMethod": info.compress_type,
                "flags": info.flag_bits,
                "crc32": f"{info.CRC:08x}",
                "dateTime": list(info.date_time),
                "headerOffset": info.header_offset,
                "createSystem": info.create_system,
                "createVersion": info.create_version,
                "extractVersion": info.extract_version,
                "internalAttributes": info.internal_attr,
                "externalAttributes": info.external_attr,
                "extraHex": info.extra.hex(),
                "commentHex": info.comment.hex(),
            }
            metadata_bytes += len(canonical_json_bytes(row)) + 100  # Reserve the digest and verified-CRC fields.
            if metadata_bytes > max_metadata_bytes:
                raise ValueError("ZIP inventory metadata exceeds its byte bound")
            digest = _complete_member_digest(archive, info, view)
            rows.append({**row, "sha256": digest, "crcVerified": True})
        result = {"commentHex": archive.comment.hex(), "members": rows}
        if len(canonical_json_bytes(result)) > max_metadata_bytes:
            raise ValueError("ZIP inventory metadata exceeds its byte bound")
        return result


def _complete_member_digest(archive, info, stream):
    """Verify the full declared compressed range; ZipExtFile truncates to file_size.

    zlib's max_length bounds each decoded chunk. Unsupported compressors refuse
    because ZipExtFile's bzip2/LZMA path cannot guarantee that memory bound.
    """
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ValueError("ZIP compression method needs a bounded decoder")
    # Reuse ZipFile's local-header/name, encryption and overlap checks, without
    # its size-truncating payload reader. No entry is extracted to a filesystem.
    with archive.open(info):
        pass
    stream.seek(info.header_offset)
    header = stream.read(30)
    if len(header) != 30:
        raise ValueError("ZIP local header is truncated")
    signature, _version, flags, method, _, _, crc, compressed, decoded, name_size, extra_size = struct.unpack(
        "<4s5H3I2H", header
    )
    if signature != b"PK\x03\x04" or method != info.compress_type or flags != info.flag_bits:
        raise ValueError("ZIP local and central headers disagree")
    if not flags & 8 and (
        crc != info.CRC
        or compressed not in (info.compress_size, 0xFFFFFFFF)
        or decoded not in (info.file_size, 0xFFFFFFFF)
    ):
        raise ValueError("ZIP local and central sizes or CRC disagree")
    stream.seek(info.header_offset + 30 + name_size + extra_size)
    remaining, observed, checksum, digest = info.compress_size, 0, 0, hashlib.sha256()
    decoder = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None

    def account(data):
        nonlocal observed, checksum
        observed += len(data)
        if observed > info.file_size:
            raise ValueError("ZIP decoded member exceeds its declared size")
        checksum = zlib.crc32(data, checksum)
        digest.update(data)

    while remaining:
        requested = min(64 * 1024, remaining)
        data = stream.read(requested)
        if len(data) != requested:
            raise ValueError("ZIP compressed member is truncated")
        remaining -= len(data)
        if decoder is None:
            account(data)
        else:
            while data:
                account(decoder.decompress(data, 64 * 1024))
                data = decoder.unconsumed_tail
                if decoder.unused_data:
                    raise ValueError("ZIP compressed member contains trailing data")
    if decoder is not None and not decoder.eof:
        raise ValueError("ZIP deflate member has no complete end")
    if observed != info.file_size or checksum != info.CRC:
        raise ValueError("ZIP complete member differs from its size or CRC")
    return "sha256:" + digest.hexdigest()
