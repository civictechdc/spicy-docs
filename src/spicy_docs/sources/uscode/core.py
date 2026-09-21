"""Shared U.S. Code facts: constants, budget rules, selections, locators and the helpers every family checks with."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from spicy_docs.transport.source_acquirer import limit_byte_bound

OLRC = "https://uscode.house.gov"
USLM_NAMESPACE = "http://xml.house.gov/schemas/uslm/1.0"
DUBLIN_CORE_NAMESPACE = "http://purl.org/dc/elements/1.1/"
DUBLIN_CORE_TERMS_NAMESPACE = "http://purl.org/dc/terms/"

#: The title codes the publisher's own download page links, in its spelling and
#: order. ``53`` is listed and answers 302; that is a fact about the route, not
#: about this vocabulary, so the code stays here and the refusal names the status.
TITLES: tuple[str, ...] = (
    "01", "02", "03", "04", "05", "05a", "06", "07", "08", "09", "10", "11", "11a", "12", "13", "14",
    "15", "16", "17", "18", "18a", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "28a",
    "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44",
    "45", "46", "47", "48", "49", "50", "50a", "51", "52", "53", "54",
)  # fmt: skip

#: The publisher's own annual span. 1994 is the first XHTML archive offered.
FIRST_ANNUAL_YEAR = 1994

# The largest title is 42 at 113,732,787 bytes of XML; the largest annual member
# is 2024's title 42 at 78,766,785 bytes of XHTML; the whole-corpus zip is about
# 108 MB and the Table III bulk member is 126,260,704 bytes.
MAX_USCODE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_XML_BYTES = 128 * 1024 * 1024
# Every zip this publisher serves fits here with headroom: the corpus at 108.6
# MB is the largest, then the 2024 annual archive at 87.8 MB.
DEFAULT_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_PAGE_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_TABLE3_MEMBER_BYTES = 192 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_ENTRIES = 128
DEFAULT_MAX_ENTRIES_PER_PAGE = 65_536

#: Where an annual member's identity comments sit. The furthest observed is 842
#: bytes into the file across all 1,781 title members of the 31 retained zips.
ANNUAL_HEADER_BYTES = 16 * 1024

type UsCodeSource = Literal[
    "release-point-title",
    "annual-title",
    "popular-names",
    "table3-act",
    "table3-bulk",
    "classification-index",
    "classification-table",
]

_BULK_MEMBER = re.compile(r"fulldump@(?P<release_point>[0-9]+-[0-9]+)\.xml")
_RELEASE_POINT = re.compile(r"(?P<congress>[1-9][0-9]{0,2})-(?P<law>[1-9][0-9]{0,4})")
#: A Table III key is a public law (``90-148``) or a pre-1957 session-law
#: chapter (``1955:360``). The Congress is bounded so the two shapes cannot
#: overlap: ``1955-360`` would otherwise read as Public Law 1955-360.
_TABLE3_KEY = re.compile(r"(?:[1-9][0-9]{0,2}-[1-9][0-9]*|(?:1[789]|20)[0-9]{2}:[1-9][0-9]*)")
_STATVIEWER_PAGE = re.compile(r"(?P<volume>[0-9]+)\s+Stat\.\s+(?P<page>[0-9]+)")
_DIVISION = re.compile(r"\bdiv\.\s*(?P<division>[A-Z]{1,3})\b")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class UsCodeSourceError(ValueError):
    """The request or response cannot establish the selected OLRC source."""


def _limit(max_bytes: object, name: str = "max_bytes") -> int:
    return limit_byte_bound(max_bytes, name=name, cap=MAX_USCODE_BYTES, error_type=UsCodeSourceError)


def _count(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise UsCodeSourceError(f"{name} must be a positive integer")
    return value


def _body(value: object, max_bytes: int, label: str) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > max_bytes:
        raise UsCodeSourceError(f"{label} must be nonempty bytes within max_bytes")
    return value


def _comparable(citation: str) -> str:
    """The publisher spells one key two ways: ``111-226`` in a URL, ``111–226`` in the page."""
    return re.sub(r"\s+", " ", citation.replace("–", "-").replace("—", "-")).strip()


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# selections and locators
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ReleasePoint:
    """One edition of the Code, named by the last public law folded into it."""

    congress: int
    law: int

    def __post_init__(self) -> None:
        for name, value, ceiling in (("congress", self.congress, 999), ("law", self.law, 99_999)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise UsCodeSourceError(f"{name} must be an integer from 1 to {ceiling}")

    @property
    def label(self) -> str:
        """The publisher's own spelling, as it appears in file names and in ``docPublicationName``."""
        return f"{self.congress}-{self.law}"

    @property
    def path(self) -> str:
        return f"{self.congress}/{self.law}"

    @classmethod
    def from_label(cls, value: str) -> ReleasePoint:
        match = _RELEASE_POINT.fullmatch(value or "")
        if match is None:
            raise UsCodeSourceError("release point label is unsupported")
        return cls(int(match["congress"]), int(match["law"]))


@dataclass(frozen=True, slots=True)
class TitleSelection:
    """One title at one release point, in the publisher's own two-digit code."""

    release_point: ReleasePoint
    title: str

    def __post_init__(self) -> None:
        if not isinstance(self.release_point, ReleasePoint):
            raise UsCodeSourceError("release_point must be a ReleasePoint")
        if self.title not in TITLES:
            raise UsCodeSourceError("title must be one of the codes the publisher lists")

    @property
    def doc_number(self) -> str:
        """The native ``docNumber`` spelling: ``01`` states ``1`` and ``05a`` states ``5a``."""
        return self.title.lstrip("0")

    @property
    def is_appendix(self) -> bool:
        return self.title.endswith("a")

    @property
    def file_name(self) -> str:
        return f"xml_usc{self.title}@{self.release_point.label}.zip"

    @property
    def identifier(self) -> str:
        """The USLM identifier the document carries on its root, when it carries one."""
        return f"/us/usc/t{self.doc_number}"


def title_xml_locator(selection: TitleSelection) -> str:
    """One title's USLM zip at one release point."""
    if not isinstance(selection, TitleSelection):
        raise UsCodeSourceError("selection must be a TitleSelection")
    return f"{OLRC}/download/releasepoints/us/pl/{selection.release_point.path}/{selection.file_name}"


def corpus_xml_locator(release_point: ReleasePoint) -> str:
    """Every title at one release point in one zip of about 108 MB."""
    if not isinstance(release_point, ReleasePoint):
        raise UsCodeSourceError("release_point must be a ReleasePoint")
    return f"{OLRC}/download/releasepoints/us/pl/{release_point.path}/xml_uscAll@{release_point.label}.zip"


def annual_archive_locator(year: int) -> str:
    """One year of the Code as XHTML; the publisher offers 1994 onwards."""
    if type(year) is not int or not FIRST_ANNUAL_YEAR <= year <= 2100:
        raise UsCodeSourceError(f"year must be an integer from {FIRST_ANNUAL_YEAR} to 2100")
    return f"{OLRC}/download/annualhistoricalarchives/XHTML/{year}.zip"


def popular_names_locator() -> str:
    """The whole Popular Name Tool, one generated page of about 11 MB."""
    return f"{OLRC}/popularnames/popularnames.htm"


def table3_file_name(key: str) -> str:
    """The Table III file name for an act key, by the rule the publisher's own page applies.

    ``table3years.htm`` ships ``getActFileName()``: replace the *first* ``-``,
    then the ``:``, with ``_``, drop spaces and periods, append ``.htm``. Both
    key shapes contain exactly one separator, so the single replacement is
    total; the rule is transcribed rather than re-derived.
    """
    if not isinstance(key, str) or _TABLE3_KEY.fullmatch(key) is None:
        raise UsCodeSourceError("Table III key must be a public law or a pre-1957 chapter key")
    return key.replace("-", "_", 1).replace(":", "_", 1) + ".htm"


def table3_act_locator(key: str) -> str:
    """One act's Table III page."""
    return f"{OLRC}/table3/{table3_file_name(key)}"


def table3_bulk_locator() -> str:
    """The whole of Table III in one zip, as ``table3years.htm`` links it."""
    return f"{OLRC}/table3/table3-xml-bulk.zip"


def _visible(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", "".join(parts)).strip()
