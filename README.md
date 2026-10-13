# QUANTIQEN SDK for Python

Fire-and-forget client for sending security and telemetry events — metrics, traces/spans, performance data, and logs — to the QUANTIQEN platform.

Client-side batching, automatic retry with exponential backoff, and proactive rate-limit-aware throttling. **The SDK never raises into your application.**

**Requires Python ≥ 3.9** (standard library only — no runtime dependencies).

## Installation

```bash
pip install quantiqen-sdk

# Or from git:
pip install "git+https://github.com/kalidashodekare14/quantiqen-sdk-python.git@main"
```

## Quickstart

```python
import atexit
from datetime import datetime, timezone
from quantiqen_sdk import QuantiqenClient, EventData, ClientOptions

client = QuantiqenClient(ClientOptions(
    api_key="qtn_live_your_api_key_here",
    base_url="https://quantiqen-backend.onrender.com",  # optional, this is the default
))

# Send a single event (fire-and-forget, never blocks)
client.send_event(EventData(
    event_type="auth.login",
    event_category="authentication",
    severity="MEDIUM",
    source="my-app",
    occurred_at=datetime.now(timezone.utc).isoformat(),
    payload={
        "userId": "user-123",
        "ip": "192.168.1.1",
        "success": True,
    },
))

# Send multiple events
client.send_events([
    EventData(
        event_type="api.request",
        event_category="api",
        severity="LOW",
        source="my-api",
        occurred_at=datetime.now(timezone.utc).isoformat(),
        payload={"method": "GET", "path": "/users", "status": 200},
    ),
    EventData(
        event_type="db.slow_query",
        event_category="database",
        severity="HIGH",
        source="my-db",
        occurred_at=datetime.now(timezone.utc).isoformat(),
        payload={"query": "SELECT * FROM users", "duration_ms": 5000},
    ),
])

# Manually flush pending events (optional)
client.flush()

# Graceful shutdown — flush pending events before process exits
atexit.register(client.shutdown)
```

## Configuration

### API key

Create a key in your QUANTIQEN organization settings (`qtn_live_…`, `qtn_test_…`, or `qtn_dev_…`) and load it from the environment — never hard-code it:

```python
import os
from quantiqen_sdk import QuantiqenClient, ClientOptions

client = QuantiqenClient(ClientOptions(api_key=os.environ["QUANTIQEN_API_KEY"]))
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `api_key` | (required) | Your QUANTIQEN API key (`qtn_live_*`, `qtn_test_*`, or `qtn_dev_*`) |
| `base_url` | `https://quantiqen-backend.onrender.com` | QUANTIQEN ingestion endpoint — set only for a self-hosted gateway |
| `batch_size` | `100` | Events accumulated before auto-flush |
| `flush_interval_ms` | `5000` | Max time (ms) between flushes |
| `max_retries` | `3` | Max retry attempts on transient failures |
| `logger` | `print` | Log function for SDK errors — **set this in production** |

## How It Works

1. **Batching**: Events are accumulated in memory. When the batch reaches `batch_size` or `flush_interval_ms` elapses (whichever comes first), the batch is flushed to the QUANTIQEN ingestion endpoint via `POST /api/v1/events/bulk`.

2. **Retry with backoff**: Transient failures (network errors, 5xx, 429) are retried up to `max_retries` times with exponential backoff (1s, 2s, 4s) plus jitter. The SDK respects `Retry-After` headers from 429 responses.

3. **Rate-limit awareness**: The SDK tracks `X-RateLimit-Remaining` from responses. When remaining is low (< 5), flushes are proactively delayed to avoid hitting the rate limit.

4. **Error isolation**: `send_event()` and `send_events()` never raise exceptions. Failures are logged internally via the `logger` callback. This guarantees the SDK never crashes your application.

5. **SDK metadata**: Events are automatically enriched with `sdkLanguage`, `sdkVersion`, and `userAgent` metadata fields (merged with any custom metadata you provide).

## Graceful Shutdown

Call `shutdown()` during process shutdown to flush any pending events:

```python
import atexit

atexit.register(client.shutdown)
```

Or for explicit control:

```python
import signal
import sys

def handle_shutdown(signum, frame):
    client.shutdown()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)
```

This is recommended but not required. If the process exits without calling `shutdown()`, any events still in the in-memory batch queue will be lost.

## Known Limitations

- **In-memory queue only**: Events are held in memory until flushed. If the host process crashes or is killed before flushing, those events are lost. This is standard for a v0.1.0 SDK. For durability-critical use cases, persist events to disk or a message queue before passing them to the SDK.

- **No persistent local queue**: There is no disk-backed or WAL-based queue. "Never lose events" applies only to transient network/5xx/429 failures during the process's lifetime, not process-level failures.

- **Single-process only**: The batcher state is in-process memory. Do not share a `QuantiqenClient` instance across threads without synchronization (the SDK uses internal locking but is designed for single-threaded use).

- **500 event cap per request**: The backend rejects batches larger than 500. The SDK enforces this automatically by chunking.

## Event Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_type` | string (1-500) | Yes | Event type (e.g. `auth.login`) |
| `event_category` | string (1-100) | Yes | Category (e.g. `authentication`) |
| `severity` | enum | Yes | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO` |
| `source` | string (1-200) | Yes | Source system (e.g. `aws-cloudtrail`) |
| `occurred_at` | ISO 8601 | Yes | When the event occurred |
| `payload` | dict | Yes | Event data |
| `event_version` | string | No | Schema version (default `1.0`) |
| `asset_id` | UUID | No | Associated asset |
| `idempotency_key` | string | No | Dedup key (derived server-side if absent) |
| `metadata` | dict | No | Additional metadata (allow-listed fields) |

## Telemetry Ingestion

Typed helpers for metrics, traces/spans, performance and logs. They build the
same wire events as `send_event` (the platform's event DTO is the contract —
no platform changes), queue them through the same batcher, and are
fire-and-forget like everything else:

- `event_category` is always `"telemetry"`; `event_type` is
  `telemetry.{metric|span|performance|log}`.
- `payload` carries `telemetryType` plus exactly one of `metric` / `span` /
  `performance` / `log`.
- A random UUID `idempotency_key` is generated per record (override via
  `common.idempotency_key`) so same-name/same-second metrics never falsely
  dedup.
- Severity defaults to `INFO`; `send_log` maps level → severity
  (`warn`→`MEDIUM`, `error`→`HIGH`, `fatal`→`CRITICAL`) unless you set one.
- Builders validate strictly and raise `ValueError`; the client's `send_*`
  methods catch and log instead (a malformed record never crashes your app).
- Trace IDs, labels and attributes live in `payload`, not `metadata`
  (metadata is an allow-listed set server-side).

```python
from quantiqen_sdk import (
    QuantiqenClient, ClientOptions, TelemetryCommon,
    MetricData, SpanData, PerformanceData, LogData,
)

common = TelemetryCommon(source="api")

# Metric (counter | gauge | histogram | distribution)
client.send_metric(
    MetricData(name="http.requests", kind="counter", value=1,
               labels={"route": "/users"}),
    common,
)

# Span / trace (W3C-style hex ids)
client.send_span(
    SpanData(
        trace_id="a1b2c3d4e5f60718293a4b5c6d7e8f90",
        span_id="0123456789abcdef",
        name="GET /users",
        kind="server",
        start_time="2026-01-01T00:00:00+00:00",
        duration_ms=120,
        status="ok",
    ),
    common,
)

# Performance
client.send_performance(
    PerformanceData(operation="POST /checkout", duration_ms=842.5,
                    status="ok", error_rate=0.01),
    TelemetryCommon(source="checkout"),
)

# Log (severity auto-mapped from level)
client.send_log(
    LogData(level="error", message="checkout failed",
            attributes={"orderId": "o-1"}),
    TelemetryCommon(source="checkout"),
)

client.flush()
```

Payload shapes (snake_case dataclass fields serialize to camelCase JSON):

| Kind | `payload.<kind>` fields |
|------|-------------------------|
| `metric` | `name`, `kind`, `value?` (counter/gauge), `values?` (histogram/distribution), `unit?`, `labels?` |
| `span` | `traceId`, `spanId`, `parentSpanId?`, `name`, `kind`, `startTime`, `endTime?`, `durationMs?`, `status?` (`ok`/`error`/`unset`), `attributes?`, `events?` |
| `performance` | `operation`, `durationMs`, `status?`, `throughputPerSec?`, `errorRate?` (0–1), `resource?`, `dimensions?` |
| `log` | `level` (`debug`/`info`/`warn`/`error`/`fatal`), `message`, `attributes?` |

For plain (non-typed) telemetry, use `send_event` directly — the convention
is optional, not enforced by the platform.

## Best Practices

- **One client per process** — create it at startup; it owns an in-memory queue and flush timer.
- **Always register shutdown hooks** (`atexit`, or `SIGTERM`/`SIGINT`) so buffered events flush before exit.
- **Use `qtn_test_` keys in CI** and non-production environments.
- **Set a meaningful `source` per service** (`checkout`, `api`, `aws-cloudtrail`) — the primary attribution field.
- **Slice with `labels` / `dimensions` / span `attributes`** (route, region, status…) instead of high-cardinality metric names.
- **Keep secrets out of payloads** — the platform redacts secret-looking keys (`*_token`, `*_secret`, …), but don't rely on redaction alone.
- **Let the SDK own idempotency for telemetry** — it auto-generates a UUID per record; pass your own `idempotency_key` only for real natural keys.
- **Set a custom `logger` in production** — failures are silent otherwise (fire-and-forget by design).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `400 INVALID_API_KEY` | Missing header, or key doesn't match `qtn_{live\|test\|dev}_…` | Check the `api_key` option and key value |
| `401 INVALID_API_KEY` | Key is well-formed but not recognized — unknown, revoked, or not provisioned in this environment | Confirm the key exists and is active in your QUANTIQEN organization settings; regenerate if needed and redeploy the new value |
| `422` with field errors | Event DTO validation failed (field names/types) | Compare the error body's `field_errors` with the [Event Schema](#event-schema) and telemetry tables |
| `429 RATE_LIMITED` | Per-key rate limit hit | SDK already backs off (`Retry-After` respected). Sustained? Raise limits in the platform |
| `504` / `503` from server | Endpoint slow or down | SDK retries transient failures automatically; check `https://quantiqen-backend.onrender.com/api/v1/health` |
| Events not arriving | Process exited before flush | Register shutdown hooks (see [Graceful Shutdown](#graceful-shutdown)); call `flush()` before exit in scripts |
| No output when sends "fail" | Fire-and-forget by design | Provide a custom `logger` callable — defaults to `print` |

**Verify your install** — a 10-second smoke test (should produce *no* SDK log output):

```python
import os
from quantiqen_sdk import QuantiqenClient, ClientOptions, MetricData, TelemetryCommon

c = QuantiqenClient(ClientOptions(api_key=os.environ["QUANTIQEN_API_KEY"], batch_size=1))
c.send_metric(MetricData(name="smoke.test", kind="gauge", value=1),
              TelemetryCommon(source="smoke-test"))
c.flush()
c.shutdown()
```

Silent logger = the platform accepted the batch. Still nothing? Check network reachability to `https://quantiqen-backend.onrender.com` first.

## License

MIT
