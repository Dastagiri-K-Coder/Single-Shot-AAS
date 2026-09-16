# -*- coding: utf-8 -*-
"""
retry.py — Retry decorator for transient Google API errors.

Applies exponential backoff for HTTP 429 (rate limit), 500, and 503 errors
from Google Sheets/Drive API calls.

Usage:
    from aas.core.retry import retry_on_api_error

    @retry_on_api_error()
    def write_to_sheet(name):
        ...
"""

import time
import functools


def retry_on_api_error(max_retries: int = 3, backoff_base: float = 2.0):
    """
    Retry decorator for Google API transient errors (429, 500, 503).

    Args:
        max_retries  : Maximum number of retries before re-raising.
        backoff_base : Base for exponential backoff (seconds).
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e)
                    retryable = any(code in error_str for code in ("429", "500", "503", "ServiceUnavailable"))
                    if not retryable or attempt == max_retries:
                        raise
                    wait = backoff_base ** attempt
                    print(
                        f"  [RETRY] {func.__name__} attempt {attempt + 1}/{max_retries} "
                        f"after {wait:.1f}s: {error_str[:80]}"
                    )
                    time.sleep(wait)
        return wrapper
    return decorator
