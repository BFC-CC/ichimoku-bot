"""Tests for utils/trade_logger.py"""

from __future__ import annotations

import csv
from dataclasses import dataclass

import pytest

from utils.trade_logger import TradeLogger, TRADE_COLUMNS


@dataclass
class _FakeTrade:
    order_id: int = 1
    symbol: str = "EURUSD"
    action_type: str = "BUY"
    entry_price: float = 1.1000
    exit_price: float = 1.1050
    sl_price: float = 1.0960
    tp_price: float = 1.1100
    lot_size: float = 0.1
    pnl: float = 50.0
    exit_reason: str = "tp"
    entry_time: str = "2024-06-01 12:00"


class TestTradeLogger:
    def test_creates_csv(self, tmp_path):
        logger = TradeLogger(str(tmp_path))
        logger.log(_FakeTrade(), "CORRECT")
        assert logger.file_path.exists()

    def test_correct_columns(self, tmp_path):
        logger = TradeLogger(str(tmp_path))
        logger.log(_FakeTrade())
        with open(logger.file_path) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == TRADE_COLUMNS
        assert len(TRADE_COLUMNS) == 22

    def test_appends(self, tmp_path):
        logger = TradeLogger(str(tmp_path))
        logger.log(_FakeTrade(order_id=1))
        logger.log(_FakeTrade(order_id=2))
        with open(logger.file_path) as f:
            rows = list(csv.reader(f))
        assert len(rows) == 3  # header + 2

    def test_pnl_formatting(self, tmp_path):
        logger = TradeLogger(str(tmp_path))
        logger.log(_FakeTrade(pnl=-23.456))
        with open(logger.file_path) as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["pnl_usd"] == "-23.46"

    def test_verification_result_stored(self, tmp_path):
        logger = TradeLogger(str(tmp_path))
        logger.log(_FakeTrade(), "INCORRECT:SL_HIT")
        with open(logger.file_path) as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["verification_result"] == "INCORRECT:SL_HIT"
