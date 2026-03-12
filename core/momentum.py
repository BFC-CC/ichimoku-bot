"""
core/momentum.py
---------------------------------------------------------------------
Pure-pandas momentum indicator calculations for signal validation.

Provides RSI, ADX, EMA alignment, and ATR consistency scores combined
into a single 0-100 momentum score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _normalise_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure lowercase column names."""
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    return out


def _calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's smoothing RSI."""
    close = _normalise_cols(df)["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss = 0 (pure uptrend), RSI should be 100
    # When avg_gain = 0 (pure downtrend), RSI should be 0
    rsi = rsi.where(avg_loss > 0, 100.0)
    rsi = rsi.where(avg_gain > 0, other=rsi.where(avg_loss > 0, 100.0))
    return rsi.fillna(50.0)


def _calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index from +DI/-DI."""
    d = _normalise_cols(df)
    high, low, close = d["high"], d["low"], d["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100.0
    adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return adx.fillna(0.0)


def _calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def _atr_consistency(df: pd.DataFrame, period: int = 14, window: int = 5) -> float:
    """
    ATR coefficient of variation check, returns 0-1.
    Low CV = consistent volatility = higher score.
    """
    d = _normalise_cols(df)
    high, low, close = d["high"], d["low"], d["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    recent = atr.iloc[-window:]
    if len(recent) < window or recent.mean() == 0:
        return 0.5

    cv = float(recent.std() / recent.mean())
    # CV < 0.1 = very consistent (1.0), CV > 0.5 = inconsistent (0.0)
    return float(max(min(1.0 - (cv - 0.1) / 0.4, 1.0), 0.0))


def _ema_alignment(df: pd.DataFrame, direction: str) -> float:
    """
    EMA(9) > EMA(21) > EMA(50) ordering score, 0-1.
    BUY: ema9 > ema21 > ema50 is ideal.
    SELL: ema9 < ema21 < ema50 is ideal.
    """
    close = _normalise_cols(df)["close"]
    ema9 = float(_calc_ema(close, 9).iloc[-1])
    ema21 = float(_calc_ema(close, 21).iloc[-1])
    ema50 = float(_calc_ema(close, 50).iloc[-1])

    is_buy = direction.upper() == "BUY"
    score = 0.0

    if is_buy:
        if ema9 > ema21:
            score += 0.5
        if ema21 > ema50:
            score += 0.5
    else:
        if ema9 < ema21:
            score += 0.5
        if ema21 < ema50:
            score += 0.5

    return score


def calculate_momentum_score(df: pd.DataFrame, direction: str) -> float:
    """
    Master momentum scoring function. Returns 0-100.

    Components:
    - RSI: 0-30 pts (BUY: RSI 50-70 full marks; SELL: RSI 30-50)
    - ADX: 0-30 pts (>25 full, 20-25 half, <20 zero)
    - ATR consistency: 0-20 pts
    - EMA alignment: 0-20 pts

    Returns 50.0 if insufficient data (< 60 bars).
    """
    if len(df) < 60:
        return 50.0

    is_buy = direction.upper() == "BUY"

    # RSI component (0-30)
    rsi_val = float(_calc_rsi(df).iloc[-1])
    if is_buy:
        # BUY: RSI 50-70 is ideal
        if 50 <= rsi_val <= 70:
            rsi_pts = 30.0
        elif 40 <= rsi_val < 50:
            rsi_pts = 15.0 + (rsi_val - 40) * 1.5
        elif 70 < rsi_val <= 80:
            rsi_pts = 30.0 - (rsi_val - 70) * 3.0
        else:
            rsi_pts = 0.0
    else:
        # SELL: RSI 30-50 is ideal
        if 30 <= rsi_val <= 50:
            rsi_pts = 30.0
        elif 50 < rsi_val <= 60:
            rsi_pts = 30.0 - (rsi_val - 50) * 3.0
        elif 20 <= rsi_val < 30:
            rsi_pts = 15.0 + (rsi_val - 20) * 1.5
        else:
            rsi_pts = 0.0
    rsi_pts = max(rsi_pts, 0.0)

    # ADX component (0-30)
    adx_val = float(_calc_adx(df).iloc[-1])
    if adx_val >= 25:
        adx_pts = 30.0
    elif adx_val >= 20:
        adx_pts = 15.0
    else:
        adx_pts = 0.0

    # ATR consistency (0-20)
    atr_pts = _atr_consistency(df) * 20.0

    # EMA alignment (0-20)
    ema_pts = _ema_alignment(df, direction) * 20.0

    total = rsi_pts + adx_pts + atr_pts + ema_pts
    return round(max(min(total, 100.0), 0.0), 2)
