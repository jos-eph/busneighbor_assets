#!/usr/bin/env python3
"""Retrying HTTP fetch, shared by the GTFS build and the real-time sampler.

Stdlib only, and deliberately so. Both callers want the same backoff, but only
the sampler may import protobuf — keeping the loop here lets them share it
without pulling a third-party package into the release workflow.
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request

ATTEMPTS = 3
INITIAL_DELAY_S = 30
BACKOFF = 4


def is_retryable(exc: Exception) -> bool:
    """Whether another attempt could plausibly succeed.

    A 4xx will not fix itself: a wrong URL, or the User-Agent filter SEPTA's
    mirror applies to `Python-urllib`. Retrying one costs two and a half
    minutes and then reports the last failure, which reads like a network
    fault rather than the request bug it is.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    return True


def with_retries(operation, describe: str, *, attempts: int = ATTEMPTS,
                 initial_delay: float = INITIAL_DELAY_S, sleep=time.sleep):
    """Call operation(), retrying retryable failures with exponential backoff."""
    delay = initial_delay
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            retryable = is_retryable(exc)
            print(
                f"{describe} attempt {attempt}/{attempts} failed: {exc}"
                + ("" if retryable else " (not retryable)"),
                file=sys.stderr,
            )
            if attempt == attempts or not retryable:
                raise
            sleep(delay)
            delay *= BACKOFF


def get_bytes(url: str, *, user_agent: str, timeout: int = 60,
              sleep=time.sleep) -> bytes:
    """Fetch a URL into memory, sending an explicit User-Agent."""
    def once() -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    return with_retries(once, f"GET {url}", sleep=sleep)
