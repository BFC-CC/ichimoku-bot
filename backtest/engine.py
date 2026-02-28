"""
backtest/engine.py
─────────────────────────────────────────────────────────────────────────────
Backtest replay engine.

Replays historical candles chronologically through the exact same pipeline
the live bot uses:

    CandleBuffer → IchimokuIndicator → SignalDetector

This means backtest results are directly comparable to live behaviour.
No look-ahead bias: at each step, the buffer contains only the candles
that would have been available at that point in time.

Usage
-----
    from backtest.engine import BacktestEngine, BacktestConfig

    engine = BacktestEngine(BacktestConfig())
    results = engine.run(
        symbol="EURUSD",
        timeframe="H1",
        candles=historical_df,
        enabled_signals={"tk_cross_up", "kumo_breakout_up"},
    )
    # results is a list[Signal]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import pandas as pd
from loguru import logger

from core.candle_buffer import CandleBuffer
from core.indicator import IchimokuConfig, IchimokuIndicator
from core.signal_detector import DetectorConfig, Signal, SignalDetector


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    # Ichimoku settings
    ichimoku: IchimokuConfig = field(default_factory=IchimokuConfig)

    # Signal detection settings
    detector: DetectorConfig = field(default_factory=DetectorConfig)

    # How many candles to use as the warm-up window before signal checking begins.
    # Must be >= 78 (52 senkou_b + 26 displacement) for valid Ichimoku values.
    warmup_candles: int = 100

    # Buffer size – keep last N candles in rolling window
    buffer_size: int = 300


# ─────────────────────────────────────────────────────────────────────────────
#  Backtest engine
# ─────────────────────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Single-pair, single-timeframe backtest engine.

    Parameters
    ----------
    config : BacktestConfig
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.cfg = config or BacktestConfig()

    def run(
        self,
        symbol: str,
        timeframe: str,
        candles: pd.DataFrame,
        enabled_signals: Optional[Set[str]] = None,
    ) -> List[Signal]:
        """
        Replay *candles* and collect every signal that fires.

        Parameters
        ----------
        symbol          : e.g. 'EURUSD'
        timeframe       : e.g. 'H1'
        candles         : full historical DataFrame (index=UTC datetime,
                          columns=open,high,low,close)
        enabled_signals : set of signal_type strings to evaluate.
                          Defaults to all six signal types.

        Returns
        -------
        list[Signal]
        """
        total = len(candles)
        warmup = self.cfg.warmup_candles

        if total <= warmup:
            raise ValueError(
                f"Not enough candles for backtest: got {total}, "
                f"need > {warmup} (warmup_candles setting)."
            )

        logger.info(
            f"Starting backtest | {symbol} {timeframe} | "
            f"{total} candles | warmup={warmup} | "
            f"replay from candle {warmup + 1}"
        )

        # Fresh components for this run
        buffer   = CandleBuffer(max_size=self.cfg.buffer_size)
        indicator = IchimokuIndicator(config=self.cfg.ichimoku)
        detector  = SignalDetector(
            config=self.cfg.detector,
            enabled_signals=enabled_signals,
        )

        # Seed the buffer with the warm-up window
        warmup_df = candles.iloc[:warmup]
        buffer.seed(warmup_df)

        all_signals: List[Signal] = []
        replay_candles = candles.iloc[warmup:]

        for i, (ts, row) in enumerate(replay_candles.iterrows(), start=1):
            # Build a one-row DataFrame and append to the buffer
            new_candle = pd.DataFrame(
                [[row["open"], row["high"], row["low"], row["close"]]],
                index=[ts],
                columns=["open", "high", "low", "close"],
            )
            new_candle.index.name = "time"
            buffer.append(new_candle)

            if not buffer.is_ready:
                continue

            # Compute indicators
            try:
                ind_values = indicator.latest_values(buffer.data)
            except Exception as exc:
                logger.warning(f"Indicator error at {ts}: {exc}")
                continue

            # Check signals
            signals = detector.check(
                pair=symbol,
                timeframe=timeframe,
                indicators=ind_values,
                candle_time=ts if hasattr(ts, "tzinfo") else pd.Timestamp(ts, tz="UTC"),
            )
            all_signals.extend(signals)

            # Progress log every 500 candles
            if i % 500 == 0:
                logger.info(
                    f"  {symbol} {timeframe}: replayed {i}/{len(replay_candles)} candles "
                    f"| signals so far: {len(all_signals)}"
                )

        logger.info(
            f"Backtest complete | {symbol} {timeframe} | "
            f"Total signals: {len(all_signals)}"
        )
        return all_signals
