"""Tests for chikou span clearance filter (Action 1)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.ichimoku_calculator import is_chikou_clear
from core.signal_engine import SignalEngine, Signal
from core.config_loader import IchimokuConfig, EntryConditions


def _make_ohlc(n: int = 200, base: float = 1.1000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    close = base + np.cumsum(rng.randn(n) * 0.001)
    high = close + rng.rand(n) * 0.003
    low = close - rng.rand(n) * 0.003
    open_ = close + rng.randn(n) * 0.001
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=dates,
    )


def _make_clear_df(n: int = 200) -> pd.DataFrame:
    """Create OHLC where chikou (current close) is clearly above the reference zone."""
    dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    # First 180 bars at base level, then trend up sharply
    close = np.concatenate([
        np.full(180, 1.1000),
        np.linspace(1.1000, 1.1500, 20),
    ])
    high = close + 0.0010
    low = close - 0.0010
    open_ = close.copy()
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=dates,
    )


def _make_congested_df(n: int = 200) -> pd.DataFrame:
    """Create OHLC where chikou (current close) is inside the reference zone."""
    dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    # Flat market: highs/lows create a wide range chikou can't escape
    close = np.full(n, 1.1000)
    high = np.full(n, 1.1050)   # high above close
    low = np.full(n, 1.0950)    # low below close
    open_ = close.copy()
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=dates,
    )


class TestIsChikouClear:
    def test_chikou_above_congestion_clear(self):
        """Chikou (current close) is well above the high-low range at ref point."""
        df = _make_clear_df()
        clear, margin = is_chikou_clear(df, "BUY", displacement=26, lookback=5)
        assert clear is True
        assert margin > 0

    def test_chikou_inside_congestion_blocked(self):
        """Chikou is inside the high-low range at ref point."""
        df = _make_congested_df()
        clear, margin = is_chikou_clear(df, "BUY", displacement=26, lookback=5)
        assert clear is False
        assert margin < 0

    def test_sell_direction(self):
        """SELL direction: chikou must be below lowest low."""
        df = _make_congested_df()
        # Current close (1.1000) is above lowest low (1.0950) → not clear for sell
        clear, margin = is_chikou_clear(df, "SELL", displacement=26, lookback=5)
        assert clear is False

    def test_sell_direction_clear(self):
        """SELL direction with price well below the reference zone."""
        dates = pd.date_range("2024-01-01", periods=200, freq="4h", tz="UTC")
        close = np.concatenate([
            np.full(180, 1.1000),
            np.linspace(1.1000, 1.0500, 20),  # trend down
        ])
        high = close + 0.0010
        low = close - 0.0010
        df = pd.DataFrame(
            {"open": close.copy(), "high": high, "low": low, "close": close},
            index=dates,
        )
        clear, margin = is_chikou_clear(df, "SELL", displacement=26, lookback=5)
        assert clear is True
        assert margin > 0

    def test_insufficient_bars_fallback(self):
        """With too few bars, should return (True, 0.0) as fallback."""
        df = _make_ohlc(30)
        clear, margin = is_chikou_clear(df, "BUY", displacement=26, lookback=5)
        assert clear is True
        assert margin == 0.0

    def test_lookback_parameter_respected(self):
        """Larger lookback should consider more bars in the window."""
        df = _make_congested_df()
        # Both should be blocked but with lookback=0, only the ref bar is checked
        clear_narrow, margin_narrow = is_chikou_clear(df, "BUY", displacement=26, lookback=1)
        clear_wide, margin_wide = is_chikou_clear(df, "BUY", displacement=26, lookback=10)
        # With congested data (same highs/lows), both should be blocked
        assert clear_narrow is False
        assert clear_wide is False

    def test_margin_pips_value(self):
        """Margin should be positive when clear, negative when blocked."""
        df_clear = _make_clear_df()
        _, margin_clear = is_chikou_clear(df_clear, "BUY", displacement=26, lookback=5)
        assert margin_clear > 0

        df_blocked = _make_congested_df()
        _, margin_blocked = is_chikou_clear(df_blocked, "BUY", displacement=26, lookback=5)
        assert margin_blocked < 0


class TestChikouClearanceIntegration:
    """Integration with signal engine."""

    def test_buy_blocked_by_chikou_congestion(self):
        """TK cross BUY should be blocked when chikou is in congested zone."""
        cfg = IchimokuConfig(
            signal_mode="tk_cross",
            entry_conditions=EntryConditions(
                require_chikou_clear=True,
                require_bullish_cloud=False,
                chikou_clear_lookback=5,
            ),
        )
        engine = SignalEngine(cfg)

        # Use congested data — chikou will be inside the range
        df = _make_congested_df()

        from core.ichimoku_calculator import IchimokuValues
        ichi = IchimokuValues(
            tenkan=1.1050, kijun=1.1040,
            senkou_a=1.0900, senkou_b=1.0850,
            chikou=1.1000, close=1.1000,
            cloud_top=1.0900, cloud_bottom=1.0850,
            prev_tenkan=1.1030, prev_kijun=1.1040,
            prev_senkou_a=1.0900, prev_senkou_b=1.0850,
            prev_chikou=1.1000, prev_close=1.1000,
            prev_cloud_top=1.0900, prev_cloud_bottom=1.0850,
            future_span_a=1.0900, future_span_b=1.0850,
            cloud_thickness_pips=50.0,
            bar_time=pd.Timestamp("2024-06-01", tz="UTC"),
        )

        result = engine.evaluate(ichi, df)
        # Should be NEUTRAL because chikou clearance fails
        assert result.signal == Signal.NEUTRAL
