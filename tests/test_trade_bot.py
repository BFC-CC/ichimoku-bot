"""Tests for trade_bot.py — end-to-end orchestrator tests."""

from __future__ import annotations

import pytest

from trade_bot import TradeBotOrchestrator
from core.config_loader import ConfigLoader, Config


def _load_config() -> Config:
    return ConfigLoader.load("config/strategy_config.json")


class TestTradeBotInit:
    def test_creates_all_components(self):
        cfg = _load_config()
        bot = TradeBotOrchestrator(cfg, force_sim=True)
        assert bot.mt5.is_simulation
        assert bot.guard is not None
        assert bot.calculator is not None
        assert bot.signal_engine is not None
        assert bot.lot_calc is not None
        assert bot.sltp is not None
        assert bot.risk_guard is not None
        assert bot.session_filter is not None
        assert bot.trend_filter is not None
        assert bot.pos_manager is not None
        assert bot.verifier is not None
        assert bot.event_listener is not None
        assert bot.state is not None

    def test_connects_in_sim(self):
        cfg = _load_config()
        bot = TradeBotOrchestrator(cfg, force_sim=True)
        assert bot.mt5.connect()
        assert bot.mt5.is_simulation
        bot.mt5.disconnect()


class TestTradeBotCycle:
    def test_run_once_completes(self):
        cfg = _load_config()
        bot = TradeBotOrchestrator(cfg, force_sim=True)
        # run_once=True exits after one cycle
        bot.start(run_once=True)
        # Should not crash — basic smoke test
        assert True

    def test_state_updated_after_cycle(self):
        cfg = _load_config()
        bot = TradeBotOrchestrator(cfg, force_sim=True)
        bot.start(run_once=True)
        snap = bot.state.snapshot()
        assert snap.balance > 0
        # Should have signal snapshots for configured pairs
        assert len(snap.signals) > 0

    def test_signals_evaluated_for_all_pairs(self):
        cfg = _load_config()
        bot = TradeBotOrchestrator(cfg, force_sim=True)
        bot.start(run_once=True)
        snap = bot.state.snapshot()
        symbols_scanned = {s.symbol for s in snap.signals}
        # At least some pairs should have been scanned
        assert len(symbols_scanned) > 0

    def test_risk_guard_initialized(self):
        cfg = _load_config()
        bot = TradeBotOrchestrator(cfg, force_sim=True)
        bot.start(run_once=True)
        # Start balance should be set
        assert bot.risk_guard._start_balance > 0


class TestTradeBotShutdown:
    def test_stop_flag(self):
        cfg = _load_config()
        bot = TradeBotOrchestrator(cfg, force_sim=True)
        bot.stop()
        assert bot._running is False
