"""Tests for news filter v2 with calendar integration (Action 5)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import json
import tempfile
import os

import pytest

from core.config_loader import NewsFilterConfig
from core.news_calendar import NewsCalendar, NewsEvent
from core.news_filter import NewsFilter


def _make_config(
    enabled: bool = True,
    minutes_before: int = 30,
    minutes_after: int = 30,
    static_path: str = "",
) -> NewsFilterConfig:
    return NewsFilterConfig(
        enabled=enabled,
        minutes_before=minutes_before,
        minutes_after=minutes_after,
        impact_levels=["high"],
        calendar_source="static",
        static_events_path=static_path,
    )


def _write_events_file(events_data: dict) -> str:
    """Write events JSON to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(events_data, f)
    return path


class TestNewsCalendar:
    def test_load_specific_dates(self):
        data = {
            "recurring_monthly": [],
            "specific_dates": [
                {
                    "name": "FOMC",
                    "currency": "USD",
                    "date": "2026-03-18",
                    "time_utc": "19:00",
                    "impact": "high",
                }
            ],
        }
        path = _write_events_file(data)
        try:
            cfg = _make_config(static_path=path)
            cal = NewsCalendar(cfg)
            assert len([e for e in cal._events if e.name == "FOMC"]) >= 1
        finally:
            os.unlink(path)

    def test_recurring_first_friday(self):
        data = {
            "recurring_monthly": [
                {
                    "name": "NFP",
                    "currency": "USD",
                    "rule": "first_friday",
                    "time_utc": "13:30",
                    "impact": "high",
                }
            ],
            "specific_dates": [],
        }
        path = _write_events_file(data)
        try:
            cfg = _make_config(static_path=path)
            cal = NewsCalendar(cfg)
            nfp_events = [e for e in cal._events if e.name == "NFP"]
            assert len(nfp_events) > 0
            for ev in nfp_events:
                assert ev.event_time.weekday() == 4  # Friday
                assert ev.event_time.hour == 13
                assert ev.event_time.minute == 30
        finally:
            os.unlink(path)

    def test_blackout_during_event(self):
        event_time = datetime(2026, 3, 18, 19, 0, tzinfo=timezone.utc)
        data = {
            "recurring_monthly": [],
            "specific_dates": [
                {
                    "name": "FOMC",
                    "currency": "USD",
                    "date": "2026-03-18",
                    "time_utc": "19:00",
                    "impact": "high",
                }
            ],
        }
        path = _write_events_file(data)
        try:
            cfg = _make_config(static_path=path, minutes_before=30, minutes_after=30)
            cal = NewsCalendar(cfg)

            # 10 minutes before FOMC
            now = event_time - timedelta(minutes=10)
            blocked, reason = cal.is_blackout("EURUSD", now)
            assert blocked is True
            assert "FOMC" in reason

            # 10 minutes after FOMC
            now = event_time + timedelta(minutes=10)
            blocked, reason = cal.is_blackout("EURUSD", now)
            assert blocked is True

            # 60 minutes after FOMC — outside window
            now = event_time + timedelta(minutes=60)
            blocked, reason = cal.is_blackout("EURUSD", now)
            assert blocked is False
        finally:
            os.unlink(path)

    def test_unaffected_pair_not_blocked(self):
        """GBPJPY should not be blocked by USD events."""
        event_time = datetime(2026, 3, 18, 19, 0, tzinfo=timezone.utc)
        data = {
            "recurring_monthly": [],
            "specific_dates": [
                {
                    "name": "FOMC",
                    "currency": "USD",
                    "date": "2026-03-18",
                    "time_utc": "19:00",
                    "impact": "high",
                }
            ],
        }
        path = _write_events_file(data)
        try:
            cfg = _make_config(static_path=path)
            cal = NewsCalendar(cfg)

            now = event_time - timedelta(minutes=5)
            blocked, _ = cal.is_blackout("GBPJPY", now)
            # USD event should not affect GBPJPY
            assert blocked is False

            # But should affect EURUSD
            blocked, _ = cal.is_blackout("EURUSD", now)
            assert blocked is True
        finally:
            os.unlink(path)

    def test_currency_affects_symbol(self):
        assert NewsCalendar._currency_affects_symbol("USD", "EURUSD") is True
        assert NewsCalendar._currency_affects_symbol("USD", "USDJPY") is True
        assert NewsCalendar._currency_affects_symbol("EUR", "EURUSD") is True
        assert NewsCalendar._currency_affects_symbol("JPY", "EURUSD") is False
        assert NewsCalendar._currency_affects_symbol("GBP", "EURUSD") is False

    def test_missing_file_returns_empty(self):
        cfg = _make_config(static_path="/nonexistent/path.json")
        cal = NewsCalendar(cfg)
        assert cal._events == []


class TestNewsFilter:
    def test_disabled_always_clear(self):
        cfg = NewsFilterConfig(enabled=False)
        nf = NewsFilter(cfg)
        ok, reason = nf.is_clear("EURUSD", datetime.now(timezone.utc))
        assert ok is True
        assert reason == "ok"

    def test_enabled_blocks_during_event(self):
        event_time = datetime(2026, 3, 18, 19, 0, tzinfo=timezone.utc)
        data = {
            "recurring_monthly": [],
            "specific_dates": [
                {
                    "name": "FOMC",
                    "currency": "USD",
                    "date": "2026-03-18",
                    "time_utc": "19:00",
                    "impact": "high",
                }
            ],
        }
        path = _write_events_file(data)
        try:
            cfg = _make_config(enabled=True, static_path=path)
            nf = NewsFilter(cfg)

            now = event_time - timedelta(minutes=5)
            ok, reason = nf.is_clear("EURUSD", now)
            assert ok is False
            assert "blackout" in reason.lower()
        finally:
            os.unlink(path)

    def test_enabled_clear_outside_window(self):
        event_time = datetime(2026, 3, 18, 19, 0, tzinfo=timezone.utc)
        data = {
            "recurring_monthly": [],
            "specific_dates": [
                {
                    "name": "FOMC",
                    "currency": "USD",
                    "date": "2026-03-18",
                    "time_utc": "19:00",
                    "impact": "high",
                }
            ],
        }
        path = _write_events_file(data)
        try:
            cfg = _make_config(enabled=True, static_path=path)
            nf = NewsFilter(cfg)

            # Well outside window
            now = event_time + timedelta(hours=2)
            ok, reason = nf.is_clear("EURUSD", now)
            assert ok is True
        finally:
            os.unlink(path)

    def test_backward_compat_disabled(self):
        """Old config with just enabled=False should still work."""
        cfg = NewsFilterConfig(enabled=False)
        nf = NewsFilter(cfg)
        ok, _ = nf.is_clear("EURUSD", datetime.now(timezone.utc))
        assert ok is True
