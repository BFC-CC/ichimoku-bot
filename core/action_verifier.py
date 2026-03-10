"""
core/action_verifier.py
─────────────────────────────────────────────────────────────────────────────
Post-close trade verification. Scores CORRECT/INCORRECT and classifies
failure types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from core.config_loader import Config
from core.mt5_connector import MT5Connector
from utils.failed_action_logger import FailedActionLogger, FailedActionRecord


@dataclass
class ClosedTrade:
    """Info about a closed trade for verification."""
    order_id: int = 0
    symbol: str = ""
    action_type: str = ""  # BUY or SELL
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    lot_size: float = 0.0
    pnl: float = 0.0
    exit_reason: str = ""
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    magic: int = 0
    comment: str = ""


@dataclass
class VerificationResult:
    result: str  # "CORRECT" or "INCORRECT:type"
    failure_type: str = ""  # SL_HIT, AGAINST_D1_TREND, etc.
    pnl: float = 0.0


class ActionVerifier:
    """Verify closed trades and log failures."""

    def __init__(
        self,
        config: Config,
        mt5: MT5Connector,
        failed_logger: FailedActionLogger,
    ) -> None:
        self.cfg = config
        self.mt5 = mt5
        self.failed_logger = failed_logger
        self._stats = {"correct": 0, "incorrect": 0, "total": 0}
        self._failure_counts: dict[str, int] = {}

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    @property
    def failure_counts(self) -> dict[str, int]:
        return dict(self._failure_counts)

    def verify(self, closed_trade: ClosedTrade) -> VerificationResult:
        """
        Score a closed trade. PnL >= 0 → CORRECT, < 0 → INCORRECT.
        """
        self._stats["total"] += 1

        if closed_trade.pnl >= 0:
            self._stats["correct"] += 1
            logger.info(
                f"Trade CORRECT: {closed_trade.symbol} #{closed_trade.order_id} "
                f"PnL={closed_trade.pnl:.2f}"
            )
            return VerificationResult(result="CORRECT", pnl=closed_trade.pnl)

        # INCORRECT — classify failure
        self._stats["incorrect"] += 1
        failure_type = self._classify_failure(closed_trade)
        self._failure_counts[failure_type] = self._failure_counts.get(failure_type, 0) + 1

        result_str = f"INCORRECT:{failure_type}"
        logger.warning(
            f"Trade INCORRECT: {closed_trade.symbol} #{closed_trade.order_id} "
            f"PnL={closed_trade.pnl:.2f} type={failure_type}"
        )

        # Build and log failed action record
        record = self._build_record(closed_trade, failure_type)
        self.failed_logger.append(record)

        return VerificationResult(
            result=result_str, failure_type=failure_type, pnl=closed_trade.pnl
        )

    def _classify_failure(self, trade: ClosedTrade) -> str:
        """Classify the failure type (checked in order)."""
        # 1. SL_HIT is the primary classification
        if trade.exit_reason == "sl":
            # Check if against D1 trend
            # (simplified: would need D1 bars to fully check)
            return "SL_HIT"

        # 2. Check session anomaly
        if trade.entry_time:
            hour = trade.entry_time.hour
            sf = self.cfg.session_filter
            if sf.enabled and (hour < sf.start_hour_utc or hour >= sf.end_hour_utc):
                return "SESSION_ANOMALY"

        # 3. Weak signal (would need entry bar data to fully verify)
        if trade.exit_reason in ("trailing", "ichimoku_exit"):
            return "WEAK_SIGNAL"

        # 4. Default
        return "SL_HIT"

    def _build_record(
        self, trade: ClosedTrade, failure_type: str
    ) -> FailedActionRecord:
        """Build a FailedActionRecord from a closed trade."""
        now = datetime.now(timezone.utc)
        duration = 0.0
        if trade.entry_time and trade.exit_time:
            duration = (trade.exit_time - trade.entry_time).total_seconds() / 60.0

        sl_dist = abs(trade.entry_price - trade.sl_price) if trade.sl_price else 0
        tp_dist = abs(trade.tp_price - trade.entry_price) if trade.tp_price else 0
        rr_planned = tp_dist / sl_dist if sl_dist > 0 else 0
        actual_dist = abs(trade.exit_price - trade.entry_price)
        rr_actual = actual_dist / sl_dist if sl_dist > 0 else 0

        return FailedActionRecord(
            timestamp_utc=now.strftime("%Y-%m-%d %H:%M:%S"),
            order_id=trade.order_id,
            symbol=trade.symbol,
            action_type=trade.action_type,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            sl_price=trade.sl_price,
            tp_price=trade.tp_price,
            lot_size=trade.lot_size,
            pnl_usd=trade.pnl,
            duration_minutes=duration,
            failure_type=failure_type,
            signal_mode=self.cfg.ichimoku.signal_mode,
            timeframe=self.cfg.timeframes.primary,
            entry_bar_time=str(trade.entry_time or ""),
            session_utc_hour=trade.entry_time.hour if trade.entry_time else 0,
            risk_reward_planned=rr_planned,
            risk_reward_actual=rr_actual,
        )
