"""
gui/live_feed.py
────────────────────────────────────────────────────────────────────────────
Live OHLC data fetcher.

Priority:
  1. MetaTrader5 (native on Windows, or via mt5linux Wine bridge on Linux)
  2. yfinance fallback (~15 min delayed, no API key)
"""

from __future__ import annotations

import pandas as pd
from core.data_fetcher import MT5_AVAILABLE, MT5_BACKEND

# Yahoo Finance ticker mapping
SYMBOL_MAP: dict[str, str] = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "XAUUSD": "GC=F",
}

# yfinance interval / period for each of our timeframe strings
TF_MAP: dict[str, dict] = {
    "M15": {"interval": "15m", "period": "5d",  "resample": None},
    "M30": {"interval": "30m", "period": "5d",  "resample": None},
    "H1":  {"interval": "1h",  "period": "7d",  "resample": None},
    "H4":  {"interval": "1h",  "period": "60d", "resample": "4h"},
    "D1":  {"interval": "1d",  "period": "2y",  "resample": None},
}


def get_data_source() -> str:
    """Return a human-readable label for the active data source."""
    if MT5_AVAILABLE:
        return f"MetaTrader5 ({MT5_BACKEND})"
    return "Yahoo Finance (delayed)"


def fetch_mt5_candles(symbol: str, timeframe: str = "H1", count: int = 300) -> pd.DataFrame:
    """
    Fetch candles directly from the running MT5 terminal.
    Works with native MT5 (Windows) or mt5linux Wine bridge (Linux).
    """
    from core.data_fetcher import MT5Config, MT5DataFetcher
    fetcher = MT5DataFetcher(MT5Config())
    fetcher.connect()
    try:
        return fetcher.fetch_historical(symbol, timeframe, count=count)
    finally:
        fetcher.disconnect()


def fetch_live_candles(
    symbol: str,
    timeframe: str = "H1",
    count: int = 300,
) -> pd.DataFrame:
    """
    Download OHLC candles for *symbol* at *timeframe* granularity.

    Uses MT5 when available, otherwise falls back to yfinance.

    Returns
    -------
    pd.DataFrame
        DatetimeIndex (UTC), columns: open, high, low, close
        Tail-trimmed to *count* rows.

    Raises
    ------
    RuntimeError if no data source can provide data.
    """
    if MT5_AVAILABLE:
        return fetch_mt5_candles(symbol, timeframe, count)

    import yfinance as yf  # lazy import so app boots without it

    ticker = SYMBOL_MAP.get(symbol.upper(), symbol.upper() + "=X")
    tf_cfg = TF_MAP.get(timeframe.upper(), TF_MAP["H1"])

    df = yf.download(
        ticker,
        interval=tf_cfg["interval"],
        period=tf_cfg["period"],
        progress=False,
        auto_adjust=True,
    )

    if df.empty:
        raise RuntimeError(f"yfinance returned no data for {symbol} ({ticker})")

    # Flatten MultiIndex columns (yfinance >= 0.2.50 wraps single-ticker too)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]

    df = df[["open", "high", "low", "close"]].copy().dropna()

    # Resample 1h → 4h when H4 is requested
    if tf_cfg["resample"]:
        df = df.resample(tf_cfg["resample"]).agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        ).dropna()

    # Normalise timezone to UTC
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df.index.name = "time"
    return df.tail(count)
