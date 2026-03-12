"""
core/adversarial_validator.py
---------------------------------------------------------------------
Multi-critic adversarial validation for trade signals.

Three critics (logical, contextual, structural) each score 0-1.
The RTR score is their average. Signals below min_rtr_score are rejected.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from core.config_loader import ValidationConfig
from core.trend_filter import TrendFilter
from core.news_filter import NewsFilter


@dataclass
class SignalContext:
    """All data needed for adversarial validation of a signal."""
    symbol: str = ""
    direction: str = ""
    ichi: Any = None          # IchimokuValues
    df_closed: Any = None     # pd.DataFrame
    sltp: Any = None          # SLTPResult
    df_d1: Any = None         # Optional pd.DataFrame
    now_utc: Optional[datetime] = None
    signal_score: float = 0.0
    momentum_score: float = 0.0


class ValidationMetrics:
    """Thread-safe counters for validation outcomes."""

    def __init__(self, max_window: int = 100) -> None:
        self._lock = threading.Lock()
        self._signals_validated = 0
        self._signals_rejected = 0
        self._rejection_breakdown: dict[str, int] = {}
        self._rtr_scores: deque[float] = deque(maxlen=max_window)
        self._latencies_ms: deque[float] = deque(maxlen=max_window)

    def record_validation(
        self,
        passed: bool,
        rtr_score: float,
        latency_ms: float,
        rejected_by: str = "",
    ) -> None:
        with self._lock:
            if passed:
                self._signals_validated += 1
            else:
                self._signals_rejected += 1
                if rejected_by:
                    self._rejection_breakdown[rejected_by] = (
                        self._rejection_breakdown.get(rejected_by, 0) + 1
                    )
            self._rtr_scores.append(rtr_score)
            self._latencies_ms.append(latency_ms)

    def get_metrics(self) -> dict:
        with self._lock:
            total = self._signals_validated + self._signals_rejected
            avg_rtr = (
                sum(self._rtr_scores) / len(self._rtr_scores)
                if self._rtr_scores else 0.0
            )
            avg_latency = (
                sum(self._latencies_ms) / len(self._latencies_ms)
                if self._latencies_ms else 0.0
            )
            return {
                "enabled": True,
                "signals_validated": self._signals_validated,
                "signals_rejected": self._signals_rejected,
                "total_evaluated": total,
                "pass_rate": (
                    self._signals_validated / total if total > 0 else 0.0
                ),
                "rejection_breakdown": dict(self._rejection_breakdown),
                "avg_rtr_score": round(avg_rtr, 4),
                "avg_latency_ms": round(avg_latency, 2),
            }


class AdversarialValidator:
    """
    Multi-critic signal validator.

    Three critics score a signal 0-1 each. The RTR (readiness-to-risk) score
    is their average. Signals below config.min_rtr_score are rejected.
    """

    def __init__(
        self,
        config: ValidationConfig,
        trend_filter: TrendFilter,
        news_filter: NewsFilter,
    ) -> None:
        self.cfg = config
        self.trend_filter = trend_filter
        self.news_filter = news_filter
        self.metrics = ValidationMetrics()

    def validate(self, ctx: SignalContext) -> dict:
        """
        Validate a signal through all critics.

        Returns {"passed": bool, "rtr_score": float, "details": dict}
        """
        t0 = time.monotonic()

        logical_score, logical_reason = self._logical_critic(ctx)
        contextual_score, contextual_reason = self._contextual_critic(ctx)
        structural_score, structural_reason = self._structural_critic(ctx)

        rtr_score = (logical_score + contextual_score + structural_score) / 3.0
        passed = rtr_score >= self.cfg.min_rtr_score

        latency_ms = (time.monotonic() - t0) * 1000.0

        details = {
            "logical": {"score": round(logical_score, 4), "reason": logical_reason},
            "contextual": {"score": round(contextual_score, 4), "reason": contextual_reason},
            "structural": {"score": round(structural_score, 4), "reason": structural_reason},
        }

        # Determine which critic caused rejection
        rejected_by = ""
        if not passed:
            min_critic = min(
                details.items(), key=lambda x: x[1]["score"]
            )
            rejected_by = min_critic[0]

        self.metrics.record_validation(passed, rtr_score, latency_ms, rejected_by)

        return {
            "passed": passed,
            "rtr_score": round(rtr_score, 4),
            "details": details,
        }

    def _logical_critic(self, ctx: SignalContext) -> tuple[float, str]:
        """
        D1 trend alignment check.

        D1 confirms direction: 1.0
        D1 data unavailable: 0.5
        D1 contradicts: 0.0
        """
        if ctx.df_d1 is None or len(ctx.df_d1) < 79:
            return 0.5, "D1 data unavailable"

        confirmed, reason = self.trend_filter.confirms_direction(
            ctx.df_d1, ctx.symbol, ctx.direction
        )
        if confirmed:
            return 1.0, f"D1 confirms: {reason}"
        return 0.0, f"D1 contradicts: {reason}"

    def _contextual_critic(self, ctx: SignalContext) -> tuple[float, str]:
        """
        News and signal quality context check.

        News clear: 1.0 | News blocked: 0.0 | No timestamp: 0.8
        Penalize if signal_score < 0.4: subtract 0.3
        """
        if ctx.now_utc is None:
            score = 0.8
            reason = "No timestamp provided"
        else:
            is_clear, news_reason = self.news_filter.is_clear(ctx.symbol, ctx.now_utc)
            if is_clear:
                score = 1.0
                reason = "News clear"
            else:
                score = 0.0
                reason = f"News blocked: {news_reason}"

        if ctx.signal_score < 0.4:
            score = max(score - 0.3, 0.0)
            reason += f" | weak signal ({ctx.signal_score:.2f})"

        return score, reason

    def _structural_critic(self, ctx: SignalContext) -> tuple[float, str]:
        """
        SL/TP placement quality check.

        - SL beyond cloud boundary: +0.5
        - SL beyond recent swing: +0.3
        - R:R >= 1.5: +0.2
        """
        score = 0.0
        reasons: list[str] = []

        if ctx.sltp is None or ctx.ichi is None:
            return 0.5, "No SLTP data"

        is_buy = ctx.direction.upper() == "BUY"

        # Check SL vs cloud boundary
        if is_buy:
            if ctx.sltp.sl < ctx.ichi.cloud_bottom:
                score += 0.5
                reasons.append("SL below cloud")
        else:
            if ctx.sltp.sl > ctx.ichi.cloud_top:
                score += 0.5
                reasons.append("SL above cloud")

        # Check SL vs recent swing (last 10 bars)
        if ctx.df_closed is not None and len(ctx.df_closed) >= 10:
            df_norm = ctx.df_closed.copy()
            df_norm.columns = [c.lower() for c in df_norm.columns]
            recent = df_norm.iloc[-10:]

            if is_buy:
                recent_low = float(recent["low"].min())
                if ctx.sltp.sl < recent_low:
                    score += 0.3
                    reasons.append("SL below swing low")
            else:
                recent_high = float(recent["high"].max())
                if ctx.sltp.sl > recent_high:
                    score += 0.3
                    reasons.append("SL above swing high")

        # Check R:R ratio
        if ctx.sltp.sl_pips > 0:
            rr = ctx.sltp.tp_pips / ctx.sltp.sl_pips
            if rr >= 1.5:
                score += 0.2
                reasons.append(f"R:R={rr:.1f}")

        score = min(score, 1.0)
        return score, " | ".join(reasons) if reasons else "No structural criteria met"
