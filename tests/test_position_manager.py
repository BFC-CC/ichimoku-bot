"""Tests for core/position_manager.py"""

from __future__ import annotations

import pandas as pd
import pytest

from core.position_manager import PositionManager
from core.break_even_manager import BreakEvenManager
from core.config_loader import (
    Config, ExecutionConfig, BreakEvenConfig, RiskManagementConfig,
    TrailingStopConfig, StopLossConfig, IchimokuConfig, ExitConditions,
)
from core.mt5_connector import MT5Connector, PositionInfo
from core.order_executor import OrderExecutor
from core.signal_engine import SignalEngine
from core.ichimoku_calculator import IchimokuValues


def _make_ichi(**kw) -> IchimokuValues:
    defaults = dict(
        tenkan=1.1050, kijun=1.1040,
        senkou_a=1.1060, senkou_b=1.1020,
        chikou=1.1100, close=1.1100,
        cloud_top=1.1060, cloud_bottom=1.1020,
        prev_tenkan=1.1050, prev_kijun=1.1040,
        prev_senkou_a=1.1060, prev_senkou_b=1.1020,
        prev_chikou=1.1050, prev_close=1.1050,
        prev_cloud_top=1.1060, prev_cloud_bottom=1.1020,
        future_span_a=1.1070, future_span_b=1.1010,
        cloud_thickness_pips=40.0,
        bar_time=pd.Timestamp("2024-06-01", tz="UTC"),
    )
    defaults.update(kw)
    return IchimokuValues(**defaults)


def _make_pm(
    trailing_enabled=True,
    trailing_method="fixed",
    exit_on_tk=False,
) -> tuple[PositionManager, MT5Connector]:
    cfg = Config(
        execution=ExecutionConfig(magic_number=99),
        risk_management=RiskManagementConfig(
            trailing_stop=TrailingStopConfig(
                enabled=trailing_enabled,
                method=trailing_method,
                fixed_trail_pips=20,
                trail_step_pips=5,
            ),
            stop_loss=StopLossConfig(buffer_pips=5),
            break_even=BreakEvenConfig(enabled=False),
        ),
        ichimoku=IchimokuConfig(
            exit_conditions=ExitConditions(exit_on_tk_cross_against=exit_on_tk)
        ),
    )
    conn = MT5Connector(cfg, force_sim=True)
    conn.connect()
    executor = OrderExecutor(cfg, conn)
    be_mgr = BreakEvenManager(cfg.risk_management.break_even, executor)
    signal_eng = SignalEngine(cfg.ichimoku)
    pm = PositionManager(cfg, executor, be_mgr, signal_eng)
    return pm, conn


class TestTrailingStop:
    def test_trailing_updates_sl(self):
        pm, conn = _make_pm(trailing_method="fixed")
        conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200, price=1.1000)
        positions = conn.get_open_positions()
        ichi = _make_ichi()
        # Price at 1.1100, trail = 20 pips -> new SL = 1.1080
        # improvement from 1.0900 to 1.1080 = 180 pips > 5 step
        pm.manage_positions(positions, {"EURUSD": ichi}, {"EURUSD": 1.1100})
        updated = conn.get_open_positions()[0]
        assert updated.sl > 1.0900

    def test_trailing_no_update_below_step(self):
        pm, conn = _make_pm(trailing_method="fixed")
        # SL at 1.1078, price 1.1100, trail=20 pips -> new SL=1.1080
        # improvement = 1.1080 - 1.1078 = 0.0002 = 2 pips < 5 step → skip
        conn.send_order("EURUSD", "BUY", 0.1, 1.1078, 1.1200, price=1.1000)
        positions = conn.get_open_positions()
        ichi = _make_ichi()
        pm.manage_positions(positions, {"EURUSD": ichi}, {"EURUSD": 1.1100})
        updated = conn.get_open_positions()[0]
        assert updated.sl == 1.1078  # unchanged — improvement < step


class TestIchimokuExit:
    def test_closes_on_tk_cross_against(self):
        pm, conn = _make_pm(exit_on_tk=True)
        conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200, price=1.1000)
        positions = conn.get_open_positions()
        # TK cross against: tenkan < kijun now, was >= before
        ichi = _make_ichi(
            tenkan=1.1030, kijun=1.1050,
            prev_tenkan=1.1050, prev_kijun=1.1050,
        )
        closed = pm.manage_positions(positions, {"EURUSD": ichi}, {"EURUSD": 1.1050})
        assert len(closed) == 1

    def test_no_exit_when_aligned(self):
        pm, conn = _make_pm(exit_on_tk=True, trailing_enabled=False)
        conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200, price=1.1000)
        positions = conn.get_open_positions()
        ichi = _make_ichi(
            tenkan=1.1060, kijun=1.1040,
            prev_tenkan=1.1055, prev_kijun=1.1040,
        )
        closed = pm.manage_positions(positions, {"EURUSD": ichi}, {"EURUSD": 1.1100})
        assert len(closed) == 0
