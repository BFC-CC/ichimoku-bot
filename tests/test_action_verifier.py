"""Tests for core/action_verifier.py"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.action_verifier import ActionVerifier, ClosedTrade, VerificationResult
from core.config_loader import Config, ExecutionConfig
from core.mt5_connector import MT5Connector
from utils.failed_action_logger import FailedActionLogger


def _make_verifier(tmp_path) -> ActionVerifier:
    cfg = Config(execution=ExecutionConfig(magic_number=99))
    conn = MT5Connector(cfg, force_sim=True)
    conn.connect()
    failed_logger = FailedActionLogger(str(tmp_path))
    return ActionVerifier(cfg, conn, failed_logger)


class TestActionVerifier:
    def test_positive_pnl_correct(self, tmp_path):
        verifier = _make_verifier(tmp_path)
        trade = ClosedTrade(order_id=1, symbol="EURUSD", pnl=50.0)
        result = verifier.verify(trade)
        assert result.result == "CORRECT"
        assert verifier.stats["correct"] == 1

    def test_zero_pnl_correct(self, tmp_path):
        verifier = _make_verifier(tmp_path)
        trade = ClosedTrade(order_id=1, symbol="EURUSD", pnl=0.0)
        result = verifier.verify(trade)
        assert result.result == "CORRECT"

    def test_negative_pnl_incorrect(self, tmp_path):
        verifier = _make_verifier(tmp_path)
        trade = ClosedTrade(
            order_id=1, symbol="EURUSD", pnl=-50.0,
            exit_reason="sl", entry_price=1.1000, sl_price=1.0960,
        )
        result = verifier.verify(trade)
        assert result.result.startswith("INCORRECT")
        assert result.failure_type == "SL_HIT"
        assert verifier.stats["incorrect"] == 1

    def test_csv_written_on_failure(self, tmp_path):
        verifier = _make_verifier(tmp_path)
        trade = ClosedTrade(
            order_id=1, symbol="EURUSD", pnl=-50.0,
            exit_reason="sl",
            entry_time=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
            exit_time=datetime(2024, 6, 1, 16, 0, tzinfo=timezone.utc),
        )
        verifier.verify(trade)
        assert verifier.failed_logger.file_path.exists()

    def test_no_csv_on_correct(self, tmp_path):
        verifier = _make_verifier(tmp_path)
        trade = ClosedTrade(order_id=1, symbol="EURUSD", pnl=50.0)
        verifier.verify(trade)
        assert not verifier.failed_logger.file_path.exists()

    def test_stats_accumulate(self, tmp_path):
        verifier = _make_verifier(tmp_path)
        verifier.verify(ClosedTrade(pnl=50.0))
        verifier.verify(ClosedTrade(pnl=-20.0, exit_reason="sl"))
        verifier.verify(ClosedTrade(pnl=30.0))
        assert verifier.stats["total"] == 3
        assert verifier.stats["correct"] == 2
        assert verifier.stats["incorrect"] == 1

    def test_failure_counts(self, tmp_path):
        verifier = _make_verifier(tmp_path)
        verifier.verify(ClosedTrade(pnl=-20.0, exit_reason="sl"))
        verifier.verify(ClosedTrade(pnl=-10.0, exit_reason="sl"))
        assert verifier.failure_counts["SL_HIT"] == 2
