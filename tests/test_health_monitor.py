"""Tests for core/health_monitor.py (Action 4)."""

from __future__ import annotations

import time
import pytest

from core.health_monitor import HealthMonitor, HealthEvent
from core.config_loader import HealthMonitorConfig


def _make_monitor(
    max_tick_gap_sec=5,
    max_consecutive_errors=3,
    alert_cooldown_sec=0,
    heartbeat_interval_sec=0,
) -> tuple[HealthMonitor, list[str]]:
    """Create a HealthMonitor with a list-accumulator notifier."""
    alerts: list[str] = []
    cfg = HealthMonitorConfig(
        enabled=True,
        max_tick_gap_sec=max_tick_gap_sec,
        max_consecutive_errors=max_consecutive_errors,
        alert_cooldown_sec=alert_cooldown_sec,
        heartbeat_interval_sec=heartbeat_interval_sec,
    )
    mon = HealthMonitor(cfg, notifier_fn=alerts.append)
    return mon, alerts


class TestRecordTick:
    def test_tick_resets_errors(self):
        mon, _ = _make_monitor()
        mon.record_error("test", "err1")
        mon.record_error("test", "err2")
        assert mon._consecutive_errors == 2
        mon.record_tick("EURUSD")
        assert mon._consecutive_errors == 0

    def test_tick_updates_time(self):
        mon, _ = _make_monitor()
        mon.record_tick("EURUSD")
        assert "EURUSD" in mon._last_tick_time
        assert mon._last_tick_time["EURUSD"] > 0


class TestTickGap:
    def test_tick_gap_alert(self):
        mon, alerts = _make_monitor(max_tick_gap_sec=1, alert_cooldown_sec=0)
        mon._last_tick_time["EURUSD"] = time.time() - 10  # 10s ago
        events = mon.check_health()
        assert any(e.event_type == "tick_gap" for e in events)
        assert len(alerts) > 0
        assert "EURUSD" in alerts[0]

    def test_no_alert_when_fresh(self):
        mon, alerts = _make_monitor(max_tick_gap_sec=60)
        mon.record_tick("EURUSD")
        events = mon.check_health()
        assert not any(e.event_type == "tick_gap" for e in events)
        assert len(alerts) == 0


class TestConsecutiveErrors:
    def test_error_threshold_triggers_alert(self):
        mon, alerts = _make_monitor(max_consecutive_errors=3, alert_cooldown_sec=0)
        mon.record_error("test", "err1")
        mon.record_error("test", "err2")
        mon.record_error("test", "err3")
        events = mon.check_health()
        assert any(e.event_type == "consecutive_errors" for e in events)
        assert len(alerts) > 0

    def test_below_threshold_no_alert(self):
        mon, alerts = _make_monitor(max_consecutive_errors=3, alert_cooldown_sec=0)
        mon.record_error("test", "err1")
        mon.record_error("test", "err2")
        events = mon.check_health()
        assert not any(e.event_type == "consecutive_errors" for e in events)

    def test_critical_severity_at_double_threshold(self):
        mon, _ = _make_monitor(max_consecutive_errors=2, alert_cooldown_sec=0)
        for i in range(4):
            mon.record_error("test", f"err{i}")
        events = mon.check_health()
        err_events = [e for e in events if e.event_type == "consecutive_errors"]
        assert err_events[0].severity == "critical"


class TestConnectionStatus:
    def test_connection_lost_alert(self):
        mon, alerts = _make_monitor(alert_cooldown_sec=0)
        mon.record_connection_status(False)
        events = mon.check_health()
        assert any(e.event_type == "connection_lost" for e in events)

    def test_connected_no_alert(self):
        mon, alerts = _make_monitor(alert_cooldown_sec=0)
        mon.record_connection_status(True)
        events = mon.check_health()
        assert not any(e.event_type == "connection_lost" for e in events)


class TestCooldown:
    def test_cooldown_suppresses_alerts(self):
        mon, alerts = _make_monitor(
            max_consecutive_errors=1,
            alert_cooldown_sec=9999,
        )
        mon.record_error("test", "err1")
        mon.check_health()  # First alert fires
        first_count = len(alerts)

        mon.record_error("test", "err2")
        mon.check_health()  # Should be suppressed by cooldown
        assert len(alerts) == first_count


class TestHeartbeat:
    def test_heartbeat_fires(self):
        mon, alerts = _make_monitor(heartbeat_interval_sec=1)
        mon._last_heartbeat_time = time.time() - 10  # Force interval elapsed
        mon.check_health()
        assert any("Heartbeat" in a for a in alerts)


class TestDisabled:
    def test_disabled_returns_empty(self):
        cfg = HealthMonitorConfig(enabled=False)
        alerts: list[str] = []
        mon = HealthMonitor(cfg, notifier_fn=alerts.append)
        mon.record_error("test", "err1")
        events = mon.check_health()
        assert events == []
        assert len(alerts) == 0


class TestGetMetrics:
    def test_metrics_structure(self):
        mon, _ = _make_monitor()
        mon.record_tick("EURUSD")
        mon.record_tick("GBPUSD")
        mon.record_execution_failure("EURUSD", "timeout")
        metrics = mon.get_metrics()
        assert metrics["connected"] is True
        assert metrics["consecutive_errors"] == 0
        assert metrics["execution_failures"] == 1
        assert "EURUSD" in metrics["tick_ages_sec"]
        assert "GBPUSD" in metrics["tick_ages_sec"]
