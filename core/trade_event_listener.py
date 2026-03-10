"""
core/trade_event_listener.py
─────────────────────────────────────────────────────────────────────────────
Polls MT5 deal history, detects close events, triggers ActionVerifier.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from core.mt5_connector import MT5Connector, DealInfo, DEAL_ENTRY_OUT
from core.action_verifier import ActionVerifier, ClosedTrade


class TradeEventListener:
    """Detect trade close events and trigger verification."""

    def __init__(
        self,
        mt5: MT5Connector,
        verifier: ActionVerifier,
        trade_logger: Optional[object] = None,
    ) -> None:
        self.mt5 = mt5
        self.verifier = verifier
        self.trade_logger = trade_logger
        self._known_deals: set[int] = set()

    def poll(self) -> list[ClosedTrade]:
        """
        Poll for new close events. Call every cycle.

        Returns list of newly detected closed trades.
        """
        recent_deals = self.mt5.get_deal_history(hours_back=24)
        closed_trades: list[ClosedTrade] = []

        for deal in recent_deals:
            if deal.ticket in self._known_deals:
                continue

            self._known_deals.add(deal.ticket)

            if deal.entry != DEAL_ENTRY_OUT:
                continue

            closed_trade = self._build_closed_trade(deal)
            closed_trades.append(closed_trade)

            # Run verification
            result = self.verifier.verify(closed_trade)

            # Log trade if logger available
            if self.trade_logger and hasattr(self.trade_logger, "log"):
                self.trade_logger.log(closed_trade, result.result)

            logger.info(
                f"Trade event: {deal.symbol} closed, "
                f"PnL={deal.profit:.2f}, verification={result.result}"
            )

        return closed_trades

    @staticmethod
    def _build_closed_trade(deal: DealInfo) -> ClosedTrade:
        """Build a ClosedTrade from a DealInfo."""
        action = "BUY" if deal.type == 1 else "SELL"  # close type is opposite
        return ClosedTrade(
            order_id=deal.order,
            symbol=deal.symbol,
            action_type=action,
            exit_price=deal.price,
            lot_size=deal.volume,
            pnl=deal.profit,
            exit_reason=deal.comment or "unknown",
            exit_time=deal.time if isinstance(deal.time, datetime) else datetime.now(timezone.utc),
            magic=deal.magic,
            comment=deal.comment,
        )
