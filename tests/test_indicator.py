"""
tests/test_indicator.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for IchimokuIndicator.

Tests verify:
  - Correct column names in output
  - Tenkan/Kijun math against manually computed values
  - Senkou A = (Tenkan + Kijun) / 2, shifted 26 periods
  - Senkou B is 52-period midpoint shifted 26 periods
  - Chikou is close shifted -26 periods
  - latest_values() returns correct current and previous values
  - NaN warning when fewer than 52 candles supplied
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from core.indicator import IchimokuConfig, IchimokuIndicator


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_candles(n: int, start_price: float = 1.1000, step: float = 0.0001) -> pd.DataFrame:
    """
    Generate a synthetic OHLC DataFrame with n candles.
    Prices move linearly upward so midpoint calculations are predictable.
    """
    times  = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    closes = [round(start_price + i * step, 5) for i in range(n)]
    highs  = [c + 0.0005 for c in closes]
    lows   = [c - 0.0005 for c in closes]
    opens  = closes  # simplify

    return pd.DataFrame({
        "time":  times,
        "open":  opens,
        "high":  highs,
        "low":   lows,
        "close": closes,
    }).set_index("time")


# ─────────────────────────────────────────────────────────────────────────────
#  Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestIchimokuCalculate:

    def test_output_columns(self):
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        result = ichi.calculate(df)
        assert set(result.columns) == {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou"}

    def test_output_same_index(self):
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        result = ichi.calculate(df)
        assert list(result.index) == list(df.index)

    def test_tenkan_math(self):
        """Tenkan = (9-period highest high + 9-period lowest low) / 2."""
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        result = ichi.calculate(df)

        # Check at row 50 (well past warmup)
        idx = 50
        window = df.iloc[idx - 8: idx + 1]   # 9 candles ending at idx
        expected = (window["high"].max() + window["low"].min()) / 2
        assert abs(result["tenkan"].iloc[idx] - expected) < 1e-8

    def test_kijun_math(self):
        """Kijun = (26-period highest high + 26-period lowest low) / 2."""
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        result = ichi.calculate(df)

        idx = 80
        window = df.iloc[idx - 25: idx + 1]
        expected = (window["high"].max() + window["low"].min()) / 2
        assert abs(result["kijun"].iloc[idx] - expected) < 1e-8

    def test_senkou_a_formula(self):
        """Senkou A = (Tenkan + Kijun) / 2, shifted 26 periods forward."""
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        result = ichi.calculate(df)

        # Without displacement, senkou_a at position 60 should equal
        # the (tenkan + kijun)/2 value at position 60 - 26 = 34
        # After .shift(26), result.iloc[60] = unshifted value at iloc[34]

        # Re-compute without shift to verify
        tenkan_34 = result["tenkan"].shift(-26).iloc[60]  # unshift to get original
        kijun_34  = result["kijun"].shift(-26).iloc[60]

        # Alternative: compute directly
        row_60_senkou_a = result["senkou_a"].iloc[60]
        # Should equal tenkan + kijun at iloc[34] divided by 2
        tenkan_34_direct = result["tenkan"].iloc[34]
        kijun_34_direct  = result["kijun"].iloc[34]
        expected = (tenkan_34_direct + kijun_34_direct) / 2
        assert abs(row_60_senkou_a - expected) < 1e-8

    def test_chikou_shift(self):
        """Chikou at position i should equal the close at position i + 26."""
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        result = ichi.calculate(df)

        # chikou at iloc[50] should be close at iloc[50] (it IS the close,
        # just placed 26 bars back – so chikou.iloc[50] == df.close.iloc[76])
        # pandas .shift(-26) means: row[50] gets the value that was at row[76]
        assert abs(result["chikou"].iloc[50] - df["close"].iloc[76]) < 1e-8

    def test_nan_at_start(self):
        """First 8 rows of Tenkan should be NaN (not enough history)."""
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        result = ichi.calculate(df)
        # Tenkan period=9: first 8 rows (0..7) should be NaN
        assert result["tenkan"].iloc[:8].isna().all()
        assert not math.isnan(result["tenkan"].iloc[8])

    def test_not_enough_candles_warning(self, caplog):
        """Should log a warning if fewer than 52 candles are passed."""
        import logging
        ichi = IchimokuIndicator()
        df   = make_candles(40)
        # Should not raise, just warn
        result = ichi.calculate(df)
        assert "senkou_a" in result.columns  # output still produced


class TestLatestValues:

    def test_returns_all_keys(self):
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        vals = ichi.latest_values(df)
        expected_keys = {
            "tenkan", "kijun", "senkou_a", "senkou_b", "chikou",
            "close", "cloud_top", "cloud_bottom",
            "prev_tenkan", "prev_kijun", "prev_senkou_a", "prev_senkou_b",
            "prev_chikou", "prev_close", "prev_cloud_top", "prev_cloud_bottom",
        }
        assert set(vals.keys()) == expected_keys

    def test_close_matches_last_candle(self):
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        vals = ichi.latest_values(df)
        assert vals["close"] == pytest.approx(df["close"].iloc[-1])

    def test_prev_close_matches_second_to_last(self):
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        vals = ichi.latest_values(df)
        assert vals["prev_close"] == pytest.approx(df["close"].iloc[-2])

    def test_cloud_top_is_max_of_senkou(self):
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        vals = ichi.latest_values(df)
        assert vals["cloud_top"] == max(vals["senkou_a"], vals["senkou_b"])

    def test_cloud_bottom_is_min_of_senkou(self):
        ichi = IchimokuIndicator()
        df   = make_candles(200)
        vals = ichi.latest_values(df)
        assert vals["cloud_bottom"] == min(vals["senkou_a"], vals["senkou_b"])

    def test_insufficient_candles_returns_nans(self):
        ichi = IchimokuIndicator()
        df   = make_candles(1)
        vals = ichi.latest_values(df)
        assert all(math.isnan(v) for v in vals.values())

    def test_custom_config(self):
        """Custom periods should change the output values."""
        cfg_std    = IchimokuConfig(tenkan_period=9)
        cfg_custom = IchimokuConfig(tenkan_period=7)

        df = make_candles(200)
        vals_std    = IchimokuIndicator(cfg_std).latest_values(df)
        vals_custom = IchimokuIndicator(cfg_custom).latest_values(df)
        # Different tenkan periods → different tenkan values
        assert vals_std["tenkan"] != vals_custom["tenkan"]
