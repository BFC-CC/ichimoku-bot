"""Tests for utils/state.py"""

from __future__ import annotations

import threading

import pytest

from utils.state import BotState, BotSnapshot, SignalSnapshot, TradeRecord


class TestBotState:
    def test_initial_snapshot(self):
        state = BotState()
        snap = state.snapshot()
        assert isinstance(snap, BotSnapshot)
        assert snap.balance == 0.0
        assert snap.signals == []
        assert snap.is_halted is False

    def test_update_account(self):
        state = BotState()
        state.update_account(10500, 10400)
        snap = state.snapshot()
        assert snap.balance == 10500
        assert snap.equity == 10400

    def test_goal_progress(self):
        state = BotState()
        state.set_start_balance(10000)
        state.set_target_pct(10)
        state.update_account(10500, 10500)
        snap = state.snapshot()
        # 500 / 10000 = 5% gain, target = 10%, progress = 50%
        assert snap.goal_progress_pct == 50.0

    def test_update_signals(self):
        state = BotState()
        sigs = [SignalSnapshot(symbol="EURUSD", signal="BUY")]
        state.update_signals(sigs)
        snap = state.snapshot()
        assert len(snap.signals) == 1
        assert snap.signals[0].signal == "BUY"

    def test_add_trades_capped(self):
        state = BotState()
        for i in range(150):
            state.add_trade(TradeRecord(order_id=i))
        snap = state.snapshot()
        assert len(snap.recent_trades) == 20  # capped at last 20

    def test_log_lines_capped(self):
        state = BotState()
        for i in range(200):
            state.add_log_line(f"line {i}")
        snap = state.snapshot()
        assert len(snap.log_lines) == 30  # capped at last 30

    def test_halted_state(self):
        state = BotState()
        state.set_halted(True, "Goal reached")
        snap = state.snapshot()
        assert snap.is_halted is True
        assert snap.halt_reason == "Goal reached"

    def test_thread_safety(self):
        state = BotState()
        errors = []

        def writer():
            try:
                for i in range(100):
                    state.update_account(10000 + i, 10000 + i)
                    state.add_log_line(f"log {i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    state.snapshot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_verification_stats(self):
        state = BotState()
        state.update_verification_stats(
            {"total": 10, "correct": 7, "incorrect": 3},
            {"SL_HIT": 2, "WEAK_SIGNAL": 1}
        )
        snap = state.snapshot()
        assert snap.verification_stats["total"] == 10
        assert snap.verification_stats["fail_SL_HIT"] == 2
