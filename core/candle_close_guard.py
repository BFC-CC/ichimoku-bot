"""
core/candle_close_guard.py
─────────────────────────────────────────────────────────────────────────────
Strips the live (forming) bar from candle data and tracks which bars have
already been processed per symbol to prevent duplicate signal evaluation.

Usage
-----
    guard = CandleCloseGuard()
    df_closed, is_new = guard.get_closed_bars(df, "EURUSD")
    if is_new:
        # evaluate signal on df_closed.iloc[-1]
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from loguru import logger


class CandleCloseGuard:
    """Ensure signals only fire on confirmed closed bars, never the live bar."""

    def __init__(self) -> None:
        self._last_processed: dict[str, pd.Timestamp] = {}

    def get_closed_bars(
        self, df: pd.DataFrame, symbol: str
    ) -> tuple[Optional[pd.DataFrame], bool]:
        """
        Strip the live bar and check if the last closed bar is new.

        Returns
        -------
        (df_closed, is_new_bar)
            df_closed has the live bar removed (iloc[:-1]).
            is_new_bar is False if this bar was already processed — skip cycle.
            Returns (None, False) if df has fewer than 2 rows.
        """
        if len(df) < 2:
            logger.warning(f"{symbol}: fewer than 2 bars, cannot strip live bar")
            return None, False

        df_closed = df.iloc[:-1].copy()
        last_bar_time = df_closed.index[-1] if isinstance(df_closed.index, pd.DatetimeIndex) else df_closed.iloc[-1].get("time")

        if self._last_processed.get(symbol) == last_bar_time:
            return df_closed, False

        self._last_processed[symbol] = last_bar_time
        logger.debug(f"{symbol}: new closed bar at {last_bar_time}")
        return df_closed, True

    def reset(self, symbol: Optional[str] = None) -> None:
        """Clear tracking state. If symbol given, clear only that symbol."""
        if symbol:
            self._last_processed.pop(symbol, None)
        else:
            self._last_processed.clear()
