# SPDX-License-Identifier: MIT
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .types import EventData


class EventBatcher:
    def __init__(
        self,
        batch_size: int,
        flush_interval_ms: int,
        on_flush: Callable[[list[EventData]], None],
        logger: Callable[[str], None],
    ) -> None:
        self._batch_size = batch_size
        self._flush_interval_ms = flush_interval_ms
        self._on_flush = on_flush
        self._logger = logger

        self._queue: list[EventData] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._flushing = False

        self._rate_limit_remaining: float | None = None
        self._rate_limit_retry_after_ms: float | None = None
        self._rate_limit_paused_until: float = 0.0

    def add(self, event: EventData) -> None:
        with self._lock:
            self._queue.append(event)
            if len(self._queue) >= self._batch_size:
                self._flush_async()

    def start(self) -> None:
        if self._timer is not None:
            return
        self._schedule_timer()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def flush(self) -> None:
        if self._flushing:
            return

        now = time.time()
        if now < self._rate_limit_paused_until:
            wait_ms = (self._rate_limit_paused_until - now) * 1000
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        # The Retry-After pause has elapsed (or was never set) — drop the
        # stale delay so it is not re-applied to every later flush.
        if time.time() >= self._rate_limit_paused_until:
            self._rate_limit_retry_after_ms = None

        self._flushing = True
        try:
            delay = self._calculate_throttle_delay()
            if delay > 0:
                time.sleep(delay / 1000.0)
            while True:
                with self._lock:
                    if not self._queue:
                        return
                    batch = self._queue[: self._batch_size]
                    self._queue = self._queue[self._batch_size :]
                try:
                    self._on_flush(batch)
                except Exception as err:
                    self._logger(f"[quantiqen-sdk] Flush failed: {err}")
                    break
        finally:
            self._flushing = False

    def shutdown(self) -> None:
        self.stop()
        self.flush()

    def update_rate_limit(self, headers: dict[str, str]) -> None:
        remaining = headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                self._rate_limit_remaining = float(remaining)
            except (ValueError, TypeError):
                pass

        retry_after = headers.get("retry-after")
        if retry_after is not None:
            try:
                ms = float(retry_after) * 1000
                if ms > 0:
                    self._rate_limit_retry_after_ms = ms
                    self._rate_limit_paused_until = time.time() + (ms / 1000.0)
            except (ValueError, TypeError):
                pass

    def get_queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def _schedule_timer(self) -> None:
        self._timer = threading.Timer(
            self._flush_interval_ms / 1000.0, self._timer_callback
        )
        self._timer.daemon = True
        self._timer.start()

    def _timer_callback(self) -> None:
        self._flush_async()
        self._schedule_timer()

    def _flush_async(self) -> None:
        t = threading.Thread(target=self.flush, daemon=True)
        t.start()

    def _calculate_throttle_delay(self) -> float:
        if self._rate_limit_retry_after_ms is not None:
            return self._rate_limit_retry_after_ms

        remaining = self._rate_limit_remaining
        if remaining is not None and remaining < 5:
            return (5 - remaining) * 500

        return 0.0
