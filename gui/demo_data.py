"""
gui/demo_data.py
────────────────────────────────────────────────────────────────────────────
Synthetic OHLC candle generator.  Used as a drop-in replacement for MT5
data on Linux / demo mode.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

BASE_PRICES: dict[str, float] = {
    "EURUSD": 1.0850,
    "GBPUSD": 1.2650,
    "USDJPY": 149.50,
    "XAUUSD": 2000.00,
}

TF_HOURS: dict[str, float] = {
    "M1":  1 / 60,
    "M5":  5 / 60,
    "M15": 15 / 60,
    "M30": 0.5,
    "H1":  1.0,
    "H4":  4.0,
    "D1":  24.0,
}


def make_synthetic_candles(
    n: int = 300,
    symbol: str = "EURUSD",
    timeframe: str = "H1",
) -> pd.DataFrame:
    """
    Generate *n* synthetic OHLC candles via a random walk.

    Returns
    -------
    pd.DataFrame
        DatetimeIndex (UTC), columns: open, high, low, close
    """
    base     = BASE_PRICES.get(symbol.upper(), 1.0)
    tf_hours = TF_HOURS.get(timeframe.upper(), 1.0)

    rng     = np.random.default_rng(hash(symbol) % (2 ** 32))
    changes = rng.normal(0, base * 0.0003, n)
    closes  = base + np.cumsum(changes)
    closes  = np.maximum(closes, base * 0.4)
    opens   = np.concatenate([[base], closes[:-1]])
    spreads = np.abs(rng.normal(0, base * 0.0008, n))
    highs   = np.maximum(opens, closes) + spreads * np.abs(rng.normal(1, 0.3, n))
    lows    = np.minimum(opens, closes) - spreads * np.abs(rng.normal(1, 0.3, n))
    lows    = np.maximum(lows, base * 0.4)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    td  = timedelta(hours=tf_hours)
    timestamps = [now - td * (n - 1 - i) for i in range(n)]

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.DatetimeIndex(timestamps, name="time", tz="UTC"),
    )
