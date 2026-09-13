"""Explicit CFR source requests and the native facts their XML can establish."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as Date
from typing import Literal

DEFAULT_MAX_BYTES = 16 * 1024 * 1024
MAX_CFR_BYTES = 256 * 1024 * 1024
_PART = re.compile(r"[0-9]+(?:-[0-9]+)*")
_SECTION = re.compile(r"[0-9][0-9A-Za-z()._-]*")
_ANNUAL_SECTION = re.compile(r"[0-9]+(?:-[0-9]+)*\.[0-9]+[A-Za-z]?(?:-[0-9]+[A-Za-z]?)*")


class CfrSourceError(ValueError):
    """The request or response cannot establish the selected CFR source."""


def _title(value: int, *, allow_reserved: bool = False) -> int:
    if type(value) is not int or not 1 <= value <= 50 or (value == 35 and not allow_reserved):
        raise CfrSourceError("title must be an integer from 1 to 50; title 35 is reserved")
    return value


def _date(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise CfrSourceError("date must use YYYY-MM-DD")
    try:
        Date.fromisoformat(value)
    except ValueError as error:
        raise CfrSourceError("date must be a valid calendar date") from error
    return value


def _limit(max_bytes: int) -> None:
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CFR_BYTES:
        raise CfrSourceError("max_bytes must be a positive integer no greater than 256 MiB")


def _section(value: str) -> str:
    if not isinstance(value, str) or len(value) > 128 or _SECTION.fullmatch(value) is None:
        raise CfrSourceError("section must be one explicit CFR section number")
    return value


@dataclass(frozen=True, slots=True)
class EcfrSelection:
    title: int
    date: str
    part: str | None = None
    section: str | None = None

    def __post_init__(self) -> None:
        _title(self.title)
        _date(self.date)
        if self.part is not None and (
            not isinstance(self.part, str) or len(self.part) > 64 or _PART.fullmatch(self.part) is None
        ):
            raise CfrSourceError("part must be one explicit CFR part number")
        if self.section is not None:
            _section(self.section)
            # Title 14 Part 241 contains section 19-8.1. Native ancestry, not
            # a section's numeric prefix, identifies the containing part.
            if self.part is None:
                raise CfrSourceError("section requires an explicit part")


@dataclass(frozen=True, slots=True)
class AnnualCfrSelection:
    year: int
    title: int
    volume: int
    section: str | None = None

    def __post_init__(self) -> None:
        _title(self.title)
        if type(self.year) is not int or not 1000 <= self.year <= 9999:
            raise CfrSourceError("year must be a four-digit integer")
        if type(self.volume) is not int or not 1 <= self.volume <= 999:
            raise CfrSourceError("volume must be an integer from 1 to 999")
        if self.section is not None:
            _section(self.section)
            if _ANNUAL_SECTION.fullmatch(self.section) is None:
                raise CfrSourceError("annual section locator spelling is unsupported")


@dataclass(frozen=True, slots=True)
class EcfrTitle:
    number: int
    name: str
    reserved: bool
    latest_amended_on: str | None
    latest_issue_date: str | None
    up_to_date_as_of: str | None
    processing_in_progress: bool | None = None


@dataclass(frozen=True, slots=True)
class EcfrTitles:
    date: str
    import_in_progress: bool
    titles: tuple[EcfrTitle, ...]


@dataclass(frozen=True, slots=True)
class CfrXmlMetadata:
    """Native fields stay absent when only the request URL supplies identity.

    Dates printed in the body are not the requested API date or annual edition.
    ``identity_basis`` identifies which fields rely on the canonical response URL.
    Full source XML remains with the caller, including fields not listed here.
    """

    source: Literal["ecfr-api", "ecfr-bulk", "annual-cfr"]
    title: int | None
    volume: int | None
    part: str | None
    section: str | None
    root_tag: str
    title_text: str | None
    stated_date: str | None
    revision_text: str | None
    amendment_dates: tuple[str, ...]
    identity_basis: tuple[str, ...]
