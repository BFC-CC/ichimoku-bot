"""
core/news_filter.py
─────────────────────────────────────────────────────────────────────────────
Stub news filter. Returns ok when disabled (default).
"""

from __future__ import annotations

from datetime import datetime

from core.config_loader import NewsFilterConfig


class NewsFilter:
    """Pause trading around high-impact news events (stub)."""

    def __init__(self, config: NewsFilterConfig) -> None:
        self.cfg = config

    def is_clear(self, symbol: str, now_utc: datetime) -> tuple[bool, str]:
        """Returns (True, 'ok') if no news conflict."""
        if not self.cfg.enabled:
            return True, "ok"

        # Stub: always clear when enabled (no data source implemented)
        return True, "News filter enabled but no data source configured"
