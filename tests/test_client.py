import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from quantiqen_sdk.client import QuantiqenClient
from quantiqen_sdk.types import ClientOptions, EventData

VALID_KEY = "qtn_live_abc123def456ghi789jkl012mno345pqr"


def make_event() -> EventData:
    return EventData(
        event_type="test.event",
        event_category="test",
        severity="INFO",
        source="test",
        occurred_at="2026-01-01T00:00:00Z",
        payload={"key": "value"},
    )


class TestConstruction:
    def test_throws_on_missing_key(self):
        with pytest.raises(ValueError, match="API key is required"):
            QuantiqenClient(ClientOptions(api_key=""))

    def test_throws_on_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid API key format"):
            QuantiqenClient(ClientOptions(api_key="invalid_key"))

    def test_throws_on_unknown_qtn_prefix(self):
        with pytest.raises(ValueError, match="Invalid API key format"):
            QuantiqenClient(ClientOptions(api_key="qtn_bogus_abc123"))

    def test_accepts_valid_key(self):
        client = QuantiqenClient(ClientOptions(api_key=VALID_KEY))
        assert client is not None
        client.shutdown()

    def test_accepts_test_and_dev_keys(self):
        for key in (
            "qtn_test_abc123def456ghi789jkl012mno345pqr",
            "qtn_dev_abc123def456ghi789jkl012mno345pqr",
        ):
            client = QuantiqenClient(ClientOptions(api_key=key))
            assert client is not None
            client.shutdown()


class TestAuth:
    def test_sends_correct_header(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({}).encode()
        mock_resp.headers = {"X-RateLimit-Remaining": "100"}

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client = QuantiqenClient(
                ClientOptions(
                    api_key=VALID_KEY, batch_size=100, flush_interval_ms=60000
                )
            )
            client.send_event(make_event())
            client.flush()
            client.shutdown()

            call_args = mock_open.call_args
            req = call_args[0][0]
            assert req.get_header("X-api-key") == VALID_KEY

    def test_uses_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({}).encode()
        mock_resp.headers = {"X-RateLimit-Remaining": "100"}

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client = QuantiqenClient(
                ClientOptions(
                    api_key=VALID_KEY,
                    base_url="https://custom.api.com",
                    batch_size=100,
                    flush_interval_ms=60000,
                )
            )
            client.send_event(make_event())
            client.flush()
            client.shutdown()

            req = mock_open.call_args[0][0]
            assert req.full_url == "https://custom.api.com/api/v1/events/bulk"


class TestResponseHandling:
    def test_sends_bulk_payload(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({}).encode()
        mock_resp.headers = {"X-RateLimit-Remaining": "100"}

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client = QuantiqenClient(
                ClientOptions(
                    api_key=VALID_KEY, batch_size=100, flush_interval_ms=60000
                )
            )
            client.send_event(make_event())
            client.flush()
            client.shutdown()

            req = mock_open.call_args[0][0]
            body = json.loads(req.data.decode())
            assert "events" in body
            assert isinstance(body["events"], list)

    def test_merges_metadata(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({}).encode()
        mock_resp.headers = {"X-RateLimit-Remaining": "100"}

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client = QuantiqenClient(
                ClientOptions(
                    api_key=VALID_KEY, batch_size=100, flush_interval_ms=60000
                )
            )
            event = make_event()
            event.metadata = {"customField": "customValue"}
            client.send_event(event)
            client.flush()
            client.shutdown()

            req = mock_open.call_args[0][0]
            body = json.loads(req.data.decode())
            meta = body["events"][0]["metadata"]
            assert meta["customField"] == "customValue"
            assert meta["sdkLanguage"] == "python"
            assert meta["sdkVersion"] == "0.1.1"
            assert "quantiqen-sdk-python" in meta["userAgent"]


class TestErrorIsolation:
    def test_send_event_resolves_on_connrefused(self):
        client = QuantiqenClient(
            ClientOptions(
                api_key=VALID_KEY,
                batch_size=1,
                flush_interval_ms=60000,
                max_retries=1,
                logger=lambda msg: None,
            )
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError(
                socket.error(111, "Connection refused")
            ),
        ):
            client.send_event(make_event())
            client.flush()
            client.shutdown()

    def test_send_events_resolves_on_connrefused(self):
        client = QuantiqenClient(
            ClientOptions(
                api_key=VALID_KEY,
                batch_size=100,
                flush_interval_ms=60000,
                max_retries=1,
                logger=lambda msg: None,
            )
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError(
                socket.error(111, "Connection refused")
            ),
        ):
            client.send_events([make_event(), make_event()])
            client.shutdown()

    def test_no_error_thrown_to_caller(self):
        client = QuantiqenClient(
            ClientOptions(
                api_key=VALID_KEY,
                batch_size=1,
                flush_interval_ms=60000,
                max_retries=1,
                logger=lambda msg: None,
            )
        )

        caught = False
        try:
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("network down"),
            ):
                client.send_event(make_event())
                client.flush()
        except Exception:
            caught = True

        client.shutdown()
        assert caught is False

    def test_completes_in_bounded_time_with_retries(self):
        client = QuantiqenClient(
            ClientOptions(
                api_key=VALID_KEY,
                batch_size=1,
                flush_interval_ms=60000,
                max_retries=3,
                logger=lambda msg: None,
            )
        )

        import time

        start = time.time()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("ECONNREFUSED"),
        ):
            client.send_event(make_event())
            client.flush()
        elapsed = time.time() - start

        client.shutdown()
        assert elapsed < 30

