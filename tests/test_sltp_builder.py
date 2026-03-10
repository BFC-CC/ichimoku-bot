"""Tests for core/sltp_builder.py"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.sltp_builder import SLTPBuilder, SLTPResult
from core.config_loader import (
    RiskManagementConfig, StopLossConfig, TakeProfitConfig,
)
from core.ichimoku_calculator import IchimokuValues


def _make_ichi(**kw) -> IchimokuValues:
    defaults = dict(
        tenkan=1.1050, kijun=1.1040,
        senkou_a=1.1060, senkou_b=1.1020,
        chikou=1.1100, close=1.1100,
        cloud_top=1.1060, cloud_bottom=1.1020,
        prev_tenkan=1.1040, prev_kijun=1.1040,
        prev_senkou_a=1.1060, prev_senkou_b=1.1020,
        prev_chikou=1.1050, prev_close=1.1050,
        prev_cloud_top=1.1060, prev_cloud_bottom=1.1020,
        future_span_a=1.1070, future_span_b=1.1010,
        cloud_thickness_pips=40.0,
        bar_time=pd.Timestamp("2024-06-01", tz="UTC"),
    )
    defaults.update(kw)
    return IchimokuValues(**defaults)


def _make_df(n=100):
    rng = np.random.RandomState(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    close = 1.1 + np.cumsum(rng.randn(n) * 0.001)
    return pd.DataFrame({
        "open": close + rng.randn(n) * 0.0005,
        "high": close + rng.rand(n) * 0.003,
        "low": close - rng.rand(n) * 0.003,
        "close": close,
    }, index=dates)


class TestSLTPKijun:
    def test_buy_sl_below_kijun(self):
        cfg = RiskManagementConfig(
            stop_loss=StopLossConfig(method="kijun", buffer_pips=5),
            take_profit=TakeProfitConfig(method="ratio", rr_ratio=2.0),
        )
        builder = SLTPBuilder(cfg)
        ichi = _make_ichi(kijun=1.1040)
        result = builder.build("BUY", 1.1100, "EURUSD", ichi)
        assert result is not None
        assert result.sl < 1.1040  # below kijun
        assert result.sl == pytest.approx(1.1040 - 5 * 0.0001, abs=1e-5)

    def test_sell_sl_above_kijun(self):
        cfg = RiskManagementConfig(
            stop_loss=StopLossConfig(method="kijun", buffer_pips=5),
            take_profit=TakeProfitConfig(method="ratio", rr_ratio=2.0),
        )
        builder = SLTPBuilder(cfg)
        ichi = _make_ichi(kijun=1.1040)
        result = builder.build("SELL", 1.0900, "EURUSD", ichi)
        assert result is not None
        assert result.sl > 1.1040  # above kijun


class TestSLTPRatio:
    def test_tp_at_rr_ratio(self):
        cfg = RiskManagementConfig(
            stop_loss=StopLossConfig(method="fixed_pips", fixed_pips=40),
            take_profit=TakeProfitConfig(method="ratio", rr_ratio=2.0),
        )
        builder = SLTPBuilder(cfg)
        ichi = _make_ichi()
        result = builder.build("BUY", 1.1000, "EURUSD", ichi)
        assert result is not None
        sl_dist = abs(1.1000 - result.sl)
        tp_dist = abs(result.tp - 1.1000)
        assert tp_dist == pytest.approx(sl_dist * 2.0, rel=0.01)


class TestSLTPFixedPips:
    def test_fixed_pips_sl(self):
        cfg = RiskManagementConfig(
            stop_loss=StopLossConfig(method="fixed_pips", fixed_pips=40),
            take_profit=TakeProfitConfig(method="fixed_pips", fixed_pips=80),
        )
        builder = SLTPBuilder(cfg)
        ichi = _make_ichi()
        result = builder.build("BUY", 1.1000, "EURUSD", ichi)
        assert result is not None
        assert result.sl == pytest.approx(1.1000 - 40 * 0.0001, abs=1e-5)
        assert result.tp == pytest.approx(1.1000 + 80 * 0.0001, abs=1e-5)


class TestSLTPCloudEdge:
    def test_buy_sl_below_cloud_bottom(self):
        cfg = RiskManagementConfig(
            stop_loss=StopLossConfig(method="cloud_edge", buffer_pips=5),
            take_profit=TakeProfitConfig(method="ratio", rr_ratio=2.0),
        )
        builder = SLTPBuilder(cfg)
        ichi = _make_ichi(cloud_bottom=1.1020)
        result = builder.build("BUY", 1.1100, "EURUSD", ichi)
        assert result is not None
        assert result.sl < 1.1020


class TestSLTPATR:
    def test_atr_sl(self):
        cfg = RiskManagementConfig(
            stop_loss=StopLossConfig(method="atr", atr_period=14, atr_multiplier=1.5),
            take_profit=TakeProfitConfig(method="ratio", rr_ratio=2.0),
        )
        builder = SLTPBuilder(cfg)
        ichi = _make_ichi()
        df = _make_df(100)
        result = builder.build("BUY", 1.1100, "EURUSD", ichi, df)
        assert result is not None
        assert result.sl < 1.1100


class TestSLTPMinimum:
    def test_rejects_if_sl_too_close(self):
        cfg = RiskManagementConfig(
            stop_loss=StopLossConfig(method="kijun", buffer_pips=0),
            take_profit=TakeProfitConfig(method="ratio", rr_ratio=2.0),
        )
        builder = SLTPBuilder(cfg)
        # kijun very close to entry
        ichi = _make_ichi(kijun=1.10001)
        result = builder.build("BUY", 1.10001, "EURUSD", ichi)
        assert result is None


class TestSLTPJPY:
    def test_jpy_sl(self):
        cfg = RiskManagementConfig(
            stop_loss=StopLossConfig(method="fixed_pips", fixed_pips=40),
            take_profit=TakeProfitConfig(method="fixed_pips", fixed_pips=80),
        )
        builder = SLTPBuilder(cfg)
        ichi = _make_ichi()
        result = builder.build("BUY", 150.00, "USDJPY", ichi)
        assert result is not None
        # 40 pips * 0.01 = 0.40
        assert result.sl == pytest.approx(150.00 - 0.40, abs=0.01)
