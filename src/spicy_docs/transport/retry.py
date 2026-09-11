"""Bounded HTTP retry timing shared by acquisition commands and tools."""

from __future__ import annotations

import random
import sys
import time
from collections.abc import Callable

# 2026-09-02: a full-history Federal Register crawl lost hours of work to one
# `_ssl.c:993: The handshake operation timed out` — the crawl was competing
# with a heavy S3 fan-out, and 5 attempts capped at 30s of total sleep gave up
# long before the network recovered. 14 attempts (13 possible sleeps) with a
# doubling backoff capped at 60s gives ~542s (~9 minutes) of worst-case
# patience -- on the order of ten minutes, not thirty seconds -- while a
# terminal refusal (a non-429 4xx, or the day's result cap) still fails on
# the first attempt; callers decide which errors are retryable.
MAX_HTTP_ATTEMPTS = 14
RETRY_BACKOFF_CEILING_SECONDS = 60.0


def retry_http[FetchResult](
    operation: Callable[[], FetchResult],
    *,
    retryable: tuple[type[Exception], ...],
) -> FetchResult:
    """Run ``operation`` with capped exponential backoff and full jitter.

    See the ``MAX_HTTP_ATTEMPTS`` comment for why the budget is what it is.
    Full jitter -- a uniform draw between 0 and the deterministic ceiling --
    keeps concurrent fetchers (Federal Register pages, public-table
    partitions) from retrying in lockstep against the same struggling host.
    Each retry is logged to stderr with the attempt number, the chosen delay,
    and the exception that triggered it, so a long retry reads as "working"
    rather than "hung" in an operator's log.
    """

    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
        try:
            return operation()
        except retryable as error:
            if attempt == MAX_HTTP_ATTEMPTS:
                raise
            ceiling = min(2**attempt, RETRY_BACKOFF_CEILING_SECONDS)
            delay = random.uniform(0.0, ceiling)
            print(
                f"source-native fetch: retry {attempt}/{MAX_HTTP_ATTEMPTS - 1} "
                f"in {delay:.1f}s (cap {ceiling:.0f}s) after "
                f"{type(error).__name__}: {error}",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")
