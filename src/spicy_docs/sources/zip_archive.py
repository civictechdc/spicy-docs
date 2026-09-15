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


def open_archive(body: bytes, *, max_bytes: int, error_type: type[ValueError], label: str) -> zipfile.ZipFile:
    """Nonempty bounded bytes carrying a zip local file header, with every entry's CRC checked."""
    if not isinstance(body, bytes) or not body or len(body) > max_bytes:
        raise error_type(f"{label} must be nonempty bytes within max_bytes")
    if body[:4] != b"PK\x03\x04":
        raise error_type(f"{label} does not start with a zip local file header")
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
        if archive.testzip() is not None:
            raise error_type(f"{label} fails its CRC check")
    except zipfile.BadZipFile as error:
        raise error_type(f"{label} is malformed") from error
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
    data = archive.read(info)
    if len(data) != info.file_size:
        raise error_type(f"{label} entry size differs from its header")
    return data
