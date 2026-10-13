# SPDX-License-Identifier: MIT
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay_ms: int = 1000


def calculate_delay(
    attempt: int,
    config: RetryConfig,
    retry_after_ms: float | None = None,
) -> float:
    if retry_after_ms is not None and retry_after_ms > 0:
        return retry_after_ms
    exponential = config.base_delay_ms * (2 ** attempt)
    jitter = exponential * (0.75 + random.random() * 0.5)
    return jitter


def is_retryable(status_code: int) -> bool:
    if status_code == 429:
        return True
    if status_code >= 500:
        return True
    return False


def parse_retry_after(header: str | None) -> float | None:
    if header is None:
        return None
    try:
        seconds = float(header)
        return max(0.0, seconds) * 1000
    except (ValueError, TypeError):
        return None


def sleep_ms(ms: float) -> None:
    time.sleep(ms / 1000.0)


def with_retry(
    fn: Callable[[], T],
    config: RetryConfig | None = None,
) -> T:
    if config is None:
        config = RetryConfig()

    last_error: Exception | None = None
    for attempt in range(config.max_retries + 1):
        try:
            return fn()
        except Exception as err:
            last_error = err
            if attempt == config.max_retries:
                break
            delay = calculate_delay(attempt, config)
            sleep_ms(delay)
    raise last_error  # type: ignore[misc]
