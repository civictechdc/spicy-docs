"""Validated release-point and annual title content from retained OLRC ZIP bytes.

One title returns its XML with the member's source metadata. A corpus keeps only
metadata and offers each validated member to a callback. Annual archives also
deliver their supporting files. Storage and processing remain the caller's responsibility.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass

from spicy_docs.reading.zip_archive import archive_members, open_archive, read_member

from .annual import AnnualTitleMetadata, validate_annual_title_html
from .core import (
    ANNUAL_HEADER_BYTES,
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ARCHIVE_ENTRIES,
    DEFAULT_MAX_XML_BYTES,
    ReleasePoint,
    TitleSelection,
    UsCodeSourceError,
    _count,
    _digest,
    _limit,
    annual_archive_locator,
)
from .titles import UsCodeTitleMetadata, validate_title_xml

_TITLE_MEMBER = re.compile(r"usc(?P<title>[0-9]{2})(?P<appendix>[aA]?)\.xml")
_ANNUAL_MEMBER = re.compile(r"(?P<year>[0-9]{4})usc(?P<title>[0-9]{2})(?P<appendix>[aA]?)\.htm", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class UsCodeArchiveEntry:
    name: str
    byte_size: int
    sha256: str
    metadata: UsCodeTitleMetadata


@dataclass(frozen=True, slots=True)
class UsCodeTitleArchive:
    """One title's exact XML and the identity checked against those same bytes."""

    release_point: str
    entry: UsCodeArchiveEntry
    xml_bytes: bytes


@dataclass(frozen=True, slots=True)
class UsCodeArchive:
    """Metadata for every validated title; member bodies are not retained here."""

    release_point: str
    entries: tuple[UsCodeArchiveEntry, ...]


def _title_code(name: str) -> str | None:
    match = _TITLE_MEMBER.fullmatch(name)
    # The publisher spells the same appendix both ways: usc05A.xml and usc11a.xml.
    return None if match is None else match["title"] + match["appendix"].lower()


def _read_title_entry(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    selection: TitleSelection,
    max_entry_bytes: int,
    label: str,
) -> tuple[UsCodeArchiveEntry, bytes]:
    data = read_member(archive, info, max_bytes=max_entry_bytes, error_type=UsCodeSourceError, label=label)
    metadata = validate_title_xml(data, selection=selection, max_bytes=max_entry_bytes)
    return UsCodeArchiveEntry(info.filename, len(data), _digest(data), metadata), data


def read_title_archive(
    body: bytes,
    *,
    selection: TitleSelection,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_entry_bytes: int = DEFAULT_MAX_XML_BYTES,
) -> UsCodeTitleArchive:
    """Read one title's release-point ZIP and return its sole validated XML member."""
    if not isinstance(selection, TitleSelection):
        raise UsCodeSourceError("selection must be a TitleSelection")
    _limit(max_bytes)
    _limit(max_entry_bytes, "max_entry_bytes")
    label = "U.S. Code title archive"
    with open_archive(
        body,
        max_bytes=max_bytes,
        max_entries=2,
        max_entry_bytes=max_entry_bytes,
        error_type=UsCodeSourceError,
        label=label,
    ) as archive:
        members = archive_members(archive, max_entries=2, error_type=UsCodeSourceError, label=label)
        if len(members) != 1:
            raise UsCodeSourceError("U.S. Code title archive must hold exactly one member")
        info = members[0]
        if _title_code(info.filename.rsplit("/", 1)[-1]) != selection.title:
            raise UsCodeSourceError("U.S. Code title archive member name is not the requested title")
        entry, data = _read_title_entry(
            archive, info, selection=selection, max_entry_bytes=max_entry_bytes, label=label
        )
    return UsCodeTitleArchive(selection.release_point.label, entry, data)


def read_corpus_archive(
    body: bytes,
    *,
    release_point: ReleasePoint,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_entry_bytes: int = DEFAULT_MAX_XML_BYTES,
    max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
    max_total_bytes: int | None = None,
    on_entry: Callable[[UsCodeArchiveEntry, bytes], None] | None = None,
) -> UsCodeArchive:
    """Validate every member, optionally delivering its exact bytes in archive order.

    Callback observations are provisional until this function returns: a later
    member can refuse the corpus. Callback exceptions propagate unchanged and
    stop the scan. The reader retains at most one member body; callers control
    whether they retain callback bytes.

    The whole compressed input must fit ``max_bytes``. ``max_total_bytes`` bounds
    declared expansion before the shared CRC preflight; when omitted it defaults
    to ``max_entries * max_entry_bytes``. These limits are not CPU or memory caps.
    """
    if not isinstance(release_point, ReleasePoint):
        raise UsCodeSourceError("release_point must be a ReleasePoint")
    _limit(max_bytes)
    _limit(max_entry_bytes, "max_entry_bytes")
    _count(max_entries, "max_entries")
    label = "U.S. Code corpus archive"
    entries = []
    with open_archive(
        body,
        max_bytes=max_bytes,
        max_entries=max_entries,
        max_entry_bytes=max_entry_bytes,
        max_total_bytes=max_total_bytes,
        error_type=UsCodeSourceError,
        label=label,
    ) as archive:
        for info in archive_members(archive, max_entries=max_entries, error_type=UsCodeSourceError, label=label):
            code = _title_code(info.filename.rsplit("/", 1)[-1])
            if code is None:
                raise UsCodeSourceError("U.S. Code corpus archive entry name is not a title member")
            entry, data = _read_title_entry(
                archive,
                info,
                selection=TitleSelection(release_point, code),
                max_entry_bytes=max_entry_bytes,
                label=label,
            )
            entries.append(entry)
            if on_entry is not None:
                on_entry(entry, data)
            del data
    if not entries:
        raise UsCodeSourceError("U.S. Code corpus archive holds no title member")
    return UsCodeArchive(release_point.label, tuple(entries))


@dataclass(frozen=True, slots=True)
class AnnualArchiveEntry:
    name: str
    byte_size: int
    sha256: str
    metadata: AnnualTitleMetadata | None = None


@dataclass(frozen=True, slots=True)
class AnnualArchive:
    """One year's XHTML archive: its title members and the files the publisher ships beside them.

    ``carried_forward`` names the members stating another year. They are the
    publisher's own doing and are reported rather than refused; ``others`` are
    the stylesheet, directory listing and extra tables some years carry, each
    kept by name, size and digest but claiming no title identity.
    """

    year: int
    entries: tuple[AnnualArchiveEntry, ...]
    others: tuple[AnnualArchiveEntry, ...]
    carried_forward: tuple[str, ...]
    publication_names: tuple[str, ...]


def read_annual_archive(
    body: bytes,
    *,
    year: int,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_entry_bytes: int = DEFAULT_MAX_XML_BYTES,
    max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
    max_total_bytes: int | None = None,
    on_entry: Callable[[AnnualArchiveEntry, bytes], None] | None = None,
) -> AnnualArchive:
    """Validate annual titles and deliver every member in archive order.

    ``on_entry`` receives titles and sidecars; sidecars have ``metadata=None``.
    Callbacks remain provisional until the complete archive succeeds, including
    the final check that at least one title states the requested year. Callback
    exceptions propagate unchanged. Bytes are retained one member at a time;
    the input and expansion bounds have the same meaning as ``read_corpus_archive``.
    """
    annual_archive_locator(year)
    _limit(max_bytes)
    _limit(max_entry_bytes, "max_entry_bytes")
    _count(max_entries, "max_entries")
    label = "U.S. Code annual archive"
    entries: list[AnnualArchiveEntry] = []
    others: list[AnnualArchiveEntry] = []
    carried: list[str] = []
    names: list[str] = []
    with open_archive(
        body,
        max_bytes=max_bytes,
        max_entries=max_entries,
        max_entry_bytes=max_entry_bytes,
        max_total_bytes=max_total_bytes,
        error_type=UsCodeSourceError,
        label=label,
    ) as archive:
        for info in archive_members(archive, max_entries=max_entries, error_type=UsCodeSourceError, label=label):
            stem = info.filename.rsplit("/", 1)[-1]
            match = _ANNUAL_MEMBER.fullmatch(stem)
            data = read_member(archive, info, max_bytes=max_entry_bytes, error_type=UsCodeSourceError, label=label)
            if match is None:
                # A member this reader does not route must not be a title in
                # disguise: the same comments it would be validated by decide it.
                if b"AUTHORITIES-USC-TITLE-ENUM" in data[:ANNUAL_HEADER_BYTES]:
                    raise UsCodeSourceError("U.S. Code annual archive states a title under an unroutable name")
                entry = AnnualArchiveEntry(info.filename, len(data), _digest(data))
                others.append(entry)
            else:
                metadata = validate_annual_title_html(data, max_bytes=max_entry_bytes)
                enum = metadata.title_enum.lower()
                if enum not in (match["title"].lstrip("0") + match["appendix"].lower(), match["title"].lstrip("0")):
                    raise UsCodeSourceError("U.S. Code annual title enum differs from its member name")
                if metadata.publication_year != str(year):
                    carried.append(info.filename)
                if metadata.publication_name not in names:
                    names.append(metadata.publication_name)
                entry = AnnualArchiveEntry(info.filename, len(data), _digest(data), metadata)
                entries.append(entry)
            if on_entry is not None:
                on_entry(entry, data)
            del data
    if not entries:
        raise UsCodeSourceError("U.S. Code annual archive holds no title member")
    if all(entry.name in carried for entry in entries):
        raise UsCodeSourceError("U.S. Code annual archive states no member of the requested year")
    return AnnualArchive(year, tuple(entries), tuple(others), tuple(carried), tuple(names))
