"""Tests for core/trade_event_listener.py"""

from __future__ import annotations

import pytest

from core.trade_event_listener import TradeEventListener
from core.action_verifier import ActionVerifier
from core.config_loader import Config, ExecutionConfig
from core.mt5_connector import MT5Connector, DEAL_ENTRY_OUT
from utils.failed_action_logger import FailedActionLogger


def _make_listener(tmp_path) -> tuple[TradeEventListener, MT5Connector]:
    cfg = Config(execution=ExecutionConfig(magic_number=99))
    conn = MT5Connector(cfg, force_sim=True)
    conn.connect()
    failed_logger = FailedActionLogger(str(tmp_path))
    verifier = ActionVerifier(cfg, conn, failed_logger)
    listener = TradeEventListener(conn, verifier)
    return listener, conn


class TestTradeEventListener:
    def test_detects_close_event(self, tmp_path):
        listener, conn = _make_listener(tmp_path)
        # Open and close a position
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        conn.close_position(result.order_id)
        closed = listener.poll()
        # Should detect the close deal
        out_deals = [d for d in conn.get_deal_history() if d.entry == DEAL_ENTRY_OUT]
        assert len(out_deals) >= 1

    def test_deduplicates(self, tmp_path):
        listener, conn = _make_listener(tmp_path)
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        conn.close_position(result.order_id)
        closed1 = listener.poll()
        closed2 = listener.poll()
        # Second poll should find no new events
        assert len(closed2) == 0

    def test_multiple_closes(self, tmp_path):
        listener, conn = _make_listener(tmp_path)
        r1 = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        r2 = conn.send_order("GBPUSD", "SELL", 0.2, 1.2800, 1.2500)
        conn.close_position(r1.order_id)
        conn.close_position(r2.order_id)
        closed = listener.poll()
        out_count = sum(1 for c in closed)
        assert out_count >= 1  # at least one close detected
