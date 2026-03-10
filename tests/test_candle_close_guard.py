"""Tests for core/candle_close_guard.py"""

from __future__ import annotations

import pandas as pd
import pytest

from core.candle_close_guard import CandleCloseGuard


def _make_df(n: int = 5) -> pd.DataFrame:
    """Create a simple OHLC DataFrame with n bars."""
    dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [1.1000 + i * 0.001 for i in range(n)],
            "high": [1.1050 + i * 0.001 for i in range(n)],
            "low": [1.0950 + i * 0.001 for i in range(n)],
            "close": [1.1020 + i * 0.001 for i in range(n)],
        },
        index=dates,
    )


class TestCandleCloseGuard:
    def test_strips_live_bar(self):
        guard = CandleCloseGuard()
        df = _make_df(5)
        closed, is_new = guard.get_closed_bars(df, "EURUSD")
        assert closed is not None
        assert len(closed) == 4  # 5 - 1 live bar
        assert is_new is True

    def test_dedup_same_bar(self):
        guard = CandleCloseGuard()
        df = _make_df(5)
        closed1, new1 = guard.get_closed_bars(df, "EURUSD")
        closed2, new2 = guard.get_closed_bars(df, "EURUSD")
        assert new1 is True
        assert new2 is False  # same bar, already processed

    def test_new_bar_after_update(self):
        guard = CandleCloseGuard()
        df1 = _make_df(5)
        guard.get_closed_bars(df1, "EURUSD")

        # Add a new bar
        df2 = _make_df(6)
        closed, is_new = guard.get_closed_bars(df2, "EURUSD")
        assert is_new is True
        assert len(closed) == 5

    def test_different_symbols_independent(self):
        guard = CandleCloseGuard()
        df = _make_df(5)
        _, new_eu = guard.get_closed_bars(df, "EURUSD")
        _, new_gb = guard.get_closed_bars(df, "GBPUSD")
        assert new_eu is True
        assert new_gb is True

    def test_too_few_bars(self):
        guard = CandleCloseGuard()
        df = _make_df(1)
        closed, is_new = guard.get_closed_bars(df, "EURUSD")
        assert closed is None
        assert is_new is False

    def test_reset_clears_state(self):
        guard = CandleCloseGuard()
        df = _make_df(5)
        guard.get_closed_bars(df, "EURUSD")
        guard.reset()
        _, is_new = guard.get_closed_bars(df, "EURUSD")
        assert is_new is True

    def test_reset_single_symbol(self):
        guard = CandleCloseGuard()
        df = _make_df(5)
        guard.get_closed_bars(df, "EURUSD")
        guard.get_closed_bars(df, "GBPUSD")
        guard.reset("EURUSD")
        _, new_eu = guard.get_closed_bars(df, "EURUSD")
        _, new_gb = guard.get_closed_bars(df, "GBPUSD")
        assert new_eu is True
        assert new_gb is False
