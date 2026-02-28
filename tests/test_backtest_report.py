"""
tests/test_backtest_report.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for BacktestReport.

Covers:
  - add_results() accumulates signals per (symbol, timeframe)
  - all_signals property flattens all results
  - save_csv() writes file with expected columns
  - save_csv() with no signals is a no-op (no file created)
  - print_summary() runs without error for normal and empty cases
  - signals_as_dataframe() returns correct DataFrame
  - signals_as_dataframe() returns empty DataFrame when no signals
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
import pytest

from backtest.report import BacktestReport
from core.signal_detector import Signal


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_signal(
    pair: str = "EURUSD",
    timeframe: str = "H1",
    signal_type: str = "tk_cross_up",
    direction: str = "BUY",
    hour: int = 10,
) -> Signal:
    return Signal(
        pair=pair,
        timeframe=timeframe,
        signal_type=signal_type,
        direction=direction,
        timestamp=datetime(2024, 6, 1, hour, 0, tzinfo=timezone.utc),
        price=1.10500,
        details={"tenkan": 1.10500, "kijun": 1.10450},
    )


def make_signals(n: int, **kwargs) -> list:
    return [make_signal(hour=i % 24, **kwargs) for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
#  add_results / all_signals
# ─────────────────────────────────────────────────────────────────────────────

class TestAddResults:

    def test_add_results_stores_signals(self):
        report = BacktestReport()
        sigs   = make_signals(5)
        report.add_results("EURUSD", "H1", sigs)
        assert len(report.all_signals) == 5

    def test_add_results_accumulates(self):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(3))
        report.add_results("EURUSD", "H1", make_signals(2))
        assert len(report.all_signals) == 5

    def test_multiple_pairs_stored_separately(self):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(3, pair="EURUSD"))
        report.add_results("GBPUSD", "H1", make_signals(4, pair="GBPUSD"))
        assert len(report.all_signals) == 7

    def test_all_signals_empty_by_default(self):
        assert BacktestReport().all_signals == []


# ─────────────────────────────────────────────────────────────────────────────
#  save_csv()
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveCsv:

    def test_creates_csv_file(self, tmp_path):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(5))
        path = str(tmp_path / "signals.csv")
        report.save_csv(path)
        assert os.path.exists(path)

    def test_csv_has_required_columns(self, tmp_path):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(3))
        path = str(tmp_path / "signals.csv")
        report.save_csv(path)
        df = pd.read_csv(path)
        for col in ["timestamp", "pair", "timeframe", "direction", "signal_type", "price"]:
            assert col in df.columns

    def test_csv_row_count_matches_signals(self, tmp_path):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(7))
        path = str(tmp_path / "out.csv")
        report.save_csv(path)
        df = pd.read_csv(path)
        assert len(df) == 7

    def test_csv_sorted_by_timestamp(self, tmp_path):
        report = BacktestReport()
        # Add signals with different hours (they'll be ordered)
        sigs = [make_signal(hour=h) for h in [5, 2, 8, 1]]
        report.add_results("EURUSD", "H1", sigs)
        path = str(tmp_path / "sorted.csv")
        report.save_csv(path)
        df = pd.read_csv(path)
        timestamps = list(df["timestamp"])
        assert timestamps == sorted(timestamps)

    def test_no_file_created_when_no_signals(self, tmp_path):
        report = BacktestReport()
        path = str(tmp_path / "empty.csv")
        report.save_csv(path)
        assert not os.path.exists(path)

    def test_creates_parent_directory(self, tmp_path):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(2))
        path = str(tmp_path / "subdir" / "signals.csv")
        report.save_csv(path)
        assert os.path.exists(path)

    def test_detail_columns_included(self, tmp_path):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(2))
        path = str(tmp_path / "details.csv")
        report.save_csv(path)
        df = pd.read_csv(path)
        # Signal details contain "tenkan" and "kijun"
        assert "tenkan" in df.columns
        assert "kijun" in df.columns


# ─────────────────────────────────────────────────────────────────────────────
#  print_summary()
# ─────────────────────────────────────────────────────────────────────────────

class TestPrintSummary:

    def test_no_error_with_signals(self, capsys):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(5))
        report.print_summary()   # should not raise
        out = capsys.readouterr().out
        assert "EURUSD" in out

    def test_no_error_with_empty_report(self, capsys):
        report = BacktestReport()
        report.print_summary()
        out = capsys.readouterr().out
        assert "No signals" in out

    def test_summary_shows_buy_sell_counts(self, capsys):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", [
            make_signal(direction="BUY"),
            make_signal(direction="BUY"),
            make_signal(direction="SELL", signal_type="tk_cross_down"),
        ])
        report.print_summary()
        out = capsys.readouterr().out
        assert "BUY" in out
        assert "SELL" in out

    def test_summary_shows_date_range(self, capsys):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(3))
        report.print_summary()
        out = capsys.readouterr().out
        assert "2024" in out


# ─────────────────────────────────────────────────────────────────────────────
#  signals_as_dataframe()
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalsAsDataframe:

    def test_returns_dataframe(self):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(5))
        df = report.signals_as_dataframe()
        assert isinstance(df, pd.DataFrame)

    def test_correct_row_count(self):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(8))
        df = report.signals_as_dataframe()
        assert len(df) == 8

    def test_empty_dataframe_when_no_signals(self):
        report = BacktestReport()
        df = report.signals_as_dataframe()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_required_columns_present(self):
        report = BacktestReport()
        report.add_results("EURUSD", "H1", make_signals(3))
        df = report.signals_as_dataframe()
        for col in ["timestamp", "pair", "timeframe", "direction", "signal_type", "price"]:
            assert col in df.columns

    def test_sorted_by_timestamp(self):
        report = BacktestReport()
        sigs = [make_signal(hour=h) for h in [3, 1, 4, 1, 5]]
        report.add_results("EURUSD", "H1", sigs)
        df = report.signals_as_dataframe()
        assert list(df["timestamp"]) == sorted(df["timestamp"])
