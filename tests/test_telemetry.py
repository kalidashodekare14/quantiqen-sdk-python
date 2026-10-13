# SPDX-License-Identifier: MIT
import json
import re
from unittest.mock import MagicMock, patch

import pytest

from quantiqen_sdk import QuantiqenClient
from quantiqen_sdk.telemetry import (
    TELEMETRY_CATEGORY,
    LogData,
    MetricData,
    PerformanceData,
    SpanData,
    SpanEventData,
    TelemetryCommon,
    build_log_event,
    build_metric_event,
    build_performance_event,
    build_span_event,
)
from quantiqen_sdk.types import ClientOptions

VALID_KEY = "qtn_live_abc123def456ghi789jkl012mno345pqr"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

COMMON = TelemetryCommon(source="my-service")


class TestBuildMetricEvent:
    def test_counter_event_conventions(self):
        event = build_metric_event(
            MetricData(
                name="http.requests",
                kind="counter",
                value=1,
                unit="count",
                labels={"route": "/users", "method": "GET"},
            ),
            COMMON,
        )
        assert event.event_type == "telemetry.metric"
        assert event.event_category == TELEMETRY_CATEGORY
        assert event.severity == "INFO"
        assert event.source == "my-service"
        assert UUID_RE.match(event.idempotency_key)
        assert event.payload == {
            "telemetryType": "metric",
            "metric": {
                "name": "http.requests",
                "kind": "counter",
                "value": 1.0,
                "unit": "count",
                "labels": {"route": "/users", "method": "GET"},
            },
        }

    def test_histogram_with_values(self):
        event = build_metric_event(
            MetricData(
                name="db.query.duration",
                kind="histogram",
                values=[12.5, 40, 8],
            ),
            COMMON,
        )
        assert event.payload["metric"]["values"] == [12.5, 40.0, 8.0]

    def test_explicit_common_fields(self):
        event = build_metric_event(
            MetricData(name="cpu.usage", kind="gauge", value=0.73),
            TelemetryCommon(
                source="host-1",
                occurred_at="2026-01-01T00:00:00+00:00",
                severity="LOW",
                idempotency_key="custom-key-1",
                asset_id="asset-uuid",
                metadata={"environment": "test"},
            ),
        )
        assert event.occurred_at == "2026-01-01T00:00:00+00:00"
        assert event.severity == "LOW"
        assert event.idempotency_key == "custom-key-1"
        assert event.asset_id == "asset-uuid"
        assert event.metadata == {"environment": "test"}

    @pytest.mark.parametrize(
        ("metric", "message"),
        [
            (MetricData(name="", kind="counter", value=1), "metric.name"),
            (MetricData(name="m", kind="nope", value=1), "metric.kind"),  # type: ignore[arg-type]
            (MetricData(name="m", kind="counter"), "metric.value is required"),
            (MetricData(name="m", kind="histogram"), "metric.values"),
            (MetricData(name="m", kind="gauge", value=float("nan")), "metric.value"),
            (
                MetricData(name="m", kind="distribution", values=[1, "x"]),  # type: ignore[list-item]
                "metric.values",
            ),
        ],
    )
    def test_invalid_metric(self, metric, message):
        with pytest.raises(ValueError, match=re.escape(message)):
            build_metric_event(metric, COMMON)

    def test_requires_source(self):
        with pytest.raises(ValueError, match="source is required"):
            build_metric_event(
                MetricData(name="m", kind="gauge", value=1),
                TelemetryCommon(source=""),
            )


class TestBuildSpanEvent:
    VALID = dict(
        trace_id="a1b2c3d4e5f60718293a4b5c6d7e8f90",
        span_id="0123456789abcdef",
        name="GET /users",
        kind="server",
        start_time="2026-01-01T00:00:00+00:00",
        end_time="2026-01-01T00:00:00.120+00:00",
        duration_ms=120,
        status="ok",
        attributes={"http.status_code": 200},
    )

    def test_default_status_unset(self):
        event = build_span_event(
            SpanData(**{**self.VALID, "status": None}), COMMON
        )
        assert event.payload["span"]["status"] == "unset"
        assert "parentSpanId" not in event.payload["span"]
        assert event.event_type == "telemetry.span"

    def test_parent_and_events(self):
        event = build_span_event(
            SpanData(
                **self.VALID,
                parent_span_id="fedcba9876543210",
                events=[
                    SpanEventData(
                        name="exception", time="2026-01-01T00:00:00.100+00:00"
                    )
                ],
            ),
            COMMON,
        )
        span = event.payload["span"]
        assert span["parentSpanId"] == "fedcba9876543210"
        assert len(span["events"]) == 1

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"trace_id": ""}, "span.traceId is required"),
            ({"trace_id": "zzzz"}, "span.traceId must be hexadecimal"),
            ({"span_id": "nothex!!"}, "span.spanId must be hexadecimal"),
            ({"name": ""}, "span.name is required"),
            ({"kind": "weird"}, "span.kind"),  # type: ignore[arg-type]
            ({"start_time": "not-a-date"}, "span.startTime"),
            ({"duration_ms": -1}, "span.durationMs must be >= 0"),
            ({"status": "meh"}, "span.status"),  # type: ignore[arg-type]
        ],
    )
    def test_invalid_span(self, overrides, message):
        with pytest.raises(ValueError, match=re.escape(message)):
            build_span_event(SpanData(**{**self.VALID, **overrides}), COMMON)


class TestBuildPerformanceEvent:
    def test_valid_event(self):
        event = build_performance_event(
            PerformanceData(
                operation="POST /checkout",
                duration_ms=842.5,
                status="ok",
                throughput_per_sec=120,
                error_rate=0.01,
                resource="checkout-service",
                dimensions={"region": "eu-west-1"},
            ),
            COMMON,
        )
        assert event.event_type == "telemetry.performance"
        assert event.payload["telemetryType"] == "performance"
        assert event.payload["performance"]["durationMs"] == 842.5

    @pytest.mark.parametrize(
        ("perf", "message"),
        [
            (PerformanceData(operation="", duration_ms=1), "performance.operation"),
            (
                PerformanceData(operation="op", duration_ms=-5),
                "performance.durationMs must be >= 0",
            ),
            (
                PerformanceData(operation="op", duration_ms=1, status="meh"),  # type: ignore[arg-type]
                "performance.status",
            ),
            (
                PerformanceData(operation="op", duration_ms=1, error_rate=1.5),
                "performance.errorRate",
            ),
            (
                PerformanceData(
                    operation="op", duration_ms=1, throughput_per_sec=-1
                ),
                "performance.throughputPerSec",
            ),
        ],
    )
    def test_invalid_performance(self, perf, message):
        with pytest.raises(ValueError, match=re.escape(message)):
            build_performance_event(perf, COMMON)


class TestBuildLogEvent:
    def test_error_log_maps_to_high(self):
        event = build_log_event(
            LogData(
                level="error",
                message="checkout failed",
                attributes={"orderId": "o-1"},
            ),
            COMMON,
        )
        assert event.severity == "HIGH"
        assert event.event_type == "telemetry.log"
        assert event.payload == {
            "telemetryType": "log",
            "log": {
                "level": "error",
                "message": "checkout failed",
                "attributes": {"orderId": "o-1"},
            },
        }

    @pytest.mark.parametrize(
        ("level", "severity"),
        [
            ("debug", "INFO"),
            ("info", "INFO"),
            ("warn", "MEDIUM"),
            ("error", "HIGH"),
            ("fatal", "CRITICAL"),
        ],
    )
    def test_level_to_severity(self, level, severity):
        event = build_log_event(LogData(level=level, message="x"), COMMON)
        assert event.severity == severity

    def test_invalid_level_and_message(self):
        with pytest.raises(ValueError, match="log.level"):
            build_log_event(
                LogData(level="verbose", message="x"), COMMON  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError, match="log.message is required"):
            build_log_event(LogData(level="info", message=""), COMMON)


class TestClientTelemetry:
    @staticmethod
    def _client(logger=None):
        return QuantiqenClient(
            ClientOptions(
                api_key=VALID_KEY,
                batch_size=100,
                flush_interval_ms=60000,
                logger=logger or (lambda msg: None),
            )
        )

    @staticmethod
    def _mock_resp():
        resp = MagicMock()
        resp.headers = {}
        resp.read.return_value = json.dumps({}).encode("utf-8")
        return resp

    def test_send_metric_bulk_payload(self):
        client = self._client()
        try:
            with patch(
                "urllib.request.urlopen", return_value=self._mock_resp()
            ) as mock_open:
                client.send_metric(
                    MetricData(name="http.requests", kind="counter", value=1),
                    TelemetryCommon(source="api"),
                )
                client.flush()

            body = json.loads(
                mock_open.call_args[0][0].data.decode("utf-8")
            )
            event = body["events"][0]
            assert event["eventCategory"] == "telemetry"
            assert event["eventType"] == "telemetry.metric"
            assert UUID_RE.match(event["idempotencyKey"])
            assert event["payload"]["telemetryType"] == "metric"
            assert event["metadata"]["sdkLanguage"] == "python"
            assert event["metadata"]["sdkVersion"] == "0.1.0"
        finally:
            client.shutdown()

    def test_send_log_and_span_bulk_path(self):
        client = self._client()
        try:
            with patch(
                "urllib.request.urlopen", return_value=self._mock_resp()
            ) as mock_open:
                client.send_log(
                    LogData(level="warn", message="slow query"),
                    TelemetryCommon(source="db"),
                )
                client.send_span(
                    SpanData(
                        trace_id="a1b2c3d4e5f60718293a4b5c6d7e8f90",
                        span_id="0123456789abcdef",
                        name="db.query",
                        kind="client",
                        start_time="2026-01-01T00:00:00+00:00",
                    ),
                    TelemetryCommon(source="db"),
                )
                client.flush()

            body = json.loads(
                mock_open.call_args[0][0].data.decode("utf-8")
            )
            assert len(body["events"]) == 2
            assert body["events"][0]["payload"]["telemetryType"] == "log"
            assert body["events"][0]["severity"] == "MEDIUM"
            assert body["events"][1]["payload"]["telemetryType"] == "span"
            assert UUID_RE.match(body["events"][1]["idempotencyKey"])
        finally:
            client.shutdown()

    def test_invalid_input_logs_and_never_raises(self):
        logger = MagicMock()
        client = self._client(logger=logger)
        try:
            with patch("urllib.request.urlopen") as mock_open:
                client.send_metric(
                    MetricData(name="", kind="counter", value=1),
                    TelemetryCommon(source="x"),
                )
                client.flush()

            mock_open.assert_not_called()
            assert any(
                "Failed to enqueue metric telemetry" in call.args[0]
                for call in logger.call_args_list
            )
        finally:
            client.shutdown()
