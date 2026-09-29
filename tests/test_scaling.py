"""The scaling helper itself: a linear reader passes, a quadratic one fails, a runaway one is stopped after two
overruns in a row, and one overrun alone is noise it rides out."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from tests import scaling

#: Catastrophic backtracking: each added ``a`` doubles the work, so eight more cost 256 times as much.
_RUNAWAY = re.compile(r"(a+)+$")


def _linear(text: str) -> int:
    return sum(1 for character in text if character == "a")


def _quadratic(text: str) -> int:
    return sum(text.count(character) for character in text[: len(text) // 4] * 4)


def test_a_linear_reader_passes() -> None:
    scaling.assert_scales(_linear, "ab" * 5_000, "ab" * 10_000, bound=3)


def test_a_quadratic_reader_fails() -> None:
    """Doubling costs it four times the work, over the bound of three; on its ratio, or, on a machine slow enough
    to overrun twice, as far past linear."""
    with pytest.raises(AssertionError, match=r"times the smaller one, over 3|far past linear"):
        scaling.assert_scales(_quadratic, "ab" * 1_000, "ab" * 2_000, bound=3)


def test_a_runaway_reader_is_stopped_after_two_overruns_in_a_row() -> None:
    with pytest.raises(AssertionError, match="twice in a row .* far past linear"):
        scaling.assert_scales(_RUNAWAY.match, "a" * 12 + "b", "a" * 24 + "b", bound=3)


def test_one_overrun_alone_is_ridden_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run that costs more CPU per instruction (a move to an efficiency core) overruns once; the next run
    decides. Simulated: the first measurement of the larger input reads as stopped."""
    real = scaling._within_cpu
    calls: list[float] = []

    def once_stopped(seconds: float, action: Callable[[], float]) -> float | None:
        calls.append(seconds)
        return None if len(calls) == 1 else real(seconds, action)

    monkeypatch.setattr(scaling, "_within_cpu", once_stopped)
    scaling.assert_scales(_linear, "ab" * 5_000, "ab" * 10_000, bound=3)
    assert len(calls) == scaling.RUNS
