"""
core/candle_buffer.py
─────────────────────────────────────────────────────────────────────────────
Maintains a rolling in-memory window of OHLC candles for one pair/timeframe.

The buffer is pre-seeded with historical data and updated with one new
candle on every loop tick.  It guarantees the DataFrame passed to the
indicator calculator always has at least `min_candles` rows.

Minimum candle requirements for Ichimoku (default settings):
  Senkou B  : 52 candles of history
  Displacement : +26 shift forward
  Warmup total : 52 + 26 = 78 candles minimum
  Recommended  : 200+ for stable rolling windows

Usage
-----
    buf = CandleBuffer(max_size=300)
    buf.seed(historical_df)
    buf.append(new_candle_df)
    df = buf.data    # current rolling window as DataFrame
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from loguru import logger


class CandleBuffer:
    """
    A fixed-size rolling buffer of OHLC candle data.

    Parameters
    ----------
    max_size : int
        Maximum number of candles to keep in memory.
        Older candles are dropped as new ones arrive.
    min_candles : int
        Minimum candles needed before indicators can be safely computed.
        Defaults to 78 (52 + 26 displacement).
    """

    # Minimum candles for full Ichimoku with default 9/26/52 settings
    DEFAULT_MIN = 78

    def __init__(self, max_size: int = 300, min_candles: int = DEFAULT_MIN):
        if max_size < min_candles:
            raise ValueError(
                f"max_size ({max_size}) must be >= min_candles ({min_candles})"
            )
        self._max_size  = max_size
        self._min       = min_candles
        self._data: Optional[pd.DataFrame] = None

    # ── public API ────────────────────────────────────────────────────────────

    def seed(self, df: pd.DataFrame) -> None:
        """
        Load initial historical data.  Replaces any existing buffer content.
        The DataFrame must contain columns: time, open, high, low, close.
        'time' can be the index or a column; it will be set as the index.
        """
        df = self._prepare(df)
        self._data = df.tail(self._max_size).copy()
        logger.info(
            f"Buffer seeded with {len(self._data)} candles "
            f"(max_size={self._max_size}, min_candles={self._min})"
        )

    def append(self, df: pd.DataFrame) -> None:
        """
        Add one or more new candles to the buffer, then trim to max_size.
        Duplicate candle timestamps are silently ignored.
        """
        if self._data is None:
            raise RuntimeError("Buffer has not been seeded.  Call seed() first.")

        new = self._prepare(df)

        # Drop rows whose timestamp already exists in the buffer
        existing_idx = self._data.index
        new = new[~new.index.isin(existing_idx)]

        if new.empty:
            logger.debug("append(): all candles already in buffer, nothing added.")
            return

        self._data = pd.concat([self._data, new]).tail(self._max_size)
        logger.debug(f"Buffer updated: {len(self._data)} candles in window.")

    @property
    def data(self) -> pd.DataFrame:
        """Return the current candle window as a DataFrame."""
        if self._data is None:
            raise RuntimeError("Buffer has not been seeded.")
        return self._data

    @property
    def is_ready(self) -> bool:
        """True if the buffer has enough candles to compute indicators."""
        if self._data is None:
            return False
        return len(self._data) >= self._min

    @property
    def size(self) -> int:
        """Current number of candles in the buffer."""
        return 0 if self._data is None else len(self._data)

    @property
    def latest_time(self) -> Optional[pd.Timestamp]:
        """Timestamp of the most recent candle, or None if buffer is empty."""
        if self._data is None or self._data.empty:
            return None
        return self._data.index[-1]

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _prepare(df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalise a candle DataFrame:
        - Lowercase column names
        - Ensure 'time' is the index (datetime)
        - Keep only open, high, low, close columns
        - Sort by time ascending
        - Drop rows with NaN in OHLC columns
        """
        out = df.copy()
        out.columns = [c.lower() for c in out.columns]

        # Set time as index if it's a column
        if "time" in out.columns:
            out["time"] = pd.to_datetime(out["time"], utc=True)
            out = out.set_index("time")
        elif not isinstance(out.index, pd.DatetimeIndex):
            raise ValueError(
                "DataFrame must have a 'time' column or a DatetimeIndex."
            )

        required = {"open", "high", "low", "close"}
        missing = required - set(out.columns)
        if missing:
            raise ValueError(f"Candle DataFrame missing columns: {missing}")

        out = out[["open", "high", "low", "close"]].copy()
        out = out.dropna()
        out = out.sort_index()
        return out
