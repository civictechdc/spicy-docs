"""Describe a source date without changing its spelling or interpreting an interval."""

from datetime import date


def literal_date_status(value: str | None) -> str:
    """Distinguish absent, empty, valid YYYY-MM-DD and invalid literal dates."""
    if value is None:
        return "absent"
    if value == "":
        return "empty"
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return "invalid"
    return "valid" if parsed.isoformat() == value else "invalid"
