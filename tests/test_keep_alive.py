"""Tests for utils/keep_alive.py and dashboard health endpoint (Action 2)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest

from utils.keep_alive import KeepAlive


class TestKeepAlivePing:
    def test_ping_success(self):
        ka = KeepAlive("https://example.com", interval_sec=60)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = MagicMock()

        with patch("utils.keep_alive.requests.get", return_value=mock_resp) as mock_get:
            ok, detail = ka._ping()
            assert ok is True
            assert "ok" in detail
            mock_get.assert_called_once_with("https://example.com/api/health", timeout=10)

    def test_ping_failure_http_error(self):
        ka = KeepAlive("https://example.com", interval_sec=60)

        with patch("utils.keep_alive.requests.get", side_effect=Exception("Connection error")):
            ok, detail = ka._ping()
            assert ok is False
            assert "Connection error" in detail

    def test_ping_unexpected_response(self):
        ka = KeepAlive("https://example.com", interval_sec=60)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "error"}
        mock_resp.raise_for_status = MagicMock()

        with patch("utils.keep_alive.requests.get", return_value=mock_resp):
            ok, detail = ka._ping()
            assert ok is False
            assert "unexpected" in detail

    def test_disabled_when_empty_url(self):
        ka = KeepAlive("", interval_sec=60)
        ka.start()
        # Should not start thread when URL is empty
        assert ka._thread is None

    def test_url_trailing_slash_stripped(self):
        ka = KeepAlive("https://example.com/", interval_sec=60)
        assert ka.url == "https://example.com"

    def test_start_stop(self):
        ka = KeepAlive("https://example.com", interval_sec=3600)
        with patch("utils.keep_alive.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"status": "ok"}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            ka.start()
            assert ka._thread is not None
            assert ka._thread.is_alive()

            ka.stop()
            # Thread should stop after signal
            assert ka._stop_event.is_set()


class TestHealthEndpoint:
    def test_health_endpoint_exists(self):
        """Verify dashboard_server defines /api/health route."""
        try:
            import httpx  # noqa: F401 — required by TestClient
            from fastapi.testclient import TestClient
        except (ImportError, ModuleNotFoundError):
            pytest.skip("httpx or FastAPI not installed")

        from utils.dashboard_server import DashboardServer
        from utils.state import BotState
        from core.config_loader import DashboardConfig

        state = BotState()
        state.update_account(1000.0, 1050.0)

        server = DashboardServer(DashboardConfig(enabled=True), state)
        client = TestClient(server.app)

        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["balance"] == 1000.0
        assert data["is_halted"] is False
