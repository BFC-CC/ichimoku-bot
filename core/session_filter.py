"""
core/session_filter.py
─────────────────────────────────────────────────────────────────────────────
UTC hour window filter + Friday close check.
"""

from __future__ import annotations

from datetime import datetime

from core.config_loader import SessionFilterConfig


class SessionFilter:
    """Check if current time is within the allowed trading session."""

    def __init__(self, config: SessionFilterConfig) -> None:
        self.cfg = config

    def is_tradeable(self, now_utc: datetime) -> tuple[bool, str]:
        """Returns (True, 'ok') or (False, reason)."""
        if not self.cfg.enabled:
            return True, "ok"

        hour = now_utc.hour
        if hour < self.cfg.start_hour_utc or hour >= self.cfg.end_hour_utc:
            return False, f"Outside session ({hour} UTC, allowed {self.cfg.start_hour_utc}-{self.cfg.end_hour_utc})"

        if now_utc.weekday() == 4 and hour >= 17 and not self.cfg.trade_friday_close:
            return False, "Friday close — no new trades"

        return True, "ok"
