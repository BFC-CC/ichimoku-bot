"""Tests for core/risk_manager.py"""

from __future__ import annotations

import pytest

from core.risk_manager import RiskGuard, PositionInfo
from core.config_loader import (
    Config, RiskManagementConfig, GoalConfig,
)


def _default_config(**risk_kw) -> Config:
    return Config(
        risk_management=RiskManagementConfig(
            max_open_trades=3,
            max_daily_loss_pct=3.0,
            max_drawdown_pct=8.0,
            **risk_kw,
        ),
        goal=GoalConfig(target_profit_pct=10.0),
    )


class TestCanTrade:
    def test_allows_when_clear(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        ok, reason = guard.can_trade("EURUSD", [], 10000, 10000)
        assert ok is True

    def test_blocks_max_trades(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        positions = [
            PositionInfo(symbol=f"PAIR{i}") for i in range(3)
        ]
        ok, reason = guard.can_trade("EURUSD", positions, 10000, 10000)
        assert ok is False
        assert "Max open trades" in reason

    def test_blocks_duplicate_symbol(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        positions = [PositionInfo(symbol="EURUSD")]
        ok, reason = guard.can_trade("EURUSD", positions, 10000, 10000)
        assert ok is False
        assert "already open" in reason

    def test_allows_different_symbol(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        positions = [PositionInfo(symbol="GBPUSD")]
        ok, reason = guard.can_trade("EURUSD", positions, 10000, 10000)
        assert ok is True


class TestDailyLoss:
    def test_blocks_after_daily_cap(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        # daily cap = 10000 * 3% = 300
        guard.record_trade_close(-150)
        guard.record_trade_close(-160)  # total = -310 > -300
        ok, reason = guard.can_trade("EURUSD", [], 10000, 10000)
        assert ok is False
        assert "Daily loss cap" in reason

    def test_reset_daily(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        guard.record_trade_close(-310)
        guard.reset_daily()
        ok, _ = guard.can_trade("EURUSD", [], 10000, 10000)
        assert ok is True


class TestDrawdown:
    def test_halts_on_max_drawdown(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        # equity dropped to 9100 = 9% DD > 8%
        ok, reason = guard.can_trade("EURUSD", [], 10000, 9100)
        assert ok is False
        assert guard.is_halted
        assert "drawdown" in reason.lower()


class TestGoal:
    def test_halts_on_goal(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        # target = 10000 * 1.10 = 11000
        ok, reason = guard.can_trade("EURUSD", [], 11100, 11100)
        assert ok is False
        assert guard.is_halted
        assert "Goal" in reason

    def test_no_halt_before_goal(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        ok, _ = guard.can_trade("EURUSD", [], 10500, 10500)
        assert ok is True


class TestHaltPersists:
    def test_halted_blocks_all(self):
        guard = RiskGuard(_default_config())
        guard.set_start_balance(10000)
        guard.can_trade("EURUSD", [], 11100, 11100)  # triggers halt
        ok, reason = guard.can_trade("GBPUSD", [], 11100, 11100)
        assert ok is False
        assert "halted" in reason.lower()
