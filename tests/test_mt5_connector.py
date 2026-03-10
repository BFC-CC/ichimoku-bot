"""Tests for core/mt5_connector.py — simulation mode."""

from __future__ import annotations

import pytest

from core.mt5_connector import MT5Connector, DEAL_ENTRY_IN, DEAL_ENTRY_OUT
from core.config_loader import Config, ExecutionConfig


def _make_connector() -> MT5Connector:
    cfg = Config(execution=ExecutionConfig(magic_number=12345, order_comment="test"))
    conn = MT5Connector(cfg, force_sim=True)
    conn.connect()
    return conn


class TestSimConnection:
    def test_connects_in_sim(self):
        conn = _make_connector()
        assert conn.is_simulation
        assert conn._connected

    def test_disconnect(self):
        conn = _make_connector()
        conn.disconnect()
        assert not conn._connected


class TestSimAccount:
    def test_account_info(self):
        conn = _make_connector()
        info = conn.get_account_info()
        assert info.balance == 10_000.0
        assert info.currency == "USD"
        assert info.trade_mode == 0


class TestSimBars:
    def test_get_bars(self):
        conn = _make_connector()
        df = conn.get_bars("EURUSD", "H4", 200)
        assert len(df) == 200
        assert "close" in df.columns

    def test_bars_jpy(self):
        conn = _make_connector()
        df = conn.get_bars("USDJPY", "H4", 200)
        assert len(df) == 200
        assert df["close"].iloc[-1] > 100  # JPY range


class TestSimOrders:
    def test_open_and_get_positions(self):
        conn = _make_connector()
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        assert result.success
        positions = conn.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "EURUSD"
        assert positions[0].magic == 12345

    def test_close_position(self):
        conn = _make_connector()
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        ticket = result.order_id
        close_result = conn.close_position(ticket)
        assert close_result.success
        assert len(conn.get_open_positions()) == 0

    def test_modify_sl(self):
        conn = _make_connector()
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        ticket = result.order_id
        ok = conn.modify_sl(ticket, 1.0950)
        assert ok
        pos = conn.get_open_positions()[0]
        assert pos.sl == 1.0950

    def test_close_nonexistent(self):
        conn = _make_connector()
        result = conn.close_position(99999)
        assert not result.success


class TestSimDeals:
    def test_deal_history(self):
        conn = _make_connector()
        conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        deals = conn.get_deal_history()
        assert len(deals) == 1
        assert deals[0].entry == DEAL_ENTRY_IN

    def test_close_creates_out_deal(self):
        conn = _make_connector()
        result = conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        conn.close_position(result.order_id)
        deals = conn.get_deal_history()
        out_deals = [d for d in deals if d.entry == DEAL_ENTRY_OUT]
        assert len(out_deals) == 1


class TestSimSymbolInfo:
    def test_eurusd_info(self):
        conn = _make_connector()
        info = conn.get_symbol_info("EURUSD")
        assert info.name == "EURUSD"
        assert info.digits == 5

    def test_jpy_info(self):
        conn = _make_connector()
        info = conn.get_symbol_info("USDJPY")
        assert info.digits == 3


class TestCloseAll:
    def test_close_all(self):
        conn = _make_connector()
        conn.send_order("EURUSD", "BUY", 0.1, 1.0900, 1.1200)
        conn.send_order("GBPUSD", "SELL", 0.2, 1.2800, 1.2500)
        closed = conn.close_all_positions()
        assert closed == 2
        assert len(conn.get_open_positions()) == 0
