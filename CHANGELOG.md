# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-10-13

### Added

- Troubleshooting guidance for `401 INVALID_API_KEY` (well-formed but
  unknown/revoked key — check the key exists and is active in the
  organization settings).

### Changed

- API-key validation now enforces the full platform contract
  `qtn_{live|test|dev}_…` client-side, so a malformed key fails instantly
  with a clear error instead of a server round-trip.
- README: removed the stale "not yet published to PyPI" notice;
  `quantiqen-sdk` installs from the public registry.

## [0.1.0] - 2026-10-12

### Added

- Initial release: `QuantiqenClient` with in-memory batching (default 100 events,
  500-event chunk cap), automatic retry with exponential backoff and jitter on
  network errors / 5xx / 429, `Retry-After` handling, and
  `X-RateLimit-Remaining`-aware throttling.
- `POST /api/v1/events/bulk` ingestion against the QUANTIQEN platform
  (`https://quantiqen-backend.onrender.com` by default).
- Automatic event metadata enrichment (`sdkLanguage`, `sdkVersion`, `userAgent`).
- Fire-and-forget semantics: `send_event()`/`send_events()` never raise; failures
  are logged via the configurable `logger`.
- PEP 561 `py.typed` marker for typed consumers.
- Telemetry ingestion helpers: `send_metric()` / `send_span()` /
  `send_performance()` / `send_log()` plus strict builders
  (`build_metric_event`, `build_span_event`, `build_performance_event`,
  `build_log_event`) and typed dataclasses. Records ride the existing event
  envelope (`event_category="telemetry"`,
  `telemetry.{metric|span|performance|log}`) with a discriminated
  `payload.telemetryType`; auto-UUID `idempotency_key` per record; `send_log`
  maps log level to severity.

### Fixed

- `flush()` now drains the entire event queue instead of a single batch.
- A `Retry-After` pause is no longer re-applied after it has elapsed.

[0.1.1]: https://github.com/kalidashodekare14/quantiqen-sdk-python/releases/tag/v0.1.1
[0.1.0]: https://github.com/kalidashodekare14/quantiqen-sdk-python/releases/tag/v0.1.0
