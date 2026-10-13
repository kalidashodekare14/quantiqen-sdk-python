# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


@dataclass
class EventData:
    event_type: str
    event_category: str
    severity: Severity
    source: str
    occurred_at: str
    payload: dict[str, Any]
    event_version: str | None = None
    asset_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "eventType": self.event_type,
            "eventCategory": self.event_category,
            "severity": self.severity,
            "source": self.source,
            "occurredAt": self.occurred_at,
            "payload": self.payload,
        }
        if self.event_version is not None:
            d["eventVersion"] = self.event_version
        if self.asset_id is not None:
            d["assetId"] = self.asset_id
        if self.idempotency_key is not None:
            d["idempotencyKey"] = self.idempotency_key
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d


@dataclass
class SingleResult:
    event_id: str
    duplicate: bool


@dataclass
class BulkItemResult:
    index: int
    status: str
    event_id: str | None = None
    error: str | None = None


@dataclass
class BulkResult:
    results: list[BulkItemResult]
    accepted_count: int
    duplicate_count: int
    rejected_count: int


@dataclass
class ClientOptions:
    api_key: str
    base_url: str = "https://api.quantiqen.com"
    batch_size: int = 100
    flush_interval_ms: int = 5000
    max_retries: int = 3
    logger: Any = None
