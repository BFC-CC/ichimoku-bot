"""Tests for signal scoring framework (Action 3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.signal_engine import SignalEngine, Signal, SignalResult
from core.ichimoku_calculator import IchimokuValues
from core.config_loader import (
    IchimokuConfig, EntryConditions, SignalScoringConfig,
)
from core.lot_calculator import LotCalculator, SymbolInfo
from core.config_loader import RiskManagementConfig


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


def _make_strong_buy_df(n: int = 200) -> pd.DataFrame:
    """Strong uptrend: chikou well above reference zone."""
    dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    close = np.concatenate([
        np.full(170, 1.0800),
        np.linspace(1.0800, 1.1500, 30),
    ])
    high = close + 0.0005
    low = close - 0.0005
    return pd.DataFrame(
        {"open": close.copy(), "high": high, "low": low, "close": close},
        index=dates,
    )


def _make_ichi(
    *,
    tenkan=1.1050, kijun=1.1040, close=1.1100,
    senkou_a=1.1060, senkou_b=1.1020,
    chikou=1.1100,
    prev_tenkan=1.1030, prev_kijun=1.1040,
    prev_close=1.1050,
) -> IchimokuValues:
    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)
    return IchimokuValues(
        tenkan=tenkan, kijun=kijun,
        senkou_a=senkou_a, senkou_b=senkou_b,
        chikou=chikou, close=close,
        cloud_top=cloud_top, cloud_bottom=cloud_bottom,
        prev_tenkan=prev_tenkan, prev_kijun=prev_kijun,
        prev_senkou_a=senkou_a, prev_senkou_b=senkou_b,
        prev_chikou=prev_close, prev_close=prev_close,
        prev_cloud_top=cloud_top, prev_cloud_bottom=cloud_bottom,
        future_span_a=senkou_a + 0.001, future_span_b=senkou_b - 0.001,
        cloud_thickness_pips=40.0,
        bar_time=pd.Timestamp("2024-06-01", tz="UTC"),
    )


class TestScoringDisabled:
    def test_score_defaults_to_one(self):
        """When scoring disabled, score should remain 1.0."""
        cfg = IchimokuConfig(
            signal_mode="tk_cross",
            entry_conditions=EntryConditions(
                require_chikou_clear=False, require_bullish_cloud=False
            ),
            signal_scoring=SignalScoringConfig(enabled=False),
        )
        engine = SignalEngine(cfg)
        ichi = _make_ichi()
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.score == 1.0
        assert result.score_breakdown == {}


class TestScoringEnabled:
    def test_score_computed_on_buy(self):
        """When scoring enabled, BUY signal should have score and breakdown."""
        cfg = IchimokuConfig(
            signal_mode="tk_cross",
            entry_conditions=EntryConditions(
                require_chikou_clear=False, require_bullish_cloud=False
            ),
            signal_scoring=SignalScoringConfig(enabled=True),
        )
        engine = SignalEngine(cfg)
        ichi = _make_ichi()
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        if result.signal == Signal.BUY:
            assert 0.0 <= result.score <= 1.0
            assert len(result.score_breakdown) > 0
            assert "tk_alignment" in result.score_breakdown

    def test_perfect_conditions_high_score(self):
        """Strong setup should produce a high score."""
        cfg = IchimokuConfig(
            signal_mode="tk_cross",
            entry_conditions=EntryConditions(
                require_chikou_clear=False, require_bullish_cloud=False
            ),
            signal_scoring=SignalScoringConfig(enabled=True),
        )
        engine = SignalEngine(cfg)
        # Strong BUY: tenkan well above kijun, price far above cloud, bullish cloud
        ichi = _make_ichi(
            tenkan=1.1200, kijun=1.1100,
            close=1.1500, senkou_a=1.1060, senkou_b=1.1020,
            prev_tenkan=1.1050, prev_kijun=1.1100,
        )
        df = _make_strong_buy_df()
        result = engine.evaluate(ichi, df)
        if result.signal == Signal.BUY:
            assert result.score >= 0.5

    def test_neutral_has_default_score(self):
        """NEUTRAL signals keep the default score of 1.0."""
        cfg = IchimokuConfig(
            signal_mode="tk_cross",
            entry_conditions=EntryConditions(
                require_chikou_clear=False, require_bullish_cloud=False
            ),
            signal_scoring=SignalScoringConfig(enabled=True),
        )
        engine = SignalEngine(cfg)
        # No cross
        ichi = _make_ichi(
            tenkan=1.1050, kijun=1.1040,
            prev_tenkan=1.1050, prev_kijun=1.1040,
        )
        df = _make_ohlc(200)
        result = engine.evaluate(ichi, df)
        assert result.signal == Signal.NEUTRAL
        assert result.score == 1.0

    def test_custom_weights(self):
        """Custom weights should be respected."""
        custom_weights = {
            "tk_alignment": 1.0,
            "price_vs_cloud": 0.0,
            "chikou_clear": 0.0,
            "cloud_direction": 0.0,
            "cloud_thickness": 0.0,
            "trend_filter": 0.0,
        }
        cfg = IchimokuConfig(
            signal_mode="tk_cross",
            entry_conditions=EntryConditions(
                require_chikou_clear=False, require_bullish_cloud=False
            ),
            signal_scoring=SignalScoringConfig(enabled=True, weights=custom_weights),
        )
        engine = SignalEngine(cfg)
        # tk_alignment only: tenkan well above kijun
        ichi = _make_ichi(
            tenkan=1.1200, kijun=1.1100,
            close=1.1500,
            prev_tenkan=1.1050, prev_kijun=1.1100,
        )
        df = _make_strong_buy_df()
        result = engine.evaluate(ichi, df)
        if result.signal == Signal.BUY:
            # Score should be dominated by tk_alignment
            assert result.score_breakdown["tk_alignment"] > 0


class TestLotScaling:
    def test_score_scales_lot(self):
        """Lot size should scale with signal score."""
        rm = RiskManagementConfig(risk_per_trade_pct=1.0, lot_mode="risk_pct")
        calc = LotCalculator(rm)
        info = SymbolInfo(name="EURUSD")

        lot_full = calc.calculate(10000, 1.1000, 1.0960, "EURUSD", info, signal_score=1.0)
        lot_half = calc.calculate(10000, 1.1000, 1.0960, "EURUSD", info, signal_score=0.5)

        assert lot_half < lot_full
        # Should be roughly half (within rounding)
        assert lot_half <= lot_full * 0.6

    def test_fixed_mode_ignores_score(self):
        """Fixed lot mode should ignore signal score."""
        rm = RiskManagementConfig(lot_mode="fixed", fixed_lot_size=0.10)
        calc = LotCalculator(rm)
        info = SymbolInfo(name="EURUSD")

        lot = calc.calculate(10000, 1.1000, 1.0960, "EURUSD", info, signal_score=0.5)
        assert lot == 0.10

    def test_minimum_score_floor(self):
        """Score should be floored at 0.1 to avoid zero lots."""
        rm = RiskManagementConfig(risk_per_trade_pct=1.0, lot_mode="risk_pct")
        calc = LotCalculator(rm)
        info = SymbolInfo(name="EURUSD")

        lot = calc.calculate(10000, 1.1000, 1.0960, "EURUSD", info, signal_score=0.0)
        assert lot > 0
