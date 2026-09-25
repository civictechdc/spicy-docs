"""Bounded HTTP retry timing shared by acquisition commands and tools."""

from __future__ import annotations

import random
import sys
import time
from collections.abc import Callable

from spicy_docs.transport.credentials import failure_reason

# Allow temporary network congestion ~542s of total sleep across 13 retries.
# Callers classify errors; terminal refusals still fail on the first attempt.
MAX_HTTP_ATTEMPTS = 14
RETRY_BACKOFF_CEILING_SECONDS = 60.0


def retry_http[FetchResult](
    operation: Callable[[], FetchResult],
    *,
    retryable: tuple[type[Exception], ...],
    max_attempts: int | None = None,
    api_key: str = "",
) -> FetchResult:
    """Run operation with capped exponential backoff and full jitter.

    max_attempts includes the initial attempt and defaults to MAX_HTTP_ATTEMPTS.
    A uniform delay from zero to the ceiling separates concurrent fetchers' retries,
    and each retry logs its attempt, delay and scrubbed exception to stderr.
    Callers using credentials must supply api_key unless they already replace or
    scrub exception text; keyless callers still get query-parameter scrubbing.
    """

    attempts = MAX_HTTP_ATTEMPTS if max_attempts is None else max_attempts
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts <= 0:
        raise ValueError("max_attempts must be a positive integer")
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except retryable as error:
            if attempt == attempts:
                raise
            ceiling = min(2**attempt, RETRY_BACKOFF_CEILING_SECONDS)
            delay = random.uniform(0.0, ceiling)
            # A later success bypasses the caller's error-row scrub. Scrub here,
            # before truncation can leave a partial credential in the log.
            reason = failure_reason(error, api_key)
            print(
                f"source-native fetch: retry {attempt}/{attempts - 1} "
                f"in {delay:.1f}s (cap {ceiling:.0f}s) after "
                f"{reason}",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")
