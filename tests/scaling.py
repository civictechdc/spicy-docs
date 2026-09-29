"""Whether a reader's cost grows linearly with its input, measured as counted work rather than wall-clock time.

The work is the CPU's retired-instruction count where the platform gives it to an unprivileged process, macOS's
``proc_pid_rusage``, which other work on a busy machine does not move: the nine identifier-shape values grew 3.53 to
4.13 times on quadrupling, each within 2.1% of itself at load 60 (independent review, 2026-09-28, receipt
``fork-execution-2026-09-21/cbo-112-113/review-2/linearity/``). Elsewhere, Linux CI included, it is the process's CPU
time. Two guards make either unit trustworthy:

- each measurement repeats the read until the smaller input costs at least ``MIN_SMALL_SECONDS`` of CPU, because a
  0.06 ms read held to a 1 ms floor asserted only that the larger one took under 8 ms;
- a measurement of the larger input that spends ``OVERRUN`` times the CPU ``bound`` allows it is stopped, and two
  such runs in a row fail, because the cubic regression these tests guard against took 713 s to fail a plain loop.
  A CPU-time timer signal interrupts Python code and the regular-expression engine alike. Twice the bound leaves a
  linear reader about four times its usual CPU (3.5-4.2 times the smaller read under load 60-78, against 16), yet
  one run can cost 2.7 times more CPU per instruction when the process moves from a performance to an efficiency
  core (second review, round 2), so one overrun alone is noise; a gross regression overruns every run. The cubic
  mutant, whose smaller read alone takes seconds, stops after two larger reads' allowances, not five whole reads.
"""

from __future__ import annotations

import ctypes
import gc
import math
import os
import signal
import sys
import threading
import time
from collections.abc import Callable

#: The least CPU a measurement of the smaller input spends; the read repeats until it does.
MIN_SMALL_SECONDS = 5e-3
#: A read of the larger input may spend this many times ``bound`` times the smaller one's CPU before it is stopped.
OVERRUN = 2
#: Interleaved measurements of each input; the least of each counts, so a burst on one run drops out.
RUNS = 5


class _RusageInfoV4(ctypes.Structure):
    """``struct rusage_info_v4`` (``<sys/resource.h>``): a uuid, 29 counters, the instruction count, then more.

    Padded past the kernel's size, which it writes whole."""

    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16),
        ("before", ctypes.c_uint64 * 29),
        ("instructions", ctypes.c_uint64),
        ("after", ctypes.c_uint64 * 16),
    ]


def _instruction_counter() -> Callable[[], int] | None:
    """This process's retired instructions so far, or ``None`` where the platform does not count them."""
    if sys.platform != "darwin":
        return None
    try:
        call = ctypes.CDLL("/usr/lib/libSystem.B.dylib").proc_pid_rusage
    except (OSError, AttributeError):
        return None
    call.argtypes, call.restype = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p), ctypes.c_int
    info = _RusageInfoV4()

    def instructions() -> int:
        if call(os.getpid(), 4, ctypes.byref(info)) != 0:  # RUSAGE_INFO_V4
            raise OSError("proc_pid_rusage refused")
        return int(info.instructions)

    try:
        before = instructions()
        sum(range(10_000))
        counted = instructions() > before
    except OSError:
        return None
    return instructions if counted else None


_INSTRUCTIONS = _instruction_counter()
#: The unit a failure reports.
WORK_UNIT = "instructions" if _INSTRUCTIONS is not None else "CPU seconds"


class _Overrun(Exception):
    """The larger input's read spent its CPU allowance."""


def _within_cpu(seconds: float, action: Callable[[], float]) -> float | None:
    """``action()``, or ``None`` once this process has spent ``seconds`` of CPU on it.

    Without a CPU-time timer (a platform with no ``setitimer``, or off the main thread) it simply runs.
    """
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        return action()

    def expire(_signum: int, _frame: object) -> None:
        raise _Overrun

    previous = signal.signal(signal.SIGPROF, expire)
    try:
        signal.setitimer(signal.ITIMER_PROF, seconds)
        try:
            return action()
        finally:
            signal.setitimer(signal.ITIMER_PROF, 0)
    except _Overrun:
        return None
    finally:
        signal.signal(signal.SIGPROF, previous)


def _cost(read: Callable[[str], object], text: str, repeats: int) -> tuple[float, float]:
    """The work and CPU seconds of ``repeats`` reads of ``text``."""
    started, counted = time.process_time(), _INSTRUCTIONS() if _INSTRUCTIONS is not None else 0
    for _ in range(repeats):
        read(text)
    seconds = time.process_time() - started
    return float(_INSTRUCTIONS() - counted) if _INSTRUCTIONS is not None else seconds, seconds


def assert_scales(read: Callable[[str], object], small: str, large: str, *, bound: float) -> None:
    """Fail unless reading ``large`` costs less than ``bound`` times reading ``small``, in counted work.

    The least of ``RUNS`` interleaved measurements of each, each ``repeats`` reads long, with the cyclic collector
    paused. A measurement of ``large`` that spends ``OVERRUN * bound`` times the smaller one's CPU is stopped and
    left out; a second in a row fails.
    """
    one = _cost(read, small, 1)[1]  # a first read also compiles and caches what later ones reuse
    if one < MIN_SMALL_SECONDS:  # a slow first read already says one read is enough; a fast one may be noise
        one = min(_cost(read, small, 1)[1] for _ in range(3))
    repeats = max(1, math.ceil(MIN_SMALL_SECONDS / max(one, 1e-7)))
    least_small = least_large = math.inf
    overran = False
    enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(RUNS):
            work, seconds = _cost(read, small, repeats)
            least_small = min(least_small, work)
            allowance = max(0.25, OVERRUN * bound * seconds)
            large_work = _within_cpu(allowance, lambda: _cost(read, large, repeats)[0])
            if large_work is None and overran:
                raise AssertionError(
                    f"reading the larger input twice in a row spent over {allowance:.2f} s of CPU, {OVERRUN * bound:g} "
                    f"times the smaller one's {seconds:.4f} s ({repeats} reads each): far past linear"
                )
            overran = large_work is None
            if large_work is not None:
                least_large = min(least_large, large_work)
    finally:
        if enabled:
            gc.enable()
    if not least_large < bound * least_small:
        raise AssertionError(
            f"reading the larger input cost {least_large / least_small:.2f} times the smaller one, over {bound:g} "
            f"({least_small:.4g} and {least_large:.4g} {WORK_UNIT}, {repeats} reads each)"
        )
