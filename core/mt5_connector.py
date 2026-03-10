"""
core/mt5_connector.py
─────────────────────────────────────────────────────────────────────────────
MT5 trading connector with full simulation fallback.

Reuses MT5_AVAILABLE/MT5_BACKEND from core.data_fetcher for import detection.
When MT5 is unavailable, all operations run in simulation mode with in-memory
position and deal storage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from core.config_loader import Config, AccountConfig, ExecutionConfig

# Reuse MT5 availability flags from data_fetcher
try:
    from core.data_fetcher import MT5_AVAILABLE, MT5_BACKEND, mt5
except ImportError:
    MT5_AVAILABLE = False
    MT5_BACKEND = None
    mt5 = None


# ─────────────────────────────────────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AccountInfo:
    balance: float = 10_000.0
    equity: float = 10_000.0
    margin: float = 0.0
    free_margin: float = 10_000.0
    currency: str = "USD"
    login: int = 0
    server: str = "Simulation"
    trade_mode: int = 0  # 0 = demo


@dataclass
class SymbolInfo:
    name: str = ""
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    contract_size: float = 100_000.0
    point: float = 0.00001
    digits: int = 5
    trade_tick_size: float = 0.00001
    ask: float = 0.0
    bid: float = 0.0


@dataclass
class OrderResult:
    success: bool = False
    order_id: int = 0
    volume: float = 0.0
    price: float = 0.0
    comment: str = ""
    retcode: int = 0


@dataclass
class PositionInfo:
    ticket: int = 0
    symbol: str = ""
    type: int = 0  # 0=BUY, 1=SELL
    volume: float = 0.0
    price_open: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    profit: float = 0.0
    magic: int = 0
    comment: str = ""
    time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DealInfo:
    ticket: int = 0
    order: int = 0
    symbol: str = ""
    type: int = 0
    entry: int = 0  # 0=IN, 1=OUT
    volume: float = 0.0
    price: float = 0.0
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    magic: int = 0
    comment: str = ""
    time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1


# ─────────────────────────────────────────────────────────────────────────────
#  MT5 Connector
# ─────────────────────────────────────────────────────────────────────────────

class MT5Connector:
    """MT5 trading connector with simulation fallback."""

    def __init__(self, config: Config, force_sim: bool = False) -> None:
        self.cfg = config
        self._connected = False
        self._sim_mode = force_sim or not MT5_AVAILABLE

        # Simulation state
        self._sim_balance = 10_000.0
        self._sim_equity = 10_000.0
        self._sim_positions: Dict[int, PositionInfo] = {}
        self._sim_deals: List[DealInfo] = []
        self._sim_next_ticket = 1000
        self._sim_bars_cache: Dict[str, pd.DataFrame] = {}

    @property
    def is_simulation(self) -> bool:
        return self._sim_mode

    def connect(self) -> bool:
        """Connect to MT5 or enter simulation mode."""
        if self._sim_mode:
            logger.info("[SIM] MT5 Connector in simulation mode")
            self._connected = True
            return True

        try:
            kwargs = {}
            acc = self.cfg.account
            if acc.login:
                kwargs["login"] = acc.login
                kwargs["server"] = acc.server
                kwargs["password"] = acc.password

            if not mt5.initialize(**kwargs):
                err = mt5.last_error()
                logger.warning(f"MT5 initialize failed: {err} — falling back to simulation")
                self._sim_mode = True
                self._connected = True
                return True

            # Demo mode safety check
            if acc.demo_mode:
                info = mt5.account_info()
                if info and info.trade_mode != 0:
                    mt5.shutdown()
                    logger.error("demo_mode=true but account is not demo. Refusing to connect.")
                    return False

            self._connected = True
            logger.info("MT5 connected (live)")
            return True
        except Exception:
            logger.warning("MT5 connection failed — falling back to simulation")
            self._sim_mode = True
            self._connected = True
            return True

    def disconnect(self) -> None:
        if self._connected and not self._sim_mode:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self._connected = False
        logger.info("MT5 disconnected")

    def get_account_info(self) -> AccountInfo:
        if self._sim_mode:
            unrealized = sum(p.profit for p in self._sim_positions.values())
            return AccountInfo(
                balance=self._sim_balance,
                equity=self._sim_balance + unrealized,
                currency="USD",
                trade_mode=0,
            )

        info = mt5.account_info()
        return AccountInfo(
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            free_margin=info.margin_free,
            currency=info.currency,
            login=info.login,
            server=info.server,
            trade_mode=info.trade_mode,
        )

    def get_bars(self, symbol: str, timeframe: str, count: int = 300) -> pd.DataFrame:
        """Fetch OHLC bars. Simulation generates synthetic data."""
        if self._sim_mode:
            return self._simulate_bars(symbol, count)

        from core.data_fetcher import _TF_MAP, _build_tf_map
        if not _TF_MAP:
            _build_tf_map()
        tf_const = _TF_MAP.get(timeframe.upper())
        if tf_const is None:
            raise ValueError(f"Unknown timeframe: {timeframe}")
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, count)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"Failed to get bars for {symbol} {timeframe}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df[["open", "high", "low", "close"]].astype(float)

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        if self._sim_mode:
            ps = 0.01 if "JPY" in symbol else 0.0001
            digits = 3 if "JPY" in symbol else 5
            return SymbolInfo(
                name=symbol,
                point=ps / 10,
                digits=digits,
                ask=1.1000 if "JPY" not in symbol else 150.00,
                bid=1.0998 if "JPY" not in symbol else 149.98,
            )

        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Symbol info not found: {symbol}")
        return SymbolInfo(
            name=info.name,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
            contract_size=info.trade_contract_size,
            point=info.point,
            digits=info.digits,
            ask=info.ask,
            bid=info.bid,
        )

    def send_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float,
        tp: float,
        price: float = 0.0,
    ) -> OrderResult:
        """Send a market order."""
        magic = self.cfg.execution.magic_number
        comment = self.cfg.execution.order_comment

        if self._sim_mode:
            ticket = self._sim_next_ticket
            self._sim_next_ticket += 1

            if price == 0.0:
                price = 1.1000 if "JPY" not in symbol else 150.00

            order_type = 0 if direction.upper() == "BUY" else 1
            pos = PositionInfo(
                ticket=ticket, symbol=symbol, type=order_type,
                volume=volume, price_open=price, sl=sl, tp=tp,
                magic=magic, comment=comment,
            )
            self._sim_positions[ticket] = pos

            # Record entry deal
            self._sim_deals.append(DealInfo(
                ticket=ticket, order=ticket, symbol=symbol,
                type=order_type, entry=DEAL_ENTRY_IN,
                volume=volume, price=price, magic=magic, comment=comment,
            ))

            logger.info(f"[SIM] Order opened: {direction} {volume} {symbol} @ {price}")
            return OrderResult(
                success=True, order_id=ticket, volume=volume,
                price=price, comment=comment,
            )

        # Real MT5 order
        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        if price == 0.0:
            price = tick.ask if direction.upper() == "BUY" else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": self.cfg.execution.slippage_points,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else -1
            return OrderResult(success=False, retcode=retcode, comment=str(result))

        return OrderResult(
            success=True, order_id=result.order,
            volume=result.volume, price=result.price,
        )

    def close_position(self, ticket: int) -> OrderResult:
        """Close a position by ticket."""
        if self._sim_mode:
            pos = self._sim_positions.pop(ticket, None)
            if pos is None:
                return OrderResult(success=False, comment="Position not found")

            # Record close deal
            self._sim_deals.append(DealInfo(
                ticket=self._sim_next_ticket, order=ticket, symbol=pos.symbol,
                type=1 - pos.type, entry=DEAL_ENTRY_OUT,
                volume=pos.volume, price=pos.price_open, profit=pos.profit,
                magic=pos.magic, comment="close",
            ))
            self._sim_next_ticket += 1
            self._sim_balance += pos.profit

            logger.info(f"[SIM] Position {ticket} closed, PnL={pos.profit:.2f}")
            return OrderResult(success=True, order_id=ticket)

        # Real MT5 close
        pos_info = None
        positions = mt5.positions_get(ticket=ticket)
        if positions:
            pos_info = positions[0]
        if pos_info is None:
            return OrderResult(success=False, comment="Position not found")

        close_type = mt5.ORDER_TYPE_SELL if pos_info.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos_info.symbol)
        price = tick.bid if pos_info.type == 0 else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos_info.symbol,
            "volume": pos_info.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": self.cfg.execution.slippage_points,
            "magic": self.cfg.execution.magic_number,
            "comment": "close",
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(success=False, retcode=result.retcode if result else -1)
        return OrderResult(success=True, order_id=result.order)

    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        """Modify the stop loss of an open position."""
        if self._sim_mode:
            pos = self._sim_positions.get(ticket)
            if pos is None:
                return False
            pos.sl = new_sl
            logger.debug(f"[SIM] Modified SL for {ticket} -> {new_sl}")
            return True

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": ticket,
            "sl": new_sl,
            "tp": pos.tp,
            "magic": self.cfg.execution.magic_number,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

    def get_open_positions(self) -> List[PositionInfo]:
        """Get all open positions filtered by magic number."""
        magic = self.cfg.execution.magic_number

        if self._sim_mode:
            return [p for p in self._sim_positions.values() if p.magic == magic]

        positions = mt5.positions_get()
        if positions is None:
            return []
        return [
            PositionInfo(
                ticket=p.ticket, symbol=p.symbol, type=p.type,
                volume=p.volume, price_open=p.price_open,
                sl=p.sl, tp=p.tp, profit=p.profit,
                magic=p.magic, comment=p.comment,
            )
            for p in positions if p.magic == magic
        ]

    def get_deal_history(self, hours_back: int = 24) -> List[DealInfo]:
        """Get deal history for recent trades."""
        if self._sim_mode:
            return list(self._sim_deals)

        from_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        to_time = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(from_time, to_time)
        if deals is None:
            return []

        magic = self.cfg.execution.magic_number
        return [
            DealInfo(
                ticket=d.ticket, order=d.order, symbol=d.symbol,
                type=d.type, entry=d.entry, volume=d.volume,
                price=d.price, profit=d.profit, commission=d.commission,
                swap=d.swap, magic=d.magic, comment=d.comment,
            )
            for d in deals if d.magic == magic
        ]

    def close_all_positions(self) -> int:
        """Close all positions with our magic number. Returns count closed."""
        positions = self.get_open_positions()
        closed = 0
        for pos in positions:
            result = self.close_position(pos.ticket)
            if result.success:
                closed += 1
        logger.info(f"Closed {closed}/{len(positions)} positions")
        return closed

    # ── Simulation helpers ────────────────────────────────────────────────────

    def _simulate_bars(self, symbol: str, count: int) -> pd.DataFrame:
        """Generate synthetic OHLCV with bullish trend in last 80 bars."""
        cache_key = f"{symbol}_{count}"
        if cache_key in self._sim_bars_cache:
            return self._sim_bars_cache[cache_key]

        seed = sum(ord(c) for c in symbol)
        rng = np.random.RandomState(seed)

        base = 150.0 if "JPY" in symbol else 1.1000
        dates = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=count, freq="4h"
        )

        noise = rng.randn(count) * (0.05 if "JPY" in symbol else 0.0005)
        close = np.zeros(count)
        close[0] = base

        for i in range(1, count):
            drift = 0.0
            if i >= count - 80:
                drift = (0.02 if "JPY" in symbol else 0.0002)
            close[i] = close[i - 1] + noise[i] + drift

        spread = 0.03 if "JPY" in symbol else 0.0003
        high = close + rng.rand(count) * spread * 3
        low = close - rng.rand(count) * spread * 3
        open_ = close + rng.randn(count) * spread

        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close},
            index=dates,
        )
        self._sim_bars_cache[cache_key] = df
        return df
