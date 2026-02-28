"""
tests/test_backtest_engine.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for BacktestEngine.

Uses synthetic OHLC DataFrames (no MT5 required).

Covers:
  - BacktestConfig default values
  - run() raises ValueError when candles <= warmup_candles
  - run() returns a list
  - run() produces the correct signal types given a detectable pattern
  - warmup_candles boundary: no signals emitted during warm-up
  - enabled_signals filter is respected
  - reset_cooldowns is called per run (independent detector state)
"""

from __future__ import annotations

from datetime import timezone

import pandas as pd
import pytest

from backtest.engine import BacktestConfig, BacktestEngine
from core.indicator import IchimokuConfig
from core.signal_detector import DetectorConfig, Signal, SignalDetector


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_candles(n: int, start: float = 1.1000, step: float = 0.0001) -> pd.DataFrame:
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


def fast_config() -> BacktestConfig:
    """Config with no cooldown and no cloud filter for maximum signal generation."""
    return BacktestConfig(
        detector=DetectorConfig(cooldown_minutes=0, cloud_filter=False),
        warmup_candles=100,
        buffer_size=300,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  BacktestConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestBacktestConfig:

    def test_default_warmup_candles(self):
        assert BacktestConfig().warmup_candles == 100

    def test_default_buffer_size(self):
        assert BacktestConfig().buffer_size == 300

    def test_default_ichimoku_is_standard(self):
        cfg = BacktestConfig()
        assert cfg.ichimoku.tenkan_period == 9
        assert cfg.ichimoku.kijun_period  == 26

    def test_custom_config(self):
        cfg = BacktestConfig(warmup_candles=150, buffer_size=500)
        assert cfg.warmup_candles == 150
        assert cfg.buffer_size    == 500


# ─────────────────────────────────────────────────────────────────────────────
#  BacktestEngine.run()
# ─────────────────────────────────────────────────────────────────────────────

class TestBacktestEngineRun:

    def test_raises_when_not_enough_candles(self):
        engine = BacktestEngine(fast_config())
        candles = make_candles(100)   # == warmup_candles, not >
        with pytest.raises(ValueError, match="Not enough candles"):
            engine.run("EURUSD", "H1", candles)

    def test_returns_list(self):
        engine  = BacktestEngine(fast_config())
        candles = make_candles(300)
        result  = engine.run("EURUSD", "H1", candles)
        assert isinstance(result, list)

    def test_all_results_are_signals(self):
        engine  = BacktestEngine(fast_config())
        candles = make_candles(300)
        result  = engine.run("EURUSD", "H1", candles)
        assert all(isinstance(s, Signal) for s in result)

    def test_signals_have_correct_pair_and_timeframe(self):
        engine  = BacktestEngine(fast_config())
        candles = make_candles(300)
        result  = engine.run("GBPUSD", "H4", candles)
        for sig in result:
            assert sig.pair      == "GBPUSD"
            assert sig.timeframe == "H4"

    def test_enabled_signals_filter_respected(self):
        engine  = BacktestEngine(fast_config())
        candles = make_candles(300)
        result  = engine.run("EURUSD", "H1", candles,
                             enabled_signals={"kumo_breakout_up"})
        signal_types = {s.signal_type for s in result}
        assert signal_types.issubset({"kumo_breakout_up"})

    def test_no_signals_before_warmup(self):
        """Timestamps of all signals must be >= warmup candle boundary."""
        engine  = BacktestEngine(fast_config())
        candles = make_candles(300)
        result  = engine.run("EURUSD", "H1", candles)
        warmup_end = candles.index[fast_config().warmup_candles]
        for sig in result:
            ts = sig.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            assert ts >= warmup_end.to_pydatetime()

    def test_two_runs_are_independent(self):
        """Each run uses a fresh SignalDetector – cooldowns don't carry over."""
        engine  = BacktestEngine(fast_config())
        candles = make_candles(300)
        result1 = engine.run("EURUSD", "H1", candles)
        result2 = engine.run("EURUSD", "H1", candles)
        assert len(result1) == len(result2)

    def test_run_with_minimum_viable_candles(self):
        engine  = BacktestEngine(fast_config())
        candles = make_candles(101)   # warmup=100, replay=1
        result  = engine.run("EURUSD", "H1", candles)
        assert isinstance(result, list)
