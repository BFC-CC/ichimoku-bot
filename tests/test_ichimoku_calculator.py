"""Tests for core/ichimoku_calculator.py"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.ichimoku_calculator import IchimokuCalculator, IchimokuValues, pip_size
from core.config_loader import IchimokuConfig


def _make_ohlc(n: int = 200, base: float = 1.1000, seed: int = 42) -> pd.DataFrame:
    """Generate deterministic OHLC data with n bars."""
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


class TestPipSize:
    def test_jpy_pairs(self):
        assert pip_size("USDJPY") == 0.01
        assert pip_size("EURJPY") == 0.01

    def test_non_jpy_pairs(self):
        assert pip_size("EURUSD") == 0.0001
        assert pip_size("GBPUSD") == 0.0001
        assert pip_size("AUDUSD") == 0.0001


class TestIchimokuCalculator:
    def test_compute_returns_values(self):
        calc = IchimokuCalculator()
        df = _make_ohlc(200)
        vals = calc.compute(df, "EURUSD")
        assert vals is not None
        assert isinstance(vals, IchimokuValues)

    def test_returns_none_insufficient_bars(self):
        calc = IchimokuCalculator()
        df = _make_ohlc(50)
        vals = calc.compute(df, "EURUSD")
        assert vals is None

    def test_frozen_dataclass(self):
        calc = IchimokuCalculator()
        vals = calc.compute(_make_ohlc(200), "EURUSD")
        with pytest.raises(AttributeError):
            vals.tenkan = 999  # type: ignore

    def test_cloud_top_gte_bottom(self):
        calc = IchimokuCalculator()
        vals = calc.compute(_make_ohlc(200), "EURUSD")
        assert vals.cloud_top >= vals.cloud_bottom

    def test_cloud_thickness_positive(self):
        calc = IchimokuCalculator()
        vals = calc.compute(_make_ohlc(200), "EURUSD")
        assert vals.cloud_thickness_pips >= 0

    def test_jpy_cloud_thickness(self):
        calc = IchimokuCalculator()
        df = _make_ohlc(200, base=150.0)
        vals = calc.compute(df, "USDJPY")
        # JPY pip size is 0.01, so thickness should be reasonable
        assert vals.cloud_thickness_pips >= 0

    def test_bar_time_matches_last_bar(self):
        calc = IchimokuCalculator()
        df = _make_ohlc(200)
        vals = calc.compute(df, "EURUSD")
        assert vals.bar_time == df.index[-1]

    def test_close_matches_dataframe(self):
        calc = IchimokuCalculator()
        df = _make_ohlc(200)
        vals = calc.compute(df, "EURUSD")
        assert abs(vals.close - df["close"].iloc[-1]) < 1e-10

    def test_prev_close_matches_dataframe(self):
        calc = IchimokuCalculator()
        df = _make_ohlc(200)
        vals = calc.compute(df, "EURUSD")
        assert abs(vals.prev_close - df["close"].iloc[-2]) < 1e-10

    def test_future_cloud_values_exist(self):
        calc = IchimokuCalculator()
        vals = calc.compute(_make_ohlc(200), "EURUSD")
        assert vals.future_span_a != 0.0 or vals.future_span_b != 0.0

    def test_custom_config(self):
        cfg = IchimokuConfig(tenkan_period=9, kijun_period=26, senkou_b_period=52)
        calc = IchimokuCalculator(cfg)
        vals = calc.compute(_make_ohlc(200), "EURUSD")
        assert vals is not None
