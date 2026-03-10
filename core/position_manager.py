"""
core/position_manager.py
─────────────────────────────────────────────────────────────────────────────
Orchestrates trailing stop, break-even, virtual TP, and ichimoku exit
conditions on all open positions each cycle.
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd
from loguru import logger

from core.config_loader import Config
from core.ichimoku_calculator import IchimokuValues, pip_size
from core.mt5_connector import PositionInfo
from core.order_executor import OrderExecutor
from core.break_even_manager import BreakEvenManager
from core.signal_engine import SignalEngine


class PositionManager:
    """Manage open positions: trailing, BE, virtual TP, ichimoku exits."""

    def __init__(
        self,
        config: Config,
        executor: OrderExecutor,
        be_manager: BreakEvenManager,
        signal_engine: SignalEngine,
    ) -> None:
        self.cfg = config
        self.executor = executor
        self.be_manager = be_manager
        self.signal_engine = signal_engine

    def manage_positions(
        self,
        positions: List[PositionInfo],
        ichi_by_symbol: dict[str, IchimokuValues],
        current_prices: dict[str, float],
    ) -> List[int]:
        """
        Check all open positions for trailing, BE, exits.

        Returns list of tickets that were closed.
        """
        closed_tickets: List[int] = []

        for pos in positions:
            symbol = pos.symbol
            ichi = ichi_by_symbol.get(symbol)
            price = current_prices.get(symbol, 0.0)

            if price == 0.0:
                continue

            # 1. Break-even check
            self.be_manager.check_and_apply(pos, price)

            # 2. Trailing stop
            self._check_trailing(pos, ichi, price)

            # 3. Virtual TP
            if self.cfg.ichimoku.use_virtual_tp and pos.tp > 0:
                is_buy = pos.type == 0
                if is_buy and price >= pos.tp:
                    result = self.executor.close_trade(pos.ticket)
                    if result.success:
                        closed_tickets.append(pos.ticket)
                        logger.info(f"Virtual TP hit: {symbol} #{pos.ticket}")
                    continue
                if not is_buy and price <= pos.tp:
                    result = self.executor.close_trade(pos.ticket)
                    if result.success:
                        closed_tickets.append(pos.ticket)
                        logger.info(f"Virtual TP hit: {symbol} #{pos.ticket}")
                    continue

            # 4. Ichimoku exit conditions
            if ichi is not None:
                direction = "BUY" if pos.type == 0 else "SELL"
                should_exit, reason = self.signal_engine.check_exit(ichi, direction)
                if should_exit:
                    result = self.executor.close_trade(pos.ticket)
                    if result.success:
                        closed_tickets.append(pos.ticket)
                        logger.info(f"Ichimoku exit: {symbol} #{pos.ticket} — {reason}")

        return closed_tickets

    def _check_trailing(
        self,
        pos: PositionInfo,
        ichi: Optional[IchimokuValues],
        current_price: float,
    ) -> None:
        """Apply trailing stop if configured."""
        ts_cfg = self.cfg.risk_management.trailing_stop
        if not ts_cfg.enabled:
            return

        ps = pip_size(pos.symbol)
        is_buy = pos.type == 0

        if ts_cfg.method == "kijun" and ichi is not None:
            buffer = self.cfg.risk_management.stop_loss.buffer_pips * ps
            if is_buy:
                new_sl = ichi.kijun - buffer
            else:
                new_sl = ichi.kijun + buffer
        elif ts_cfg.method == "fixed":
            trail_dist = ts_cfg.fixed_trail_pips * ps
            if is_buy:
                new_sl = current_price - trail_dist
            else:
                new_sl = current_price + trail_dist
        else:
            return

        # Only update if improvement >= trail_step_pips
        step = ts_cfg.trail_step_pips * ps
        if is_buy:
            improvement = new_sl - pos.sl
            if improvement < step:
                return
        else:
            if pos.sl == 0:
                improvement = step  # force first update
            else:
                improvement = pos.sl - new_sl
            if improvement < step:
                return

        self.executor.modify_stop_loss(pos.ticket, round(new_sl, 5))
        logger.debug(
            f"Trailing SL updated: {pos.symbol} #{pos.ticket} -> {new_sl:.5f} "
            f"(method={ts_cfg.method})"
        )
