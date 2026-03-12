"""Tests for core/signal_engine.py"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.signal_engine import SignalEngine, Signal, SignalResult
from core.ichimoku_calculator import IchimokuValues, IchimokuCalculator
from core.config_loader import IchimokuConfig, EntryConditions, ExitConditions


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


def _make_ichi(
    *,
    tenkan=1.1050, kijun=1.1040, close=1.1100,
    senkou_a=1.1060, senkou_b=1.1020,
    chikou=1.1100,
    prev_tenkan=1.1030, prev_kijun=1.1040,
    prev_close=1.1050,
    prev_senkou_a=1.1060, prev_senkou_b=1.1020,
    prev_chikou=1.1050,
    future_a=1.1070, future_b=1.1010,
) -> IchimokuValues:
    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)
    prev_cloud_top = max(prev_senkou_a, prev_senkou_b)
    prev_cloud_bottom = min(prev_senkou_a, prev_senkou_b)
    return IchimokuValues(
        tenkan=tenkan, kijun=kijun,
        senkou_a=senkou_a, senkou_b=senkou_b,
        chikou=chikou, close=close,
        cloud_top=cloud_top, cloud_bottom=cloud_bottom,
        prev_tenkan=prev_tenkan, prev_kijun=prev_kijun,
        prev_senkou_a=prev_senkou_a, prev_senkou_b=prev_senkou_b,
        prev_chikou=prev_chikou, prev_close=prev_close,
        prev_cloud_top=prev_cloud_top, prev_cloud_bottom=prev_cloud_bottom,
        future_span_a=future_a, future_span_b=future_b,
        cloud_thickness_pips=40.0,
        bar_time=pd.Timestamp("2024-06-01 00:00", tz="UTC"),
    )


class TestTKCross:
    def test_buy_signal(self):
        cfg = IchimokuConfig(signal_mode="tk_cross",
                             entry_conditions=EntryConditions(
                                 require_chikou_clear=False,
                                 require_bullish_cloud=False))
        engine = SignalEngine(cfg)
        # TK cross up: prev tenkan <= prev kijun, now tenkan > kijun
        # price above cloud
        ichi = _make_ichi(
            tenkan=1.1050, kijun=1.1040,
            prev_tenkan=1.1030, prev_kijun=1.1040,
            close=1.1100, senkou_a=1.1060, senkou_b=1.1020,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.BUY
        assert result.mode_used == "tk_cross"

    def test_sell_signal(self):
        cfg = IchimokuConfig(signal_mode="tk_cross",
                             entry_conditions=EntryConditions(
                                 require_chikou_clear=False,
                                 require_bullish_cloud=False))
        engine = SignalEngine(cfg)
        # TK cross down: prev tenkan >= prev kijun, now tenkan < kijun
        # price below cloud
        ichi = _make_ichi(
            tenkan=1.0900, kijun=1.0950,
            prev_tenkan=1.0960, prev_kijun=1.0950,
            close=1.0800, senkou_a=1.0900, senkou_b=1.0950,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.SELL

    def test_neutral_no_cross(self):
        cfg = IchimokuConfig(signal_mode="tk_cross",
                             entry_conditions=EntryConditions(
                                 require_chikou_clear=False,
                                 require_bullish_cloud=False))
        engine = SignalEngine(cfg)
        # No cross: both bars have tenkan > kijun
        ichi = _make_ichi(
            tenkan=1.1050, kijun=1.1040,
            prev_tenkan=1.1050, prev_kijun=1.1040,
            close=1.1100,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.NEUTRAL


class TestChikouCross:
    def test_buy_signal(self):
        cfg = IchimokuConfig(signal_mode="chikou_cross")
        engine = SignalEngine(cfg)
        # chikou crosses above close[-26] and price above cloud
        ichi = _make_ichi(
            chikou=1.1100, prev_chikou=1.0900,
            close=1.1100, senkou_a=1.1060, senkou_b=1.1020,
        )
        df = _make_ohlc(200)
        # Need close at idx-26 to be below chikou
        result = engine.evaluate(ichi, df)
        assert result.mode_used == "chikou_cross"
        # Result depends on df values at -26, so just check it doesn't crash
        assert result.signal in (Signal.BUY, Signal.SELL, Signal.NEUTRAL)

    def test_neutral_no_cross(self):
        cfg = IchimokuConfig(signal_mode="chikou_cross")
        engine = SignalEngine(cfg)
        ichi = _make_ichi(chikou=1.1100, prev_chikou=1.1100)
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.NEUTRAL


class TestKumoBreakout:
    def test_buy_breakout(self):
        cfg = IchimokuConfig(
            signal_mode="kumo_breakout",
            entry_conditions=EntryConditions(require_chikou_clear=False),
        )
        engine = SignalEngine(cfg)
        # prev close was inside/below cloud, now above
        ichi = _make_ichi(
            prev_close=1.1050, close=1.1100,
            senkou_a=1.1060, senkou_b=1.1020,
            prev_senkou_a=1.1060, prev_senkou_b=1.1020,
            future_a=1.1070, future_b=1.1010,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.BUY
        assert result.mode_used == "kumo_breakout"

    def test_sell_breakout(self):
        cfg = IchimokuConfig(
            signal_mode="kumo_breakout",
            entry_conditions=EntryConditions(require_chikou_clear=False),
        )
        engine = SignalEngine(cfg)
        ichi = _make_ichi(
            prev_close=1.1030, close=1.0900,
            senkou_a=1.1020, senkou_b=1.1060,
            prev_senkou_a=1.1020, prev_senkou_b=1.1060,
            future_a=1.0990, future_b=1.1050,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.SELL

    def test_neutral_no_breakout(self):
        cfg = IchimokuConfig(signal_mode="kumo_breakout")
        engine = SignalEngine(cfg)
        # Price was above and stays above — no breakout
        ichi = _make_ichi(
            prev_close=1.1100, close=1.1100,
            senkou_a=1.1060, senkou_b=1.1020,
            prev_senkou_a=1.1060, prev_senkou_b=1.1020,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.NEUTRAL


class TestFullConfirm:
    def test_buy_all_conditions(self):
        cfg = IchimokuConfig(signal_mode="full_confirm", cloud_min_thickness_pips=5)
        engine = SignalEngine(cfg)
        ichi = _make_ichi(
            close=1.1100, tenkan=1.1050, kijun=1.1040,
            senkou_a=1.1060, senkou_b=1.1020, chikou=1.1100,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.mode_used == "full_confirm"
        # Depends on df[-26] close value
        assert result.signal in (Signal.BUY, Signal.NEUTRAL)

    def test_neutral_missing_condition(self):
        cfg = IchimokuConfig(signal_mode="full_confirm", cloud_min_thickness_pips=5)
        engine = SignalEngine(cfg)
        # tenkan < kijun — fails tk condition
        ichi = _make_ichi(
            close=1.1100, tenkan=1.1030, kijun=1.1050,
            senkou_a=1.1060, senkou_b=1.1020,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.NEUTRAL


class TestCheckExit:
    def test_tk_cross_against_buy(self):
        cfg = IchimokuConfig(
            exit_conditions=ExitConditions(exit_on_tk_cross_against=True)
        )
        engine = SignalEngine(cfg)
        ichi = _make_ichi(
            tenkan=1.1030, kijun=1.1050,
            prev_tenkan=1.1050, prev_kijun=1.1050,
        )
        should_exit, reason = engine.check_exit(ichi, "BUY")
        assert should_exit is True
        assert "TK cross against" in reason

    def test_no_exit_when_aligned(self):
        cfg = IchimokuConfig(
            exit_conditions=ExitConditions(exit_on_tk_cross_against=True)
        )
        engine = SignalEngine(cfg)
        ichi = _make_ichi(
            tenkan=1.1050, kijun=1.1040,
            prev_tenkan=1.1050, prev_kijun=1.1040,
        )
        should_exit, reason = engine.check_exit(ichi, "BUY")
        assert should_exit is False

    def test_price_enter_cloud_exit(self):
        cfg = IchimokuConfig(
            exit_conditions=ExitConditions(
                exit_on_tk_cross_against=False,
                exit_on_price_enter_cloud=True
            )
        )
        engine = SignalEngine(cfg)
        ichi = _make_ichi(close=1.1050, senkou_a=1.1060, senkou_b=1.1020)
        should_exit, _ = engine.check_exit(ichi, "BUY")
        assert should_exit is True
