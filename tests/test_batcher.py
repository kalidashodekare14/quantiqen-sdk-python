import time
import threading
from unittest.mock import MagicMock

import pytest

from quantiqen_sdk.batcher import EventBatcher
from quantiqen_sdk.types import EventData


def make_event(**overrides) -> EventData:
    defaults = {
        "event_type": "test.event",
        "event_category": "test",
        "severity": "INFO",
        "source": "test",
        "occurred_at": "2026-01-01T00:00:00Z",
        "payload": {"key": "value"},
    }
    defaults.update(overrides)
    return EventData(**defaults)


class TestEventBatcher:
    def test_add_increases_queue(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=10,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.add(make_event())
        assert batcher.get_queue_size() == 1

    def test_flush_on_batch_size(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=3,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.add(make_event())
        batcher.add(make_event())
        batcher.add(make_event())
        time.sleep(0.05)
        assert on_flush.call_count == 1
        assert len(on_flush.call_args[0][0]) == 3

    def test_manual_flush(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=100,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.add(make_event())
        batcher.flush()
        assert on_flush.call_count == 1

    def test_correct_payload_shape(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=2,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.add(make_event())
        batcher.add(make_event())
        time.sleep(0.05)
        payload = on_flush.call_args[0][0]
        assert hasattr(payload[0], "event_type")
        assert hasattr(payload[0], "payload")

    def test_empty_not_flushed(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=10,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.flush()
        assert on_flush.call_count == 0

    def test_shutdown_flushes_remaining(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=100,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.add(make_event())
        batcher.add(make_event())
        batcher.shutdown()
        assert on_flush.call_count == 1
        assert len(on_flush.call_args[0][0]) == 2

    def test_handles_flush_error(self):
        logger = MagicMock()
        batcher = EventBatcher(
            batch_size=100,
            flush_interval_ms=60000,
            on_flush=MagicMock(side_effect=RuntimeError("network error")),
            logger=logger,
        )
        batcher.add(make_event())
        batcher.flush()
        logger.assert_called_once()
        assert "Flush failed" in logger.call_args[0][0]

    def test_flush_drains_entire_queue(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=2,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher._queue = [make_event() for _ in range(5)]

        batcher.flush()

        assert batcher.get_queue_size() == 0
        assert on_flush.call_count == 3
        assert [len(c[0][0]) for c in on_flush.call_args_list] == [2, 2, 1]


class TestRateLimitThrottling:
    def test_defers_flush_when_remaining_low(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=100,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.update_rate_limit({"x-ratelimit-remaining": "2"})
        batcher.add(make_event())

        start = time.time()
        batcher.flush()
        elapsed = time.time() - start

        assert elapsed >= 1.3
        assert on_flush.call_count == 1

    def test_pauses_on_429(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=100,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.update_rate_limit({"retry-after": "1"})

        start = time.time()
        batcher.flush()
        elapsed = time.time() - start

        assert elapsed >= 0.9

    def test_no_delay_when_remaining_high(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=100,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.update_rate_limit({"x-ratelimit-remaining": "10"})
        batcher.add(make_event())

        start = time.time()
        batcher.flush()
        elapsed = time.time() - start

        assert elapsed < 0.5

    def test_resets_stale_retry_after_after_pause(self):
        on_flush = MagicMock()
        batcher = EventBatcher(
            batch_size=100,
            flush_interval_ms=60000,
            on_flush=on_flush,
            logger=lambda msg: None,
        )
        batcher.update_rate_limit({"retry-after": "1"})
        batcher.add(make_event())

        start = time.time()
        batcher.flush()
        assert time.time() - start >= 0.9

        # The pause has elapsed — the next flush must not re-apply it.
        batcher.add(make_event())
        start = time.time()
        batcher.flush()
        assert time.time() - start < 0.5
        assert on_flush.call_count == 2
