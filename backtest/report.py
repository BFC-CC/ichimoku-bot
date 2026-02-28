"""
backtest/report.py
─────────────────────────────────────────────────────────────────────────────
Collects signals from one or more backtest runs and produces:
  1. A CSV file with every triggered signal and its details.
  2. A printed summary table broken down by pair, timeframe, and signal type.

Usage
-----
    from backtest.report import BacktestReport
    report = BacktestReport()
    report.add_results("EURUSD", "H1", signals_eurusd_h1)
    report.add_results("GBPUSD", "H1", signals_gbpusd_h1)
    report.save_csv("./backtest_results/signals.csv")
    report.print_summary()
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd
from loguru import logger

from core.signal_detector import Signal


class BacktestReport:
    """
    Aggregates signals from multiple backtest runs and generates reports.
    """

    def __init__(self):
        # (symbol, timeframe) → list[Signal]
        self._results: Dict[Tuple[str, str], List[Signal]] = defaultdict(list)

    # ── data collection ───────────────────────────────────────────────────────

    def add_results(
        self, symbol: str, timeframe: str, signals: List[Signal]
    ) -> None:
        """Register the signal list from one backtest run."""
        self._results[(symbol, timeframe)].extend(signals)
        logger.info(
            f"Report: added {len(signals)} signals for {symbol} {timeframe}."
        )

    @property
    def all_signals(self) -> List[Signal]:
        """Flat list of every signal across all runs."""
        return [s for signals in self._results.values() for s in signals]

    # ── CSV export ────────────────────────────────────────────────────────────

    def save_csv(self, path: str) -> None:
        """
        Write all signals to a CSV file.

        Columns: timestamp, pair, timeframe, direction, signal_type, price,
                 + one column per details key (tenkan, kijun, etc.)
        """
        if not self.all_signals:
            logger.warning("No signals to export.")
            return

        rows = []
        for sig in sorted(self.all_signals, key=lambda s: s.timestamp):
            row = {
                "timestamp":   sig.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "pair":        sig.pair,
                "timeframe":   sig.timeframe,
                "direction":   sig.direction,
                "signal_type": sig.signal_type,
                "price":       sig.price,
            }
            row.update(sig.details)
            rows.append(row)

        df = pd.DataFrame(rows)

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        df.to_csv(path, index=False)
        logger.info(f"Signals CSV saved → {path}  ({len(df)} rows)")

    # ── console summary ───────────────────────────────────────────────────────

    def print_summary(self) -> None:
        """Print a formatted summary table to stdout."""
        all_sigs = self.all_signals
        if not all_sigs:
            print("\n  No signals were generated.\n")
            return

        sep  = "─" * 60
        sep2 = "═" * 60

        print(f"\n{sep2}")
        print("  ICHIMOKU BACKTEST REPORT")
        print(sep2)

        # Date range
        timestamps = [s.timestamp for s in all_sigs]
        print(f"  Period   : {min(timestamps).date()} → {max(timestamps).date()}")
        print(f"  Signals  : {len(all_sigs)}")
        print(sep)

        # Per pair/timeframe breakdown
        for (symbol, tf), signals in sorted(self._results.items()):
            if not signals:
                continue

            buys  = [s for s in signals if s.direction == "BUY"]
            sells = [s for s in signals if s.direction == "SELL"]

            print(f"\n  {symbol}  {tf}")
            print(f"  {'─' * 30}")
            print(f"  Total : {len(signals):>4}  (BUY: {len(buys)}, SELL: {len(sells)})")

            # Per signal type
            type_counts: Dict[str, int] = defaultdict(int)
            for s in signals:
                type_counts[s.signal_type] += 1

            for stype, count in sorted(type_counts.items()):
                direction = "BUY " if stype.endswith("_up") else "SELL"
                label = stype.replace("_", " ").title()
                print(f"    {direction}  {label:<25} : {count:>4}")

        print(f"\n{sep2}\n")

    def signals_as_dataframe(self) -> pd.DataFrame:
        """Return all signals as a pandas DataFrame (for further analysis)."""
        if not self.all_signals:
            return pd.DataFrame()

        rows = []
        for sig in sorted(self.all_signals, key=lambda s: s.timestamp):
            row = {
                "timestamp":   sig.timestamp,
                "pair":        sig.pair,
                "timeframe":   sig.timeframe,
                "direction":   sig.direction,
                "signal_type": sig.signal_type,
                "price":       sig.price,
            }
            row.update(sig.details)
            rows.append(row)

        return pd.DataFrame(rows)
