"""
core/news_filter.py
---------------------------------------------------------------------
News filter: blocks trading during high-impact news event windows.
Delegates to NewsCalendar for event data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from loguru import logger

from core.config_loader import NewsFilterConfig
from core.news_calendar import NewsCalendar


class NewsFilter:
    """Pause trading around high-impact news events."""

    def __init__(self, config: NewsFilterConfig) -> None:
        self.cfg = config
        self._calendar: Optional[NewsCalendar] = None
        if config.enabled:
            self._calendar = NewsCalendar(config)

    def is_clear(self, symbol: str, now_utc: datetime) -> tuple[bool, str]:
        """Returns (True, 'ok') if no news conflict."""
        if not self.cfg.enabled:
            return True, "ok"

        if self._calendar is None:
            return True, "ok"

        is_blocked, reason = self._calendar.is_blackout(symbol, now_utc)
        if is_blocked:
            return False, f"News blackout: {reason}"

        return True, "ok"
