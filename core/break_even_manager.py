"""
core/break_even_manager.py
─────────────────────────────────────────────────────────────────────────────
Move SL to entry + lock_in_pips when profit >= trigger_pips.
"""

from __future__ import annotations

from loguru import logger

from core.config_loader import BreakEvenConfig
from core.ichimoku_calculator import pip_size
from core.mt5_connector import PositionInfo
from core.order_executor import OrderExecutor


class BreakEvenManager:
    """Check and apply break-even on open positions."""

    def __init__(self, config: BreakEvenConfig, executor: OrderExecutor) -> None:
        self.cfg = config
        self.executor = executor
        self._be_applied: set[int] = set()  # tickets already at BE

    def check_and_apply(self, position: PositionInfo, current_price: float) -> bool:
        """
        Check if position qualifies for break-even and apply if so.

        Returns True if BE was applied this call.
        """
        if not self.cfg.enabled:
            return False

        if position.ticket in self._be_applied:
            return False

        ps = pip_size(position.symbol)
        is_buy = position.type == 0

        if is_buy:
            profit_pips = (current_price - position.price_open) / ps
        else:
            profit_pips = (position.price_open - current_price) / ps

        if profit_pips < self.cfg.trigger_pips:
            return False

        # Calculate new SL at entry + lock_in_pips
        lock_dist = self.cfg.lock_in_pips * ps
        if is_buy:
            new_sl = position.price_open + lock_dist
        else:
            new_sl = position.price_open - lock_dist

        # Only move if it's an improvement
        if is_buy and new_sl <= position.sl:
            return False
        if not is_buy and position.sl > 0 and new_sl >= position.sl:
            return False

        ok = self.executor.modify_stop_loss(position.ticket, round(new_sl, 5))
        if ok:
            self._be_applied.add(position.ticket)
            logger.info(
                f"Break-even applied: {position.symbol} #{position.ticket} "
                f"SL -> {new_sl:.5f} (profit {profit_pips:.1f} pips)"
            )
        return ok

    def on_position_closed(self, ticket: int) -> None:
        """Clean up tracking when a position is closed."""
        self._be_applied.discard(ticket)
