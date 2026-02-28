"""
tests/test_candle_buffer.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for CandleBuffer.

Covers:
  - Constructor validation (max_size >= min_candles)
  - seed() normalisation, trimming, size tracking
  - append() deduplication, max_size trimming, RuntimeError before seed
  - is_ready threshold
  - size and latest_time properties
  - _prepare() column normalisation, DatetimeIndex acceptance,
    missing-column error, missing time-index error
"""

from __future__ import annotations

import pytest
import pandas as pd
from datetime import timezone

from core.candle_buffer import CandleBuffer


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_ohlc(n: int, start: float = 1.1000, step: float = 0.0001) -> pd.DataFrame:
    """Return a DatetimeIndex OHLC DataFrame with n rows."""
    times  = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    closes = [round(start + i * step, 5) for i in range(n)]
    return pd.DataFrame(
        {
            "open":  closes,
            "high":  [c + 0.0005 for c in closes],
            "low":   [c - 0.0005 for c in closes],
            "close": closes,
        },
        index=pd.DatetimeIndex(times, name="time"),
    )


def make_ohlc_with_time_col(n: int) -> pd.DataFrame:
    """Return a DataFrame with a 'time' column (not index)."""
    df = make_ohlc(n).reset_index()
    return df


# ─────────────────────────────────────────────────────────────────────────────
#  Constructor
# ─────────────────────────────────────────────────────────────────────────────

class TestCandleBufferInit:

    def test_valid_construction(self):
        buf = CandleBuffer(max_size=300, min_candles=78)
        assert buf.size == 0
        assert buf.is_ready is False

    def test_max_size_equals_min_candles(self):
        buf = CandleBuffer(max_size=78, min_candles=78)
        assert buf.size == 0

    def test_raises_when_max_size_less_than_min_candles(self):
        with pytest.raises(ValueError, match="max_size"):
            CandleBuffer(max_size=50, min_candles=78)

    def test_default_min_candles(self):
        buf = CandleBuffer(max_size=300)
        assert buf._min == CandleBuffer.DEFAULT_MIN


# ─────────────────────────────────────────────────────────────────────────────
#  seed()
# ─────────────────────────────────────────────────────────────────────────────

class TestSeed:

    def test_seed_sets_size(self):
        buf = CandleBuffer(max_size=300)
        buf.seed(make_ohlc(100))
        assert buf.size == 100

    def test_seed_trims_to_max_size(self):
        buf = CandleBuffer(max_size=50, min_candles=10)
        buf.seed(make_ohlc(200))
        assert buf.size == 50

    def test_seed_keeps_most_recent_candles(self):
        buf = CandleBuffer(max_size=50, min_candles=10)
        df  = make_ohlc(200)
        buf.seed(df)
        assert buf.latest_time == df.index[-1]

    def test_seed_replaces_existing_data(self):
        buf = CandleBuffer(max_size=300)
        buf.seed(make_ohlc(50))
        buf.seed(make_ohlc(80, start=1.2000))
        assert buf.size == 80

    def test_seed_accepts_time_column(self):
        buf = CandleBuffer(max_size=300)
        buf.seed(make_ohlc_with_time_col(100))
        assert buf.size == 100

    def test_seed_normalises_uppercase_columns(self):
        buf = CandleBuffer(max_size=300)
        df  = make_ohlc(100)
        df.columns = [c.upper() for c in df.columns]
        df.index.name = "time"
        buf.seed(df)
        assert buf.size == 100


# ─────────────────────────────────────────────────────────────────────────────
#  append()
# ─────────────────────────────────────────────────────────────────────────────

class TestAppend:

    def test_append_raises_before_seed(self):
        buf = CandleBuffer(max_size=300)
        with pytest.raises(RuntimeError, match="seed"):
            buf.append(make_ohlc(1))

    def test_append_increases_size(self):
        buf = CandleBuffer(max_size=300)
        df  = make_ohlc(100)
        buf.seed(df)
        # Candles must start after the last seeded timestamp to avoid dedup
        new_times = pd.date_range(df.index[-1] + pd.Timedelta(hours=1),
                                  periods=5, freq="h", tz="UTC")
        new = make_ohlc(5, start=1.2000)
        new.index = new_times
        new.index.name = "time"
        buf.append(new)
        assert buf.size == 105

    def test_append_ignores_duplicate_timestamps(self):
        buf = CandleBuffer(max_size=300)
        df  = make_ohlc(100)
        buf.seed(df)
        # Append the same slice again – should be ignored
        buf.append(df.tail(10))
        assert buf.size == 100

    def test_append_trims_to_max_size(self):
        buf = CandleBuffer(max_size=110, min_candles=10)
        df  = make_ohlc(100)
        buf.seed(df)
        new_times = pd.date_range(df.index[-1] + pd.Timedelta(hours=1),
                                  periods=20, freq="h", tz="UTC")
        new = make_ohlc(20, start=1.5000)
        new.index = new_times
        new.index.name = "time"
        buf.append(new)
        assert buf.size == 110

    def test_append_updates_latest_time(self):
        buf = CandleBuffer(max_size=300)
        buf.seed(make_ohlc(100))
        new = make_ohlc(3, start=1.5000)   # future timestamps
        new.index = pd.date_range("2030-01-01", periods=3, freq="h", tz="UTC")
        new.index.name = "time"
        buf.append(new)
        assert buf.latest_time == new.index[-1]


# ─────────────────────────────────────────────────────────────────────────────
#  is_ready / size / latest_time
# ─────────────────────────────────────────────────────────────────────────────

class TestProperties:

    def test_is_ready_false_below_min(self):
        buf = CandleBuffer(max_size=300, min_candles=78)
        buf.seed(make_ohlc(50))
        assert buf.is_ready is False

    def test_is_ready_true_at_min(self):
        buf = CandleBuffer(max_size=300, min_candles=78)
        buf.seed(make_ohlc(78))
        assert buf.is_ready is True

    def test_is_ready_false_before_seed(self):
        buf = CandleBuffer(max_size=300)
        assert buf.is_ready is False

    def test_size_zero_before_seed(self):
        assert CandleBuffer(max_size=300).size == 0

    def test_latest_time_none_before_seed(self):
        assert CandleBuffer(max_size=300).latest_time is None

    def test_latest_time_after_seed(self):
        buf = CandleBuffer(max_size=300)
        df  = make_ohlc(100)
        buf.seed(df)
        assert buf.latest_time == df.index[-1]

    def test_data_raises_before_seed(self):
        buf = CandleBuffer(max_size=300)
        with pytest.raises(RuntimeError):
            _ = buf.data


# ─────────────────────────────────────────────────────────────────────────────
#  _prepare() edge-cases
# ─────────────────────────────────────────────────────────────────────────────

class TestPrepare:

    def test_raises_on_missing_ohlc_columns(self):
        df = pd.DataFrame({"open": [1.0], "high": [1.1]},
                          index=pd.DatetimeIndex(["2024-01-01"], tz="UTC"))
        with pytest.raises(ValueError, match="missing"):
            CandleBuffer._prepare(df)

    def test_raises_when_no_time_column_and_no_datetimeindex(self):
        df = pd.DataFrame({"open": [1.0], "high": [1.1],
                           "low": [0.9], "close": [1.0]})
        with pytest.raises(ValueError, match="time"):
            CandleBuffer._prepare(df)

    def test_drops_nan_rows(self):
        df = make_ohlc(5)
        df.iloc[2, df.columns.get_loc("close")] = float("nan")
        result = CandleBuffer._prepare(df)
        assert len(result) == 4

    def test_sorts_by_time(self):
        df = make_ohlc(5)
        shuffled = df.sample(frac=1, random_state=42)
        result = CandleBuffer._prepare(shuffled)
        assert list(result.index) == sorted(result.index)
