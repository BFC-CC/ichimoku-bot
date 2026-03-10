"""Tests for core/session_filter.py"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.session_filter import SessionFilter
from core.config_loader import SessionFilterConfig


class TestSessionFilter:
    def test_allows_within_session(self):
        sf = SessionFilter(SessionFilterConfig(enabled=True, start_hour_utc=7, end_hour_utc=20))
        ok, _ = sf.is_tradeable(datetime(2024, 6, 3, 12, 0, tzinfo=timezone.utc))  # Monday noon
        assert ok is True

    def test_blocks_before_session(self):
        sf = SessionFilter(SessionFilterConfig(enabled=True, start_hour_utc=7, end_hour_utc=20))
        ok, reason = sf.is_tradeable(datetime(2024, 6, 3, 5, 0, tzinfo=timezone.utc))
        assert ok is False
        assert "Outside session" in reason

    def test_blocks_after_session(self):
        sf = SessionFilter(SessionFilterConfig(enabled=True, start_hour_utc=7, end_hour_utc=20))
        ok, _ = sf.is_tradeable(datetime(2024, 6, 3, 21, 0, tzinfo=timezone.utc))
        assert ok is False

    def test_allows_when_disabled(self):
        sf = SessionFilter(SessionFilterConfig(enabled=False))
        ok, _ = sf.is_tradeable(datetime(2024, 6, 3, 3, 0, tzinfo=timezone.utc))
        assert ok is True

    def test_blocks_friday_close(self):
        sf = SessionFilter(SessionFilterConfig(
            enabled=True, start_hour_utc=7, end_hour_utc=22,
            trade_friday_close=False
        ))
        # Friday 18:00 UTC
        ok, reason = sf.is_tradeable(datetime(2024, 6, 7, 18, 0, tzinfo=timezone.utc))
        assert ok is False
        assert "Friday" in reason

    def test_allows_friday_if_configured(self):
        sf = SessionFilter(SessionFilterConfig(
            enabled=True, start_hour_utc=7, end_hour_utc=22,
            trade_friday_close=True
        ))
        ok, _ = sf.is_tradeable(datetime(2024, 6, 7, 18, 0, tzinfo=timezone.utc))
        assert ok is True

    def test_friday_early_ok(self):
        sf = SessionFilter(SessionFilterConfig(
            enabled=True, start_hour_utc=7, end_hour_utc=20,
            trade_friday_close=False
        ))
        # Friday 10:00 — before 17:00 cutoff
        ok, _ = sf.is_tradeable(datetime(2024, 6, 7, 10, 0, tzinfo=timezone.utc))
        assert ok is True
