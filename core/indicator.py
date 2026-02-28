"""
core/indicator.py
─────────────────────────────────────────────────────────────────────────────
Pure-pandas Ichimoku Kinko Hyo calculator.

All five lines are computed from a standard OHLC DataFrame and returned
as a new DataFrame with the same index.  Senkou A/B are already shifted
forward (displacement periods), and Chikou is shifted back – matching
exactly what you see on an MT5 chart.

Usage
-----
    from core.indicator import IchimokuIndicator
    ichi = IchimokuIndicator()
    result = ichi.calculate(candles_df)
    latest = ichi.latest_values(candles_df)   # dict of current + prev values
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
from loguru import logger


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IchimokuConfig:
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    displacement: int = 26    # Senkou A/B shift forward
    chikou_shift: int = 26    # Chikou shift back (stored as negative index offset)


# ─────────────────────────────────────────────────────────────────────────────
#  Main calculator
# ─────────────────────────────────────────────────────────────────────────────

class IchimokuIndicator:
    """
    Computes Ichimoku Kinko Hyo indicator lines.

    Parameters
    ----------
    config : IchimokuConfig, optional
        Override default periods.  Defaults to standard 9/26/52.
    """

    def __init__(self, config: Optional[IchimokuConfig] = None):
        self.cfg = config or IchimokuConfig()

    # ── public API ────────────────────────────────────────────────────────────

    def calculate(self, candles: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all Ichimoku lines for the full candle history.

        Parameters
        ----------
        candles : pd.DataFrame
            Must contain columns: open, high, low, close (case-insensitive).
            Index should be datetime.

        Returns
        -------
        pd.DataFrame
            Same index as *candles*, with columns:
            tenkan, kijun, senkou_a, senkou_b, chikou
        """
        df = self._normalise_columns(candles)
        self._validate(df)

        tenkan  = self._midpoint(df, self.cfg.tenkan_period)
        kijun   = self._midpoint(df, self.cfg.kijun_period)
        senkou_b = self._midpoint(df, self.cfg.senkou_b_period)

        senkou_a = ((tenkan + kijun) / 2).shift(self.cfg.displacement)
        senkou_b = senkou_b.shift(self.cfg.displacement)
        chikou   = df["close"].shift(-self.cfg.chikou_shift)

        result = pd.DataFrame({
            "tenkan":   tenkan,
            "kijun":    kijun,
            "senkou_a": senkou_a,
            "senkou_b": senkou_b,
            "chikou":   chikou,
        }, index=df.index)

        logger.debug(
            f"Ichimoku calculated over {len(df)} candles – "
            f"valid rows: {result.dropna().shape[0]}"
        )
        return result

    def latest_values(self, candles: pd.DataFrame) -> Dict[str, float]:
        """
        Return a flat dict with the *current* and *previous* indicator values,
        which is exactly what SignalDetector needs for crossover detection.

        Keys
        ----
        tenkan, kijun, senkou_a, senkou_b, chikou         (current candle)
        prev_tenkan, prev_kijun, prev_senkou_a,
        prev_senkou_b, prev_chikou                        (one candle earlier)
        close                                             (latest close price)
        prev_close                                        (previous close price)
        cloud_top, cloud_bottom                           (max/min of senkou_a/b)
        prev_cloud_top, prev_cloud_bottom

        Returns NaN for any value that cannot be computed (not enough history).
        """
        ichi = self.calculate(candles)

        # We need at least two rows of fully-computed Ichimoku values.
        # Senkou lines are shifted forward, so the last valid row where all
        # non-chikou values exist is at index [-1].  Chikou of the current
        # candle points 26 bars back, which is always available.
        if len(ichi) < 2:
            logger.warning("Not enough candles to produce latest_values.")
            return self._nan_dict()

        cur  = ichi.iloc[-1]
        prev = ichi.iloc[-2]

        df_norm = self._normalise_columns(candles)

        def v(series_row, col):
            val = series_row[col]
            return float(val) if not (isinstance(val, float) and np.isnan(val)) else float("nan")

        return {
            # current
            "tenkan":       v(cur,  "tenkan"),
            "kijun":        v(cur,  "kijun"),
            "senkou_a":     v(cur,  "senkou_a"),
            "senkou_b":     v(cur,  "senkou_b"),
            "chikou":       v(cur,  "chikou"),
            "close":        float(df_norm["close"].iloc[-1]),
            "cloud_top":    max(v(cur, "senkou_a"), v(cur, "senkou_b")),
            "cloud_bottom": min(v(cur, "senkou_a"), v(cur, "senkou_b")),
            # previous
            "prev_tenkan":       v(prev, "tenkan"),
            "prev_kijun":        v(prev, "kijun"),
            "prev_senkou_a":     v(prev, "senkou_a"),
            "prev_senkou_b":     v(prev, "senkou_b"),
            "prev_chikou":       v(prev, "chikou"),
            "prev_close":        float(df_norm["close"].iloc[-2]),
            "prev_cloud_top":    max(v(prev, "senkou_a"), v(prev, "senkou_b")),
            "prev_cloud_bottom": min(v(prev, "senkou_a"), v(prev, "senkou_b")),
        }

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _midpoint(df: pd.DataFrame, period: int) -> pd.Series:
        """(highest_high + lowest_low) / 2  over *period* candles."""
        high = df["high"].rolling(window=period).max()
        low  = df["low"].rolling(window=period).min()
        return (high + low) / 2

    @staticmethod
    def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Lowercase all column names so we accept any capitalisation."""
        out = df.copy()
        out.columns = [c.lower() for c in out.columns]
        return out

    @staticmethod
    def _validate(df: pd.DataFrame) -> None:
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Candle DataFrame is missing columns: {missing}")
        if len(df) < 52:
            logger.warning(
                f"Only {len(df)} candles supplied – need ≥52 for Senkou B "
                f"(plus 26 for displacement = 78 total for full signal accuracy)."
            )

    @staticmethod
    def _nan_dict() -> Dict[str, float]:
        keys = [
            "tenkan", "kijun", "senkou_a", "senkou_b", "chikou",
            "close", "cloud_top", "cloud_bottom",
            "prev_tenkan", "prev_kijun", "prev_senkou_a", "prev_senkou_b",
            "prev_chikou", "prev_close", "prev_cloud_top", "prev_cloud_bottom",
        ]
        return {k: float("nan") for k in keys}
