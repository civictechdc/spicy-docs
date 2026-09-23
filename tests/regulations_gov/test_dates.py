"""Eastern calendar days: a deadline is the Eastern day it closes on under either offset, a bare UTC midnight
keeps its printed date, and absent or unreadable values state nothing.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from spicy_docs.source_native.regulations_gov import (
    REGULATIONS_GOV_ZONE,
    regulations_gov_day,
    regulations_gov_instant,
)


@pytest.mark.parametrize(
    "value,day,offset_hours",
    [
        # Deadlines, 11:59:59 PM Eastern, as the live API printed them on 2026-09-23.
        ("2026-09-25T03:59:59Z", date(2026, 9, 24), -4),
        ("2026-01-06T04:59:59Z", date(2026, 1, 5), -5),
        # Either side of both 2026 clock changes (March 8, November 1).
        ("2026-03-08T04:59:59Z", date(2026, 3, 7), -5),
        ("2026-03-09T03:59:59Z", date(2026, 3, 8), -4),
        ("2026-11-01T03:59:59Z", date(2026, 10, 31), -4),
        ("2026-11-02T04:59:59Z", date(2026, 11, 1), -5),
        # Starts, Eastern midnight.
        ("2026-09-24T04:00:00Z", date(2026, 9, 24), -4),
        ("2026-01-05T05:00:00Z", date(2026, 1, 5), -5),
        # SQL Server's minimum date, through New York's local mean time (3 retained deadlines).
        ("1753-01-02T04:56:01Z", date(1753, 1, 1), None),
    ],
)
def test_an_instant_names_its_eastern_day(value, day, offset_hours):
    """The day is the Eastern one, never the UTC prefix; the instant keeps the publisher's moment."""
    instant = regulations_gov_instant(value)
    assert instant is not None and instant.tzinfo is REGULATIONS_GOV_ZONE
    assert instant == datetime.fromisoformat(value)
    assert regulations_gov_day(value) == instant.date() == day
    if offset_hours is not None:
        assert instant.utcoffset() == timedelta(hours=offset_hours)
    if value.endswith("59Z"):
        # A deadline's UTC date is the day after it closes.
        assert instant.time().isoformat() == "23:59:59" and date.fromisoformat(value[:10]) == day + timedelta(days=1)


@pytest.mark.parametrize("value", ["2025-06-02T00:00:00Z", "2025-06-02", " 2025-06-02 "])
def test_a_date_only_value_keeps_its_printed_day_and_states_no_instant(value):
    """A bare UTC midnight is a date, not Eastern 8 PM of the day before."""
    assert regulations_gov_day(value) == date(2025, 6, 2)
    assert regulations_gov_instant(value) is None


@pytest.mark.parametrize("value", ["20240101", "2024-W01-1"])
def test_other_iso_spellings_read_as_their_date_as_the_spicy_regs_rule_did(value):
    """Basic and ISO-week dates that ``fromisoformat`` reads give their day and no instant."""
    assert regulations_gov_day(value) == date(2024, 1, 1)
    assert regulations_gov_instant(value) is None


def test_a_timestamp_without_an_offset_keeps_its_printed_day_and_states_no_instant():
    """Without an offset there is no instant to convert; the printed date stands."""
    assert regulations_gov_day("2025-06-02T23:30:00") == date(2025, 6, 2)
    assert regulations_gov_instant("2025-06-02T23:30:00") is None


@pytest.mark.parametrize("value", [None, "", "  ", "not a date", "2025-13-01", "2025-02-30T00:00:00Z", "2025-06"])
def test_absent_or_unreadable_values_state_nothing(value):
    """None, blank and malformed values give neither a day nor an instant."""
    assert regulations_gov_day(value) is None
    assert regulations_gov_instant(value) is None
