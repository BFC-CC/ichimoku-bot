"""
core/order_executor.py
─────────────────────────────────────────────────────────────────────────────
Sends orders via MT5Connector with retry logic and magic number enforcement.
"""

from __future__ import annotations

import time

from loguru import logger

from core.config_loader import Config
from core.mt5_connector import MT5Connector, OrderResult


class OrderExecutor:
    """Execute trades with retry logic."""

    def __init__(self, config: Config, connector: MT5Connector) -> None:
        self.cfg = config
        self.mt5 = connector

    def open_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float,
        tp: float,
        price: float = 0.0,
    ) -> OrderResult:
        """
        Open a trade with retry logic.

        Returns OrderResult with success/failure details.
        """
        exec_cfg = self.cfg.execution
        max_attempts = exec_cfg.retry_attempts
        delay_sec = exec_cfg.retry_delay_ms / 1000.0

        for attempt in range(1, max_attempts + 1):
            result = self.mt5.send_order(
                symbol=symbol,
                direction=direction,
                volume=volume,
                sl=sl,
                tp=tp,
                price=price,
            )

            if result.success:
                logger.info(
                    f"Trade opened: {direction} {volume} {symbol} @ {result.price} "
                    f"SL={sl} TP={tp} (attempt {attempt})"
                )
                return result

            logger.warning(
                f"Order failed (attempt {attempt}/{max_attempts}): "
                f"retcode={result.retcode}, {result.comment}"
            )

            if attempt < max_attempts:
                time.sleep(delay_sec)

        logger.error(f"All {max_attempts} order attempts failed for {symbol}")
        return OrderResult(success=False, comment="All retry attempts exhausted")

    def close_trade(self, ticket: int) -> OrderResult:
        """Close an open position by ticket."""
        return self.mt5.close_position(ticket)

    def modify_stop_loss(self, ticket: int, new_sl: float) -> bool:
        """Modify the stop loss of an open position."""
        return self.mt5.modify_sl(ticket, new_sl)
