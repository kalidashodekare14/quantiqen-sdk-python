# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .batcher import EventBatcher
from .retry import (
    RetryConfig,
    calculate_delay,
    is_retryable,
    parse_retry_after,
    sleep_ms,
)
from .types import ClientOptions, EventData
from .telemetry import (
    LogData,
    MetricData,
    PerformanceData,
    SpanData,
    TelemetryCommon,
    build_log_event,
    build_metric_event,
    build_performance_event,
    build_span_event,
)

SDK_VERSION = "0.1.0"
SDK_LANGUAGE = "python"
DEFAULT_BATCH_SIZE = 100
DEFAULT_FLUSH_INTERVAL_MS = 5000
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY_MS = 1000
MAX_BULK_SIZE = 500


class QuantiqenClient:
    def __init__(self, options: ClientOptions) -> None:
        if not options.api_key:
            raise ValueError("API key is required")
        if not options.api_key.startswith("qtn_"):
            raise ValueError(
                'Invalid API key format. Expected key starting with "qtn_"'
            )

        self._api_key = options.api_key
        self._base_url = options.base_url.rstrip("/")
        self._max_retries = options.max_retries
        self._base_delay_ms = DEFAULT_BASE_DELAY_MS
        self._logger = options.logger or (lambda msg: print(msg, flush=True))

        self._batcher = EventBatcher(
            batch_size=options.batch_size,
            flush_interval_ms=options.flush_interval_ms,
            on_flush=self._send_bulk,
            logger=self._logger,
        )
        self._batcher.start()

    def send_event(self, event: EventData) -> None:
        try:
            enriched = self._enrich_event(event)
            self._batcher.add(enriched)
        except Exception as err:
            self._logger(
                f"[quantiqen-sdk] Failed to enqueue event: {err}"
            )

    def send_events(self, events: list[EventData]) -> None:
        try:
            for event in events:
                enriched = self._enrich_event(event)
                self._batcher.add(enriched)
        except Exception as err:
            self._logger(
                f"[quantiqen-sdk] Failed to enqueue events: {err}"
            )

    def flush(self) -> None:
        self._batcher.flush()

    def send_metric(self, metric: MetricData, common: TelemetryCommon) -> None:
        """Enqueue a typed metric record (telemetry ingestion). Fire-and-forget."""
        self._enqueue_telemetry(lambda: build_metric_event(metric, common), "metric")

    def send_span(self, span: SpanData, common: TelemetryCommon) -> None:
        """Enqueue a typed span/trace record. Fire-and-forget."""
        self._enqueue_telemetry(lambda: build_span_event(span, common), "span")

    def send_performance(
        self, performance: PerformanceData, common: TelemetryCommon
    ) -> None:
        """Enqueue a typed performance record. Fire-and-forget."""
        self._enqueue_telemetry(
            lambda: build_performance_event(performance, common), "performance"
        )

    def send_log(self, log: LogData, common: TelemetryCommon) -> None:
        """Enqueue a typed log/telemetry record. Fire-and-forget."""
        self._enqueue_telemetry(lambda: build_log_event(log, common), "log")

    def _enqueue_telemetry(self, build, kind: str) -> None:
        try:
            self._batcher.add(self._enrich_event(build()))
        except Exception as err:
            self._logger(
                f"[quantiqen-sdk] Failed to enqueue {kind} telemetry: {err}"
            )

    def shutdown(self) -> None:
        self._batcher.shutdown()

    def update_rate_limit(self, headers: dict[str, str]) -> None:
        self._batcher.update_rate_limit(headers)

    def _enrich_event(self, event: EventData) -> EventData:
        meta = dict(event.metadata) if event.metadata else {}
        meta["sdkLanguage"] = SDK_LANGUAGE
        meta["sdkVersion"] = SDK_VERSION
        meta["userAgent"] = f"quantiqen-sdk-{SDK_LANGUAGE}/{SDK_VERSION}"
        return EventData(
            event_type=event.event_type,
            event_category=event.event_category,
            severity=event.severity,
            source=event.source,
            occurred_at=event.occurred_at,
            payload=event.payload,
            event_version=event.event_version,
            asset_id=event.asset_id,
            idempotency_key=event.idempotency_key,
            metadata=meta,
        )

    def _send_bulk(self, events: list[EventData]) -> None:
        for i in range(0, len(events), MAX_BULK_SIZE):
            chunk = events[i : i + MAX_BULK_SIZE]
            body = {"events": [e.to_dict() for e in chunk]}
            self._post_with_retry("/api/v1/events/bulk", body)

    def _post_with_retry(self, path: str, body: dict[str, Any]) -> Any:
        config = RetryConfig(
            max_retries=self._max_retries,
            base_delay_ms=self._base_delay_ms,
        )
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": self._api_key,
        }

        last_error: Exception | None = None
        for attempt in range(config.max_retries + 1):
            try:
                req = urllib.request.Request(
                    url, data=data, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_headers = {
                        k.lower(): v for k, v in resp.headers.items()
                    }
                    self._batcher.update_rate_limit(resp_headers)
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                last_error = err
                if not is_retryable(err.code):
                    raise
                retry_after = parse_retry_after(
                    err.headers.get("Retry-After")
                    if err.headers
                    else None
                )
                delay = calculate_delay(attempt, config, retry_after)
                sleep_ms(delay)
            except urllib.error.URLError as err:
                last_error = err
                if attempt == config.max_retries:
                    break
                delay = calculate_delay(attempt, config)
                sleep_ms(delay)
            except Exception as err:
                last_error = err
                if attempt == config.max_retries:
                    break
                delay = calculate_delay(attempt, config)
                sleep_ms(delay)

        raise last_error  # type: ignore[misc]
