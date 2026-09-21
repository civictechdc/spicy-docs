"""Shared deterministic ZIP-member metadata for source acquisition evidence.

``deterministic_zip_entry`` builds and ``has_deterministic_zip_metadata`` checks one fixed member shape
(1980-01-01 timestamp, deflate, mode 0644), so a replayed archive compares field by field.
"""

from __future__ import annotations

from zipfile import ZIP_DEFLATED, ZipInfo


def deterministic_zip_entry(name: str) -> ZipInfo:
    """Return the one stable ZIP entry shape used by every source profile."""

    entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    return entry


def has_deterministic_zip_metadata(entry: ZipInfo, *, name: str) -> bool:
    """Return whether a replayed member has the exact shared metadata shape."""

    expected = deterministic_zip_entry(name)
    return (
        entry.filename == name
        and entry.orig_filename == expected.orig_filename
        and entry.date_time == expected.date_time
        and entry.compress_type == expected.compress_type
        and entry.create_version == expected.create_version
        and entry.extract_version == expected.extract_version
        and entry.external_attr == expected.external_attr
        and entry.create_system == expected.create_system
        and entry.flag_bits == expected.flag_bits
        and entry.internal_attr == expected.internal_attr
        and entry.volume == expected.volume
        and entry.reserved == expected.reserved
        and entry.comment == expected.comment
        and entry.extra == expected.extra
    )


__all__ = ["deterministic_zip_entry", "has_deterministic_zip_metadata"]
