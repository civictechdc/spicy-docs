"""Small markdown rendering helpers shared by the comparison, flow and table renderers."""

from __future__ import annotations


def _ordinal(n: int) -> str:
    """``n`` with an English ordinal suffix, e.g. ``1st``, ``12th``."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _cell(text: object) -> str:
    """Markdown-table-safe cell text: pipe escaped, newlines collapsed, None rendered empty."""
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")
