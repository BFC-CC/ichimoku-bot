"""
core/sltp_builder.py
─────────────────────────────────────────────────────────────────────────────
Calculates Stop Loss and Take Profit prices based on configured methods.

SL methods: kijun, atr, cloud_edge, fixed_pips
TP methods: ratio, next_cloud, fixed_pips
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from core.config_loader import RiskManagementConfig
from core.ichimoku_calculator import IchimokuValues, pip_size


@dataclass
class SLTPResult:
    """Result of SL/TP calculation."""
    sl: float
    tp: float
    sl_pips: float
    tp_pips: float
    sl_method: str
    tp_method: str


class SLTPBuilder:
    """Build stop-loss and take-profit levels."""

    MIN_SL_PIPS = 2.0

    def __init__(self, config: RiskManagementConfig) -> None:
        self.cfg = config

    def build(
        self,
        direction: str,
        entry: float,
        symbol: str,
        ichi: IchimokuValues,
        df_closed: Optional[pd.DataFrame] = None,
    ) -> Optional[SLTPResult]:
        """
        Calculate SL and TP for a trade.

        Returns None if SL would be less than MIN_SL_PIPS from entry.
        """
        ps = pip_size(symbol)
        sl_cfg = self.cfg.stop_loss
        tp_cfg = self.cfg.take_profit
        is_buy = direction.upper() == "BUY"

        # ── Stop Loss ─────────────────────────────────────────────────────
        sl = self._calc_sl(entry, is_buy, ichi, ps, df_closed)
        sl_dist = abs(entry - sl)
        sl_pips = sl_dist / ps

        if sl_pips < self.MIN_SL_PIPS:
            logger.warning(
                f"SL too close: {sl_pips:.1f} pips < {self.MIN_SL_PIPS} minimum. "
                f"Trade rejected."
            )
            return None

        # ── Take Profit ───────────────────────────────────────────────────
        tp = self._calc_tp(entry, sl_dist, is_buy, ichi, ps)
        tp_pips = abs(entry - tp) / ps

        return SLTPResult(
            sl=round(sl, 5),
            tp=round(tp, 5),
            sl_pips=round(sl_pips, 1),
            tp_pips=round(tp_pips, 1),
            sl_method=sl_cfg.method,
            tp_method=tp_cfg.method,
        )

    def _calc_sl(
        self,
        entry: float,
        is_buy: bool,
        ichi: IchimokuValues,
        ps: float,
        df_closed: Optional[pd.DataFrame],
    ) -> float:
        """Calculate stop loss price."""
        method = self.cfg.stop_loss.method
        buffer = self.cfg.stop_loss.buffer_pips * ps

        if method == "kijun":
            if is_buy:
                return ichi.kijun - buffer
            return ichi.kijun + buffer

        if method == "cloud_edge":
            if is_buy:
                return ichi.cloud_bottom - buffer
            return ichi.cloud_top + buffer

        if method == "fixed_pips":
            dist = self.cfg.stop_loss.fixed_pips * ps
            if is_buy:
                return entry - dist
            return entry + dist

        if method == "atr":
            atr = self._calc_atr(df_closed, self.cfg.stop_loss.atr_period)
            dist = atr * self.cfg.stop_loss.atr_multiplier
            if is_buy:
                return entry - dist
            return entry + dist

        # Fallback to kijun
        logger.warning(f"Unknown SL method '{method}', falling back to kijun")
        if is_buy:
            return ichi.kijun - buffer
        return ichi.kijun + buffer

    def _calc_tp(
        self,
        entry: float,
        sl_dist: float,
        is_buy: bool,
        ichi: IchimokuValues,
        ps: float,
    ) -> float:
        """Calculate take profit price."""
        method = self.cfg.take_profit.method

        if method == "ratio":
            tp_dist = sl_dist * self.cfg.take_profit.rr_ratio
            if is_buy:
                return entry + tp_dist
            return entry - tp_dist

        if method == "fixed_pips":
            dist = self.cfg.take_profit.fixed_pips * ps
            if is_buy:
                return entry + dist
            return entry - dist

        if method == "next_cloud":
            if is_buy:
                tp = ichi.cloud_top + abs(ichi.cloud_top - ichi.cloud_bottom)
            else:
                tp = ichi.cloud_bottom - abs(ichi.cloud_top - ichi.cloud_bottom)
            # Check R:R, fallback to ratio if below 1.0
            tp_dist = abs(entry - tp)
            if sl_dist > 0 and tp_dist / sl_dist < 1.0:
                tp_dist = sl_dist * self.cfg.take_profit.rr_ratio
                if is_buy:
                    return entry + tp_dist
                return entry - tp_dist
            return tp

        # Fallback to ratio
        tp_dist = sl_dist * self.cfg.take_profit.rr_ratio
        if is_buy:
            return entry + tp_dist
        return entry - tp_dist

    @staticmethod
    def _calc_atr(df: Optional[pd.DataFrame], period: int) -> float:
        """Calculate ATR. Returns a default if df is None."""
        if df is None or len(df) < period + 1:
            return 0.0020  # fallback ~20 pips

        df_norm = df.copy()
        df_norm.columns = [c.lower() for c in df_norm.columns]
        high = df_norm["high"]
        low = df_norm["low"]
        close = df_norm["close"]

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        return float(tr.rolling(period).mean().iloc[-1])
