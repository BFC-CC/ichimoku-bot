"""
core/trend_filter.py
─────────────────────────────────────────────────────────────────────────────
D1 cloud direction confirmation filter.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from loguru import logger

from core.ichimoku_calculator import IchimokuCalculator, IchimokuValues


class TrendFilter:
    """Check D1 timeframe cloud direction for trade confirmation."""

    def __init__(self, calculator: IchimokuCalculator) -> None:
        self.calc = calculator

    def check_d1_trend(
        self, df_d1: pd.DataFrame, symbol: str
    ) -> tuple[Optional[str], str]:
        """
        Check D1 trend direction.

        Returns (direction, reason):
            direction: 'BUY', 'SELL', or None if unclear
            reason: human-readable explanation
        """
        if len(df_d1) < 79:
            return None, "Not enough D1 bars for trend filter"

        # Strip live bar
        df_closed = df_d1.iloc[:-1]
        ichi = self.calc.compute(df_closed, symbol)
        if ichi is None:
            return None, "Could not compute D1 Ichimoku"

        # Price above cloud = bullish D1 trend
        if ichi.close > ichi.cloud_top:
            return "BUY", f"D1 bullish: price {ichi.close:.5f} > cloud {ichi.cloud_top:.5f}"

        if ichi.close < ichi.cloud_bottom:
            return "SELL", f"D1 bearish: price {ichi.close:.5f} < cloud {ichi.cloud_bottom:.5f}"

        return None, f"D1 inside cloud: price {ichi.close:.5f}"

    def confirms_direction(
        self, df_d1: pd.DataFrame, symbol: str, direction: str
    ) -> tuple[bool, str]:
        """Check if D1 trend confirms the intended trade direction."""
        d1_dir, reason = self.check_d1_trend(df_d1, symbol)
        if d1_dir is None:
            return False, reason
        if d1_dir == direction.upper():
            return True, reason
        return False, f"D1 trend ({d1_dir}) conflicts with {direction}"
