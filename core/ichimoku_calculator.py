"""
core/ichimoku_calculator.py
─────────────────────────────────────────────────────────────────────────────
Wraps core.indicator.IchimokuIndicator and returns a frozen IchimokuValues
dataclass snapshot suitable for the signal engine, risk math, and logging.

Usage
-----
    from core.ichimoku_calculator import IchimokuCalculator
    calc = IchimokuCalculator(config)
    values = calc.compute(df_closed)  # df_closed = live bar already stripped
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from loguru import logger

from core.indicator import IchimokuIndicator, IchimokuConfig as _IndicatorConfig
from core.config_loader import IchimokuConfig


@dataclass(frozen=True)
class IchimokuValues:
    """Frozen snapshot of all Ichimoku values at the last closed bar."""
    # Current bar values
    tenkan: float
    kijun: float
    senkou_a: float
    senkou_b: float
    chikou: float
    close: float
    cloud_top: float
    cloud_bottom: float

    # Previous bar values
    prev_tenkan: float
    prev_kijun: float
    prev_senkou_a: float
    prev_senkou_b: float
    prev_chikou: float
    prev_close: float
    prev_cloud_top: float
    prev_cloud_bottom: float

    # Extra fields for trading
    future_span_a: float
    future_span_b: float
    cloud_thickness_pips: float
    bar_time: pd.Timestamp


def pip_size(symbol: str) -> float:
    """Return pip size: 0.01 for JPY pairs, 0.0001 for all others."""
    return 0.01 if "JPY" in symbol.upper() else 0.0001


class IchimokuCalculator:
    """Wraps existing IchimokuIndicator, returns IchimokuValues snapshot."""

    def __init__(self, config: Optional[IchimokuConfig] = None) -> None:
        self.cfg = config or IchimokuConfig()
        self._indicator = IchimokuIndicator(
            _IndicatorConfig(
                tenkan_period=self.cfg.tenkan_period,
                kijun_period=self.cfg.kijun_period,
                senkou_b_period=self.cfg.senkou_b_period,
                displacement=self.cfg.displacement,
                chikou_shift=self.cfg.displacement,
            )
        )

    def compute(self, df_closed: pd.DataFrame, symbol: str = "EURUSD") -> Optional[IchimokuValues]:
        """
        Compute Ichimoku on closed-bar data and return an IchimokuValues snapshot.

        Parameters
        ----------
        df_closed : pd.DataFrame
            OHLC data with the live bar already stripped.
        symbol : str
            Used for pip size calculation.

        Returns None if there aren't enough bars.
        """
        if len(df_closed) < 78:
            logger.warning(f"Only {len(df_closed)} closed bars — need >=78 for Ichimoku")
            return None

        ichi_df = self._indicator.calculate(df_closed)

        idx = len(ichi_df) - 1
        disp = self.cfg.displacement

        # Current and previous Ichimoku line values at the bar position
        cur = ichi_df.iloc[idx]
        prev = ichi_df.iloc[idx - 1]

        # Cloud values at current bar: senkou lines were shifted +displacement,
        # so at the current bar index, senkou_a/senkou_b represent the cloud
        # that was projected displacement bars ago — this IS the visible cloud
        # at the current bar.
        cloud_top = max(_f(cur["senkou_a"]), _f(cur["senkou_b"]))
        cloud_bottom = min(_f(cur["senkou_a"]), _f(cur["senkou_b"]))
        prev_cloud_top = max(_f(prev["senkou_a"]), _f(prev["senkou_b"]))
        prev_cloud_bottom = min(_f(prev["senkou_a"]), _f(prev["senkou_b"]))

        # Future cloud: the senkou values computed at the current bar haven't
        # been shifted yet in the raw (pre-shift) computation. We need the
        # raw (unshifted) senkou_a and senkou_b at the current bar.
        # Since indicator.calculate() already shifts, the "future" cloud
        # values that will appear at idx+displacement are at ichi_df index
        # positions beyond the data. Instead, we recompute from the raw
        # midpoints.
        raw_tenkan = self._indicator._midpoint(
            self._indicator._normalise_columns(df_closed),
            self.cfg.tenkan_period
        )
        raw_kijun = self._indicator._midpoint(
            self._indicator._normalise_columns(df_closed),
            self.cfg.kijun_period
        )
        raw_senkou_b = self._indicator._midpoint(
            self._indicator._normalise_columns(df_closed),
            self.cfg.senkou_b_period
        )
        future_a = _f((raw_tenkan.iloc[idx] + raw_kijun.iloc[idx]) / 2)
        future_b = _f(raw_senkou_b.iloc[idx])

        ps = pip_size(symbol)
        thickness = abs(cloud_top - cloud_bottom) / ps

        # Close values
        df_norm = self._indicator._normalise_columns(df_closed)
        close_val = float(df_norm["close"].iloc[idx])
        prev_close_val = float(df_norm["close"].iloc[idx - 1])

        # Chikou: in the calculated df, chikou is close shifted -26.
        # At current index, chikou is NaN (shifted into the future).
        # The actual chikou value is the current close plotted at idx-26.
        # For signal purposes, chikou = current close, compared against
        # close at idx-26.
        chikou_val = close_val
        prev_chikou_val = prev_close_val

        bar_time = ichi_df.index[idx]

        return IchimokuValues(
            tenkan=_f(cur["tenkan"]),
            kijun=_f(cur["kijun"]),
            senkou_a=_f(cur["senkou_a"]),
            senkou_b=_f(cur["senkou_b"]),
            chikou=chikou_val,
            close=close_val,
            cloud_top=cloud_top,
            cloud_bottom=cloud_bottom,
            prev_tenkan=_f(prev["tenkan"]),
            prev_kijun=_f(prev["kijun"]),
            prev_senkou_a=_f(prev["senkou_a"]),
            prev_senkou_b=_f(prev["senkou_b"]),
            prev_chikou=prev_chikou_val,
            prev_close=prev_close_val,
            prev_cloud_top=prev_cloud_top,
            prev_cloud_bottom=prev_cloud_bottom,
            future_span_a=future_a,
            future_span_b=future_b,
            cloud_thickness_pips=round(thickness, 2),
            bar_time=bar_time,
        )


def is_chikou_clear(
    df: pd.DataFrame,
    direction: str,
    displacement: int = 26,
    lookback: int = 5,
) -> tuple[bool, float]:
    """
    Check if chikou span is clear of price congestion at the reference point.

    Chikou = current close, plotted at idx - displacement.
    At that reference index, check the high-low range across
    [ref_idx - lookback : ref_idx + lookback + 1].

    BUY: chikou must be above the highest high in the window.
    SELL: chikou must be below the lowest low in the window.

    Returns (is_clear, margin_pips) where margin is the distance from the
    nearest boundary. Returns (True, 0.0) if insufficient bars.
    """
    col_close = "close" if "close" in df.columns else "Close"
    col_high = "high" if "high" in df.columns else "High"
    col_low = "low" if "low" in df.columns else "Low"

    if col_close not in df.columns:
        return True, 0.0

    idx = len(df) - 1
    ref_idx = idx - displacement

    if ref_idx < lookback or ref_idx + lookback >= len(df):
        return True, 0.0

    chikou_val = float(df[col_close].iloc[idx])

    window_start = max(0, ref_idx - lookback)
    window_end = ref_idx + lookback + 1
    window = df.iloc[window_start:window_end]

    highest_high = float(window[col_high].max())
    lowest_low = float(window[col_low].min())

    if direction.upper() == "BUY":
        is_clear = chikou_val > highest_high
        margin = chikou_val - highest_high
    else:
        is_clear = chikou_val < lowest_low
        margin = lowest_low - chikou_val

    return is_clear, margin


def _f(val) -> float:
    """Convert to float, handling NaN gracefully."""
    import math
    v = float(val)
    return v if not math.isnan(v) else 0.0
