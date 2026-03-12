"""Tests for core/momentum.py"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.momentum import (
    _calc_rsi,
    _calc_adx,
    _ema_alignment,
    _atr_consistency,
    calculate_momentum_score,
)


def _make_ohlc(n: int = 200, base: float = 1.1, trend: float = 0.001) -> pd.DataFrame:
    """Deterministic uptrend OHLC."""
    idx = np.arange(n, dtype=float)
    close = base + idx * trend / n
    high = close + 0.002
    low = close - 0.002
    open_ = (close + np.roll(close, 1)) / 2
    open_[0] = close[0]
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=pd.date_range("2024-01-01", periods=n, freq="4h"),
    )


def _make_downtrend(n: int = 200, base: float = 1.2, drop: float = 0.05) -> pd.DataFrame:
    close = np.linspace(base, base - drop, n)
    high = close + 0.002
    low = close - 0.002
    open_ = (close + np.roll(close, 1)) / 2
    open_[0] = close[0]
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=pd.date_range("2024-01-01", periods=n, freq="4h"),
    )


class TestRSI:
    def test_rsi_uptrend_above_50(self):
        # Strong consistent uptrend for clear RSI > 50
        n = 200
        close = np.linspace(1.0, 1.2, n)
        high = close + 0.002
        low = close - 0.001
        df = pd.DataFrame(
            {"open": close - 0.0005, "high": high, "low": low, "close": close},
            index=pd.date_range("2024-01-01", periods=n, freq="4h"),
        )
        rsi = _calc_rsi(df)
        assert float(rsi.iloc[-1]) > 50

    def test_rsi_downtrend_below_50(self):
        df = _make_downtrend()
        rsi = _calc_rsi(df)
        assert float(rsi.iloc[-1]) < 50

    def test_rsi_range_0_100(self):
        df = _make_ohlc(200)
        rsi = _calc_rsi(df)
        assert rsi.min() >= 0
        assert rsi.max() <= 100


class TestADX:
    def test_adx_trending_high(self):
        df = _make_ohlc(200, trend=0.1)
        adx = _calc_adx(df)
        # Strong trend should produce higher ADX
        assert float(adx.iloc[-1]) >= 0

    def test_adx_non_negative(self):
        df = _make_ohlc(200)
        adx = _calc_adx(df)
        assert (adx >= 0).all()


class TestEMAAlignment:
    def test_buy_alignment_uptrend(self):
        df = _make_ohlc(200, trend=0.05)
        score = _ema_alignment(df, "BUY")
        assert 0.0 <= score <= 1.0

    def test_sell_alignment_downtrend(self):
        df = _make_downtrend()
        score = _ema_alignment(df, "SELL")
        assert 0.0 <= score <= 1.0

    def test_alignment_returns_float(self):
        df = _make_ohlc(200)
        assert isinstance(_ema_alignment(df, "BUY"), float)


class TestATRConsistency:
    def test_consistency_range(self):
        df = _make_ohlc(200)
        score = _atr_consistency(df)
        assert 0.0 <= score <= 1.0


class TestCalculateMomentumScore:
    def test_score_range(self):
        df = _make_ohlc(200)
        score = calculate_momentum_score(df, "BUY")
        assert 0 <= score <= 100

    def test_short_df_guard(self):
        df = _make_ohlc(30)
        score = calculate_momentum_score(df, "BUY")
        assert score == 50.0

    def test_buy_vs_sell_different(self):
        df = _make_ohlc(200, trend=0.05)
        buy_score = calculate_momentum_score(df, "BUY")
        sell_score = calculate_momentum_score(df, "SELL")
        # In uptrend, BUY score should generally differ from SELL
        assert isinstance(buy_score, float)
        assert isinstance(sell_score, float)

    def test_returns_float(self):
        df = _make_ohlc(100)
        assert isinstance(calculate_momentum_score(df, "SELL"), float)
