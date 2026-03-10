"""Tests for core/break_even_manager.py"""

from __future__ import annotations

import pytest

from core.break_even_manager import BreakEvenManager
from core.config_loader import Config, ExecutionConfig, BreakEvenConfig
from core.mt5_connector import MT5Connector, PositionInfo
from core.order_executor import OrderExecutor


def _make_be_manager(trigger=20, lock_in=2) -> tuple[BreakEvenManager, MT5Connector]:
    cfg = Config(execution=ExecutionConfig(magic_number=99))
    conn = MT5Connector(cfg, force_sim=True)
    conn.connect()
    executor = OrderExecutor(cfg, conn)
    be_cfg = BreakEvenConfig(enabled=True, trigger_pips=trigger, lock_in_pips=lock_in)
    return BreakEvenManager(be_cfg, executor), conn


class TestBreakEvenManager:
    def test_applies_be_on_buy(self):
        mgr, conn = _make_be_manager(trigger=20, lock_in=2)
        # Open a BUY position
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200, price=1.1000)
        pos = conn.get_open_positions()[0]
        # Simulate price moved 25 pips up
        current_price = 1.1025
        applied = mgr.check_and_apply(pos, current_price)
        assert applied is True
        # Check SL was moved
        updated_pos = conn.get_open_positions()[0]
        assert updated_pos.sl == pytest.approx(1.1000 + 2 * 0.0001, abs=1e-5)

    def test_no_be_if_not_enough_profit(self):
        mgr, conn = _make_be_manager(trigger=20, lock_in=2)
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200, price=1.1000)
        pos = conn.get_open_positions()[0]
        # Only 10 pips profit, trigger is 20
        applied = mgr.check_and_apply(pos, 1.1010)
        assert applied is False

    def test_no_double_be(self):
        mgr, conn = _make_be_manager(trigger=20, lock_in=2)
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200, price=1.1000)
        pos = conn.get_open_positions()[0]
        mgr.check_and_apply(pos, 1.1025)
        # Second call should not re-apply
        pos2 = conn.get_open_positions()[0]
        applied = mgr.check_and_apply(pos2, 1.1030)
        assert applied is False

    def test_disabled(self):
        cfg = Config(execution=ExecutionConfig(magic_number=99))
        conn = MT5Connector(cfg, force_sim=True)
        conn.connect()
        executor = OrderExecutor(cfg, conn)
        be_cfg = BreakEvenConfig(enabled=False)
        mgr = BreakEvenManager(be_cfg, executor)
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200, price=1.1000)
        pos = conn.get_open_positions()[0]
        applied = mgr.check_and_apply(pos, 1.1050)
        assert applied is False

    def test_sell_be(self):
        mgr, conn = _make_be_manager(trigger=20, lock_in=2)
        result = conn.send_order("EURUSD", "SELL", 0.1, 1.1100, 1.0800, price=1.1000)
        pos = conn.get_open_positions()[0]
        # Price dropped 25 pips
        applied = mgr.check_and_apply(pos, 1.0975)
        assert applied is True
        updated = conn.get_open_positions()[0]
        # SL should be at entry - lock_in
        assert updated.sl == pytest.approx(1.1000 - 2 * 0.0001, abs=1e-5)
