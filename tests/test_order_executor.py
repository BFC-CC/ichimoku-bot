"""Tests for core/order_executor.py"""

from __future__ import annotations

import pytest

from core.order_executor import OrderExecutor
from core.mt5_connector import MT5Connector
from core.config_loader import Config, ExecutionConfig


def _make_executor() -> tuple[OrderExecutor, MT5Connector]:
    cfg = Config(execution=ExecutionConfig(
        magic_number=12345, retry_attempts=2, retry_delay_ms=10
    ))
    conn = MT5Connector(cfg, force_sim=True)
    conn.connect()
    return OrderExecutor(cfg, conn), conn


class TestOrderExecutor:
    def test_open_trade(self):
        executor, conn = _make_executor()
        result = executor.open_trade("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        assert result.success
        assert len(conn.get_open_positions()) == 1

    def test_close_trade(self):
        executor, conn = _make_executor()
        result = executor.open_trade("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        close_result = executor.close_trade(result.order_id)
        assert close_result.success
        assert len(conn.get_open_positions()) == 0

    def test_modify_stop_loss(self):
        executor, conn = _make_executor()
        result = executor.open_trade("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        ok = executor.modify_stop_loss(result.order_id, 1.0950)
        assert ok
