"""Regulations.gov states dates and instants on the Eastern clock; read their calendar day there.

The publisher bounds a comment window at Eastern midnight and 11:59:59 PM Eastern
and prints the instant in UTC, so a deadline's UTC date is the next day. The
receipt is ``supply-2026-09-02/receipts/regulations-gov-eastern-day-2026-09-23``:

- In the retained rulemaking build (``documents.parquet``, 2026-09-23) every one
  of the 527,366 ``commentEndDate`` values is 23:59:59 Eastern: 336,564 at
  ``03:59:59Z`` (EDT), 190,799 at ``04:59:59Z`` (EST), and 3 at
  ``1753-01-0xT04:56:01Z``, SQL Server's minimum date through New York's
  local mean time. DuckDB's ICU zones and Python's zoneinfo agree.
- Two live API v4 pages (2026-09-23), one EDT and one EST window: all 500
  deadlines are 23:59:59 Eastern.
- A bare ``T00:00:00Z`` is a date-only value, not Eastern 8 PM: 6,010 of the
  1,209,307 retained ``commentStartDate`` values print it, and of those that
  carry a Federal Register publication date 5,494 of 5,551 equal it, 6 equal the
  Eastern day (SpicyRegs ``build_comment_periods``, 2026-09-23).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Final
from zoneinfo import ZoneInfo

REGULATIONS_GOV_ZONE: Final = ZoneInfo("America/New_York")
_DATE_ONLY: Final = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})(?:T00:00:00Z)?")


def regulations_gov_instant(value: str | None) -> datetime | None:
    """The instant a Regulations.gov timestamp states, on the Eastern clock.

    None when absent, unreadable, without a UTC offset, or date-only (a bare
    date or ``T00:00:00Z``): those state a day, not an instant.
    """
    text = (value or "").strip()
    if _DATE_ONLY.fullmatch(text):
        return None
    try:
        instant = datetime.fromisoformat(text)
    except ValueError:
        return None
    return instant.astimezone(REGULATIONS_GOV_ZONE) if instant.utcoffset() is not None else None


def regulations_gov_day(value: str | None) -> date | None:
    """The Eastern calendar day a Regulations.gov date or timestamp names; None when absent or unreadable.

    A date-only value keeps its printed date, as does a timestamp without an offset.
    """
    text = (value or "").strip()
    if (match := _DATE_ONLY.fullmatch(text)) is not None:
        text = match[1]
    elif (instant := regulations_gov_instant(text)) is not None:
        return instant.date()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None
