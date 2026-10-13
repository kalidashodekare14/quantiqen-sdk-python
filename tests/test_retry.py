import pytest
from unittest.mock import patch

from quantiqen_sdk.retry import (
    RetryConfig,
    calculate_delay,
    is_retryable,
    parse_retry_after,
    with_retry,
)


class TestCalculateDelay:
    def test_returns_retry_after_when_positive(self):
        config = RetryConfig(max_retries=3, base_delay_ms=1000)
        assert calculate_delay(0, config, retry_after_ms=5000) == 5000

    def test_ignores_retry_after_when_zero(self):
        config = RetryConfig(max_retries=3, base_delay_ms=1000)
        delay = calculate_delay(0, config, retry_after_ms=0)
        assert 750 <= delay <= 1250

    def test_ignores_retry_after_when_negative(self):
        config = RetryConfig(max_retries=3, base_delay_ms=1000)
        delay = calculate_delay(0, config, retry_after_ms=-100)
        assert 750 <= delay <= 1250

    @patch("quantiqen_sdk.retry.random.random", return_value=0.5)
    def test_exponential_delay_increases(self, _mock_random):
        config = RetryConfig(max_retries=3, base_delay_ms=1000)
        delays = [calculate_delay(i, config) for i in range(4)]
        assert delays[0] < delays[1] < delays[2] < delays[3]

    def test_jitter_within_tolerance(self):
        config = RetryConfig(max_retries=3, base_delay_ms=1000)
        delays = [calculate_delay(1, config) for _ in range(20)]
        assert min(delays) >= 1500
        assert max(delays) <= 2500


class TestIsRetryable:
    def test_retries_on_429(self):
        assert is_retryable(429) is True

    def test_retries_on_500(self):
        assert is_retryable(500) is True

    def test_retries_on_503(self):
        assert is_retryable(503) is True

    def test_no_retry_on_400(self):
        assert is_retryable(400) is False

    def test_no_retry_on_401(self):
        assert is_retryable(401) is False

    def test_no_retry_on_403(self):
        assert is_retryable(403) is False

    def test_no_retry_on_404(self):
        assert is_retryable(404) is False

    def test_no_retry_on_422(self):
        assert is_retryable(422) is False


class TestParseRetryAfter:
    def test_parses_numeric(self):
        assert parse_retry_after("30") == 30000.0

    def test_returns_none_for_none(self):
        assert parse_retry_after(None) is None

    def test_returns_none_for_non_numeric(self):
        assert parse_retry_after("bad") is None

    def test_clamps_negative(self):
        assert parse_retry_after("-5") == 0.0


class TestWithRetry:
    def test_returns_on_first_success(self):
        fn = lambda: "ok"  # noqa: E731
        result = with_retry(fn, RetryConfig(max_retries=2, base_delay_ms=10))
        assert result == "ok"

    def test_retries_and_succeeds(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("fail")
            return "ok"

        result = with_retry(fn, RetryConfig(max_retries=2, base_delay_ms=10))
        assert result == "ok"
        assert call_count == 2

    def test_throws_after_max_retries(self):
        def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            with_retry(fn, RetryConfig(max_retries=2, base_delay_ms=10))
