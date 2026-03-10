"""
core/risk_manager.py
─────────────────────────────────────────────────────────────────────────────
RiskGuard: pre-trade risk checks.

Checks: max_open_trades, duplicate_symbol, daily_loss_cap, max_drawdown,
goal_reached.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from loguru import logger

from core.config_loader import Config


@dataclass
class PositionInfo:
    """Minimal position info for risk checks."""
    symbol: str
    ticket: int = 0
    profit: float = 0.0
    volume: float = 0.0


class RiskGuard:
    """Pre-trade risk management checks."""

    def __init__(self, config: Config) -> None:
        self.cfg = config
        self._daily_closed_pnl: float = 0.0
        self._start_balance: float = 0.0
        self._halted: bool = False
        self._halt_reason: str = ""

    def set_start_balance(self, balance: float) -> None:
        self._start_balance = balance

    def reset_daily(self) -> None:
        """Reset daily loss counter (call at start of each trading day)."""
        self._daily_closed_pnl = 0.0

    def record_trade_close(self, pnl: float) -> None:
        """Record closed trade PnL for daily tracking."""
        self._daily_closed_pnl += pnl

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def can_trade(
        self,
        symbol: str,
        open_positions: List[PositionInfo],
        balance: float,
        equity: float,
    ) -> tuple[bool, str]:
        """
        Check all risk conditions before opening a new trade.

        Returns (can_trade, reason).
        """
        if self._halted:
            return False, f"Bot halted: {self._halt_reason}"

        rm = self.cfg.risk_management

        # 1. Max open trades
        if len(open_positions) >= rm.max_open_trades:
            return False, f"Max open trades reached ({rm.max_open_trades})"

        # 2. Duplicate symbol
        for pos in open_positions:
            if pos.symbol == symbol:
                return False, f"Position already open for {symbol}"

        # 3. Daily loss cap
        daily_cap = balance * rm.max_daily_loss_pct / 100.0
        if self._daily_closed_pnl <= -daily_cap:
            return False, (
                f"Daily loss cap reached: ${self._daily_closed_pnl:.2f} "
                f"(cap: -${daily_cap:.2f})"
            )

        # 4. Max drawdown
        if self._start_balance > 0:
            dd_pct = (self._start_balance - equity) / self._start_balance * 100
            if dd_pct >= rm.max_drawdown_pct:
                self._halted = True
                self._halt_reason = (
                    f"Max drawdown: {dd_pct:.1f}% >= {rm.max_drawdown_pct}%"
                )
                return False, self._halt_reason

        # 5. Goal reached
        if self._start_balance > 0:
            target = self._start_balance * (1 + self.cfg.goal.target_profit_pct / 100)
            if balance >= target:
                self._halted = True
                self._halt_reason = (
                    f"Goal reached: ${balance:.2f} >= target ${target:.2f}"
                )
                return False, self._halt_reason

        return True, "ok"
