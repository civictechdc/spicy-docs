"""One bounded zip reader for the archive routes: a proved shape, bounded entries, checked sizes.

Publishers serve bulk collections as zips whose headers prove nothing: GovInfo's
bulkdata omits ``Content-Length`` and OLRC's download routes send no
``Content-Type`` at all. The shape is therefore read from the bytes -- a local
file header, then a CRC check of the whole archive before any entry is trusted --
and every bound is the caller's. Each caller keeps its own refusal words through
``error_type`` and ``label``; nothing here decides what an entry means.
"""

from __future__ import annotations

import io
import zipfile


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
