# SPDX-License-Identifier: MIT
"""Telemetry conventions — typed models riding the existing events envelope.

The platform's wire contract is the generic event DTO (free-form JSON
payload); telemetry records carry a discriminated ``payload.telemetryType``
plus exactly one of metric/span/performance/log. Builders validate strictly
and raise ValueError; the client's send_* helpers catch and log instead —
fire-and-forget, matching the SDK contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping
from uuid import uuid4

from .types import EventData, Severity

TELEMETRY_CATEGORY = "telemetry"

TelemetryType = Literal["metric", "span", "performance", "log"]
MetricKind = Literal["counter", "gauge", "histogram", "distribution"]
SpanKind = Literal["internal", "server", "client", "producer", "consumer"]
SpanStatus = Literal["ok", "error", "unset"]
PerformanceStatus = Literal["ok", "error"]
TelemetryLogLevel = Literal["debug", "info", "warn", "error", "fatal"]

METRIC_KINDS = {"counter", "gauge", "histogram", "distribution"}
SPAN_KINDS = {"internal", "server", "client", "producer", "consumer"}
SPAN_STATUSES = {"ok", "error", "unset"}
LOG_LEVELS = {"debug", "info", "warn", "error", "fatal"}

LOG_LEVEL_SEVERITY: dict[str, Severity] = {
    "debug": "INFO",
    "info": "INFO",
    "warn": "MEDIUM",
    "error": "HIGH",
    "fatal": "CRITICAL",
}

_HEX_DIGITS = set("0123456789abcdefABCDEF")


@dataclass
class TelemetryCommon:
    source: str
    occurred_at: str | None = None
    severity: Severity | None = None
    asset_id: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass
class MetricData:
    name: str
    kind: MetricKind
    value: float | None = None
    values: list[float] | None = None
    unit: str | None = None
    labels: Mapping[str, Any] | None = None


@dataclass
class SpanEventData:
    name: str
    time: str
    attributes: Mapping[str, Any] | None = None


@dataclass
class SpanData:
    trace_id: str
    span_id: str
    name: str
    kind: SpanKind
    start_time: str
    parent_span_id: str | None = None
    end_time: str | None = None
    duration_ms: float | None = None
    status: SpanStatus | None = None
    attributes: Mapping[str, Any] | None = None
    events: list[SpanEventData] | None = None


@dataclass
class PerformanceData:
    operation: str
    duration_ms: float
    status: PerformanceStatus | None = None
    throughput_per_sec: float | None = None
    error_rate: float | None = None
    resource: str | None = None
    dimensions: Mapping[str, Any] | None = None


@dataclass
class LogData:
    level: TelemetryLogLevel
    message: str
    attributes: Mapping[str, Any] | None = None


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value


def _require_finite(value: float, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number")
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{field_name} must be a finite number")
    return float(value)


def _require_hex(value: str, field_name: str) -> str:
    _require_non_empty(value, field_name)
    if not all(ch in _HEX_DIGITS for ch in value):
        raise ValueError(f"{field_name} must be hexadecimal")
    return value


def _require_iso(value: str, field_name: str) -> str:
    _require_non_empty(value, field_name)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from err
    return value


def _base_event(
    telemetry_type: TelemetryType,
    event_type: str,
    payload: dict[str, Any],
    common: TelemetryCommon,
    severity: Severity | None = None,
) -> EventData:
    _require_non_empty(common.source, "source")
    return EventData(
        event_type=event_type,
        event_category=TELEMETRY_CATEGORY,
        severity=severity or common.severity or "INFO",
        source=common.source,
        occurred_at=common.occurred_at
        or datetime.now(timezone.utc).isoformat(),
        event_version="1.0",
        idempotency_key=common.idempotency_key or str(uuid4()),
        payload={"telemetryType": telemetry_type, **payload},
        asset_id=common.asset_id,
        metadata=dict(common.metadata) if common.metadata is not None else None,
    )


def build_metric_event(metric: MetricData, common: TelemetryCommon) -> EventData:
    _require_non_empty(metric.name, "metric.name")
    if metric.kind not in METRIC_KINDS:
        raise ValueError(f"metric.kind must be one of: {sorted(METRIC_KINDS)}")

    data: dict[str, Any] = {"name": metric.name, "kind": metric.kind}

    if metric.kind in ("counter", "gauge"):
        if metric.value is None:
            raise ValueError(f'metric.value is required for kind "{metric.kind}"')
        data["value"] = _require_finite(metric.value, "metric.value")
    else:
        if (
            not isinstance(metric.values, list)
            or len(metric.values) == 0
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in metric.values)
        ):
            raise ValueError(
                f'metric.values must be a non-empty array of finite numbers for kind "{metric.kind}"'
            )
        data["values"] = [
            _require_finite(v, "metric.values") for v in metric.values
        ]

    if metric.value is not None:
        data["value"] = _require_finite(metric.value, "metric.value")

    if metric.unit is not None:
        data["unit"] = metric.unit
    if metric.labels is not None:
        data["labels"] = dict(metric.labels)

    return _base_event("metric", "telemetry.metric", {"metric": data}, common)


def build_span_event(span: SpanData, common: TelemetryCommon) -> EventData:
    _require_hex(span.trace_id, "span.traceId")
    _require_hex(span.span_id, "span.spanId")
    if span.parent_span_id is not None:
        _require_hex(span.parent_span_id, "span.parentSpanId")
    _require_non_empty(span.name, "span.name")
    if span.kind not in SPAN_KINDS:
        raise ValueError(f"span.kind must be one of: {sorted(SPAN_KINDS)}")
    _require_iso(span.start_time, "span.startTime")
    if span.end_time is not None:
        _require_iso(span.end_time, "span.endTime")
    if span.duration_ms is not None:
        duration = _require_finite(span.duration_ms, "span.durationMs")
        if duration < 0:
            raise ValueError("span.durationMs must be >= 0")
    status = span.status or "unset"
    if status not in SPAN_STATUSES:
        raise ValueError(f"span.status must be one of: {sorted(SPAN_STATUSES)}")

    data: dict[str, Any] = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "name": span.name,
        "kind": span.kind,
        "startTime": span.start_time,
        "status": status,
    }
    if span.parent_span_id is not None:
        data["parentSpanId"] = span.parent_span_id
    if span.end_time is not None:
        data["endTime"] = span.end_time
    if span.duration_ms is not None:
        data["durationMs"] = float(span.duration_ms)
    if span.attributes is not None:
        data["attributes"] = dict(span.attributes)
    if span.events is not None:
        events: list[dict[str, Any]] = []
        for i, ev in enumerate(span.events):
            _require_non_empty(ev.name, f"span.events[{i}].name")
            _require_iso(ev.time, f"span.events[{i}].time")
            entry: dict[str, Any] = {"name": ev.name, "time": ev.time}
            if ev.attributes is not None:
                entry["attributes"] = dict(ev.attributes)
            events.append(entry)
        data["events"] = events

    return _base_event("span", "telemetry.span", {"span": data}, common)


def build_performance_event(
    performance: PerformanceData, common: TelemetryCommon
) -> EventData:
    _require_non_empty(performance.operation, "performance.operation")
    duration = _require_finite(performance.duration_ms, "performance.durationMs")
    if duration < 0:
        raise ValueError("performance.durationMs must be >= 0")
    if (
        performance.status is not None
        and performance.status not in ("ok", "error")
    ):
        raise ValueError('performance.status must be "ok" or "error"')

    data: dict[str, Any] = {
        "operation": performance.operation,
        "durationMs": duration,
    }
    if performance.status is not None:
        data["status"] = performance.status
    if performance.throughput_per_sec is not None:
        throughput = _require_finite(
            performance.throughput_per_sec, "performance.throughputPerSec"
        )
        if throughput < 0:
            raise ValueError("performance.throughputPerSec must be >= 0")
        data["throughputPerSec"] = throughput
    if performance.error_rate is not None:
        rate = _require_finite(performance.error_rate, "performance.errorRate")
        if rate < 0 or rate > 1:
            raise ValueError("performance.errorRate must be between 0 and 1")
        data["errorRate"] = rate
    if performance.resource is not None:
        data["resource"] = performance.resource
    if performance.dimensions is not None:
        data["dimensions"] = dict(performance.dimensions)

    return _base_event(
        "performance", "telemetry.performance", {"performance": data}, common
    )


def build_log_event(log: LogData, common: TelemetryCommon) -> EventData:
    if log.level not in LOG_LEVELS:
        raise ValueError(f"log.level must be one of: {sorted(LOG_LEVELS)}")
    _require_non_empty(log.message, "log.message")

    data: dict[str, Any] = {"level": log.level, "message": log.message}
    if log.attributes is not None:
        data["attributes"] = dict(log.attributes)

    return _base_event(
        "log",
        "telemetry.log",
        {"log": data},
        common,
        severity=LOG_LEVEL_SEVERITY[log.level],
    )
