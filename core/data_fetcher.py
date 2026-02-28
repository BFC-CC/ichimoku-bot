"""
core/data_fetcher.py
─────────────────────────────────────────────────────────────────────────────
MetaTrader 5 data layer.

Wraps the `MetaTrader5` Python package and provides a clean interface for
fetching historical and live candle data.  Handles connection lifecycle,
MT5 error codes, and timezone alignment (all timestamps returned in UTC).

Requires MetaTrader 5 terminal to be installed and running on the same
Windows machine (MT5 Python API is Windows-only).

Supported timeframes (MT5 granularity strings → MT5 constants):
    M1, M5, M15, M30, H1, H4, D1, W1, MN1

Usage
-----
    from core.data_fetcher import MT5DataFetcher, MT5Config
    fetcher = MT5DataFetcher(MT5Config())
    fetcher.connect()
    df = fetcher.fetch_historical("EURUSD", "H1", count=300)
    latest = fetcher.fetch_latest("EURUSD", "H1", count=1)
    fetcher.disconnect()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from loguru import logger

# MT5 is imported lazily so the rest of the codebase can be tested without
# a running MT5 terminal.
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None          # type: ignore
    MT5_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
#  Timeframe mapping
# ─────────────────────────────────────────────────────────────────────────────

_TF_MAP: dict[str, int] = {}   # populated after MT5 import check


def _build_tf_map() -> None:
    global _TF_MAP
    if not MT5_AVAILABLE:
        return
    _TF_MAP = {
        "M1":  mt5.TIMEFRAME_M1,
        "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,
        "D1":  mt5.TIMEFRAME_D1,
        "W1":  mt5.TIMEFRAME_W1,
        "MN1": mt5.TIMEFRAME_MN1,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MT5Config:
    login:    int = 0       # 0 = use currently logged-in session
    server:   str = ""      # "" = use currently logged-in session
    password: str = ""      # "" = use currently logged-in session
    timeout:  int = 60_000  # milliseconds
    max_retries: int = 5
    retry_delay: float = 2.0   # seconds (doubles on each retry)


# ─────────────────────────────────────────────────────────────────────────────
#  MT5 Data Fetcher
# ─────────────────────────────────────────────────────────────────────────────

class MT5DataFetcher:
    """
    Fetches OHLC candle data from a running MetaTrader 5 terminal.

    All returned DataFrames have:
        index  : DatetimeIndex (UTC)
        columns: open, high, low, close  (float64)
    """

    def __init__(self, config: Optional[MT5Config] = None):
        if not MT5_AVAILABLE:
            raise EnvironmentError(
                "MetaTrader5 package is not installed.  "
                "Run: pip install MetaTrader5"
            )
        self.cfg = config or MT5Config()
        self._connected = False
        _build_tf_map()

    # ── connection lifecycle ──────────────────────────────────────────────────

    def connect(self) -> None:
        """Open connection to the MT5 terminal.  Call once at startup."""
        kwargs: dict = {"timeout": self.cfg.timeout}
        if self.cfg.login:
            kwargs["login"]    = self.cfg.login
            kwargs["server"]   = self.cfg.server
            kwargs["password"] = self.cfg.password

        if not mt5.initialize(**kwargs):
            err = mt5.last_error()
            raise ConnectionError(f"MT5 initialize() failed: {err}")

        info = mt5.terminal_info()
        logger.info(
            f"MT5 connected | build={info.build} | "
            f"company={info.company} | connected={info.connected}"
        )
        self._connected = True

    def disconnect(self) -> None:
        """Close the MT5 connection."""
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 disconnected.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ── data methods ─────────────────────────────────────────────────────────

    def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        count: int = 300,
    ) -> pd.DataFrame:
        """
        Fetch the last *count* completed candles for *symbol* on *timeframe*.

        Parameters
        ----------
        symbol    : e.g. 'EURUSD'
        timeframe : e.g. 'H1'  (see _TF_MAP for valid values)
        count     : number of candles to fetch

        Returns
        -------
        pd.DataFrame  (index=UTC datetime, columns=open,high,low,close)
        """
        self._ensure_connected()
        tf_const = self._resolve_timeframe(timeframe)

        rates = self._retry(
            lambda: mt5.copy_rates_from_pos(symbol, tf_const, 0, count)
        )
        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            raise RuntimeError(
                f"fetch_historical({symbol}, {timeframe}, {count}) failed: {err}"
            )

        df = self._rates_to_df(rates)
        logger.info(
            f"Fetched {len(df)} historical candles | "
            f"{symbol} {timeframe} | "
            f"{df.index[0]} → {df.index[-1]}"
        )
        return df

    def fetch_from_date(
        self,
        symbol: str,
        timeframe: str,
        from_date: datetime,
        to_date: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Fetch candles between *from_date* and *to_date* (inclusive).
        Used by the backtesting engine.

        Parameters
        ----------
        from_date : UTC datetime
        to_date   : UTC datetime (defaults to now)
        """
        self._ensure_connected()
        tf_const = self._resolve_timeframe(timeframe)

        if to_date is None:
            to_date = datetime.now(timezone.utc)

        # Ensure timezone-aware
        from_date = self._utc(from_date)
        to_date   = self._utc(to_date)

        rates = self._retry(
            lambda: mt5.copy_rates_range(symbol, tf_const, from_date, to_date)
        )
        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            raise RuntimeError(
                f"fetch_from_date({symbol}, {timeframe}) failed: {err}"
            )

        df = self._rates_to_df(rates)
        logger.info(
            f"Fetched {len(df)} candles (date range) | "
            f"{symbol} {timeframe} | {from_date.date()} → {to_date.date()}"
        )
        return df

    def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 1,
    ) -> pd.DataFrame:
        """
        Fetch the most recent *count* completed candles.
        Identical to fetch_historical but semantically for live updates.
        """
        return self.fetch_historical(symbol, timeframe, count=count)

    # ── private helpers ───────────────────────────────────────────────────────

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError(
                "Not connected to MT5.  Call connect() first."
            )

    def _resolve_timeframe(self, tf: str) -> int:
        tf = tf.upper()
        if tf not in _TF_MAP:
            raise ValueError(
                f"Unknown timeframe '{tf}'. "
                f"Valid options: {list(_TF_MAP.keys())}"
            )
        return _TF_MAP[tf]

    def _retry(self, fn, retries: Optional[int] = None):
        """Call *fn* up to max_retries times with exponential backoff."""
        max_tries = retries if retries is not None else self.cfg.max_retries
        delay = self.cfg.retry_delay
        last_err = None
        for attempt in range(1, max_tries + 1):
            try:
                result = fn()
                if result is not None and len(result) > 0:
                    return result
                last_err = mt5.last_error()
                logger.warning(
                    f"MT5 call returned empty/None (attempt {attempt}/{max_tries}). "
                    f"Error: {last_err}"
                )
            except Exception as exc:
                last_err = exc
                logger.warning(f"MT5 call raised exception (attempt {attempt}): {exc}")

            if attempt < max_tries:
                time.sleep(delay)
                delay *= 2   # exponential backoff

        logger.error(f"All {max_tries} MT5 retry attempts failed. Last error: {last_err}")
        return None

    @staticmethod
    def _rates_to_df(rates) -> pd.DataFrame:
        """Convert MT5 rates array (structured numpy array) to a clean DataFrame."""
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        # MT5 returns: open, high, low, close, tick_volume, spread, real_volume
        df = df[["open", "high", "low", "close"]].copy()
        df = df.astype(float)
        return df

    @staticmethod
    def _utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
