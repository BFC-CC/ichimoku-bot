"""
tests/test_data_fetcher.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for MT5DataFetcher — limited to the parts that don't require
a running MetaTrader 5 terminal (which is Windows-only).

Covers:
  - MT5Config default values
  - MT5DataFetcher raises EnvironmentError when MT5 is unavailable (Linux)
  - _utc() timezone normalisation (static method, callable without MT5)
  - _rates_to_df() DataFrame conversion (static method, callable without MT5)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytest

from core.data_fetcher import MT5Config, MT5DataFetcher, MT5_AVAILABLE


# ─────────────────────────────────────────────────────────────────────────────
#  MT5Config
# ─────────────────────────────────────────────────────────────────────────────

class TestMT5Config:

    def test_default_login_zero(self):
        assert MT5Config().login == 0

    def test_default_server_empty(self):
        assert MT5Config().server == ""

    def test_default_password_empty(self):
        assert MT5Config().password == ""

    def test_default_timeout(self):
        assert MT5Config().timeout == 60_000

    def test_default_max_retries(self):
        assert MT5Config().max_retries == 5

    def test_default_retry_delay(self):
        assert MT5Config().retry_delay == 2.0

    def test_custom_values(self):
        cfg = MT5Config(login=12345, server="ICMarkets-Demo", password="secret")
        assert cfg.login == 12345
        assert cfg.server == "ICMarkets-Demo"
        assert cfg.password == "secret"


# ─────────────────────────────────────────────────────────────────────────────
#  MT5DataFetcher – environment guard
# ─────────────────────────────────────────────────────────────────────────────

class TestMT5DataFetcherInit:

    def test_raises_environment_error_when_mt5_unavailable(self):
        """On Linux, MT5 is not installed – constructor must raise EnvironmentError."""
        if MT5_AVAILABLE:
            pytest.skip("MT5 is installed – skipping unavailability test.")
        with pytest.raises(EnvironmentError, match="MetaTrader5 package is not installed"):
            MT5DataFetcher()


# ─────────────────────────────────────────────────────────────────────────────
#  _utc() – static method (no MT5 needed)
# ─────────────────────────────────────────────────────────────────────────────

class TestUtc:

    def test_adds_utc_to_naive_datetime(self):
        dt     = datetime(2024, 1, 15, 12, 30, 0)          # no tzinfo
        result = MT5DataFetcher._utc(dt)
        assert result.tzinfo == timezone.utc
        assert result.year == 2024

    def test_preserves_utc_datetime(self):
        dt     = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        result = MT5DataFetcher._utc(dt)
        assert result == dt
        assert result.tzinfo == timezone.utc

    def test_converts_non_utc_to_utc(self):
        # UTC+2 offset
        tz_plus2 = timezone(timedelta(hours=2))
        dt       = datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz_plus2)
        result   = MT5DataFetcher._utc(dt)
        assert result.tzinfo == timezone.utc
        assert result.hour == 12   # 14:00 UTC+2 → 12:00 UTC


# ─────────────────────────────────────────────────────────────────────────────
#  _rates_to_df() – static method (no MT5 needed)
# ─────────────────────────────────────────────────────────────────────────────

class TestRatesToDf:

    def _make_rates(self, n: int):
        """Simulate the structured numpy array returned by MT5 copy_rates_*."""
        times = [int(datetime(2024, 1, 1, i, 0, tzinfo=timezone.utc).timestamp())
                 for i in range(n)]
        return pd.DataFrame({
            "time":        times,
            "open":        [1.1000 + i * 0.0001 for i in range(n)],
            "high":        [1.1005 + i * 0.0001 for i in range(n)],
            "low":         [1.0995 + i * 0.0001 for i in range(n)],
            "close":       [1.1002 + i * 0.0001 for i in range(n)],
            "tick_volume": [100] * n,
            "spread":      [2]   * n,
            "real_volume": [0]   * n,
        }).to_records(index=False)

    def test_returns_dataframe(self):
        result = MT5DataFetcher._rates_to_df(self._make_rates(5))
        assert isinstance(result, pd.DataFrame)

    def test_index_is_datetime_utc(self):
        result = MT5DataFetcher._rates_to_df(self._make_rates(5))
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.tz == timezone.utc

    def test_columns_are_ohlc_only(self):
        result = MT5DataFetcher._rates_to_df(self._make_rates(5))
        assert set(result.columns) == {"open", "high", "low", "close"}

    def test_correct_row_count(self):
        result = MT5DataFetcher._rates_to_df(self._make_rates(10))
        assert len(result) == 10

    def test_values_are_float(self):
        result = MT5DataFetcher._rates_to_df(self._make_rates(3))
        assert result["close"].dtype == float
