"""
core/health_monitor.py
---------------------------------------------------------------------
Proactive health monitoring with Discord alerts for missed ticks,
connection losses, and execution failures.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from loguru import logger

from core.config_loader import HealthMonitorConfig


@dataclass
class HealthEvent:
    severity: str  # "warning" or "critical"
    event_type: str
    detail: str
    timestamp: float = field(default_factory=time.time)


class HealthMonitor:
    """Track bot health metrics and fire alerts when thresholds are breached."""

    def __init__(
        self,
        config: HealthMonitorConfig,
        notifier_fn: Callable[[str], None],
    ) -> None:
        self.cfg = config
        self._notify = notifier_fn

        self._last_tick_time: Dict[str, float] = {}
        self._consecutive_errors: int = 0
        self._last_error_type: str = ""
        self._connected: bool = True
        self._last_alert_time: float = 0.0
        self._last_heartbeat_time: float = time.time()
        self._execution_failures: int = 0

    def record_tick(self, symbol: str) -> None:
        """Record a successful tick for a symbol."""
        self._last_tick_time[symbol] = time.time()
        self._consecutive_errors = 0

    def record_error(self, error_type: str, detail: str) -> None:
        """Record an error occurrence."""
        self._consecutive_errors += 1
        self._last_error_type = error_type
        logger.warning(f"Health: error #{self._consecutive_errors} ({error_type}): {detail}")

    def record_execution_failure(self, symbol: str, reason: str) -> None:
        """Record a failed trade execution."""
        self._execution_failures += 1
        logger.warning(f"Health: execution failure on {symbol}: {reason}")

    def record_connection_status(self, connected: bool) -> None:
        """Record MT5 connection status."""
        was_connected = self._connected
        self._connected = connected
        if was_connected and not connected:
            self.record_error("connection_lost", "MT5 connection lost")

    def check_health(self) -> List[HealthEvent]:
        """
        Check all health conditions and emit alerts if needed.
        Returns list of events generated (empty if healthy).
        """
        if not self.cfg.enabled:
            return []

        events: List[HealthEvent] = []
        now = time.time()

        # Check tick gaps
        for symbol, last_tick in self._last_tick_time.items():
            gap = now - last_tick
            if gap > self.cfg.max_tick_gap_sec:
                events.append(HealthEvent(
                    severity="warning",
                    event_type="tick_gap",
                    detail=f"{symbol}: no tick for {gap:.0f}s (max={self.cfg.max_tick_gap_sec}s)",
                ))

        # Check consecutive errors
        if self._consecutive_errors >= self.cfg.max_consecutive_errors:
            severity = "critical" if self._consecutive_errors >= self.cfg.max_consecutive_errors * 2 else "warning"
            events.append(HealthEvent(
                severity=severity,
                event_type="consecutive_errors",
                detail=f"{self._consecutive_errors} consecutive errors (last: {self._last_error_type})",
            ))

        # Check connection
        if not self._connected:
            events.append(HealthEvent(
                severity="critical",
                event_type="connection_lost",
                detail="MT5 connection is down",
            ))

        # Send alerts (respecting cooldown)
        if events and (now - self._last_alert_time) >= self.cfg.alert_cooldown_sec:
            self._send_alerts(events)
            self._last_alert_time = now

        # Heartbeat
        if (
            self.cfg.heartbeat_interval_sec > 0
            and (now - self._last_heartbeat_time) >= self.cfg.heartbeat_interval_sec
        ):
            self._send_heartbeat()
            self._last_heartbeat_time = now

        return events

    def get_metrics(self) -> dict:
        """Return metrics dict for the dashboard."""
        now = time.time()
        tick_ages = {
            sym: round(now - t, 1) for sym, t in self._last_tick_time.items()
        }
        return {
            "connected": self._connected,
            "consecutive_errors": self._consecutive_errors,
            "execution_failures": self._execution_failures,
            "tick_ages_sec": tick_ages,
        }

    def _send_alerts(self, events: List[HealthEvent]) -> None:
        """Format and send alert via notifier."""
        lines = ["**Health Alert**"]
        for ev in events:
            icon = "!!!" if ev.severity == "critical" else "!"
            lines.append(f"{icon} [{ev.event_type}] {ev.detail}")
        msg = "\n".join(lines)
        try:
            self._notify(msg)
        except Exception as e:
            logger.error(f"Failed to send health alert: {e}")

    def _send_heartbeat(self) -> None:
        """Send periodic heartbeat message."""
        metrics = self.get_metrics()
        msg = (
            f"**Heartbeat** | connected={metrics['connected']} | "
            f"errors={metrics['consecutive_errors']} | "
            f"exec_failures={metrics['execution_failures']}"
        )
        try:
            self._notify(msg)
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
