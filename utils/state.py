"""
utils/state.py
─────────────────────────────────────────────────────────────────────────────
Thread-safe shared bot state for dashboard consumption.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class SignalSnapshot:
    symbol: str = ""
    signal: str = "NEUTRAL"
    close: float = 0.0
    tenkan: float = 0.0
    kijun: float = 0.0
    cloud_position: str = ""
    cloud_thickness: float = 0.0
    score: float = 1.0


@dataclass
class PositionSnapshot:
    ticket: int = 0
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    current_sl: float = 0.0
    unrealized_pnl: float = 0.0
    trailing_status: str = ""


@dataclass
class TradeRecord:
    order_id: int = 0
    symbol: str = ""
    direction: str = ""
    pnl: float = 0.0
    verification: str = ""
    exit_reason: str = ""


@dataclass
class BotSnapshot:
    """Immutable snapshot of bot state for the dashboard."""
    balance: float = 0.0
    equity: float = 0.0
    goal_progress_pct: float = 0.0
    signals: List[SignalSnapshot] = field(default_factory=list)
    positions: List[PositionSnapshot] = field(default_factory=list)
    recent_trades: List[TradeRecord] = field(default_factory=list)
    verification_stats: Dict[str, int] = field(default_factory=dict)
    log_lines: List[str] = field(default_factory=list)
    timestamp: str = ""
    is_halted: bool = False
    halt_reason: str = ""
    health_metrics: Dict[str, Any] = field(default_factory=dict)


class BotState:
    """Thread-safe mutable bot state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._balance: float = 0.0
        self._equity: float = 0.0
        self._start_balance: float = 0.0
        self._target_pct: float = 10.0
        self._signals: List[SignalSnapshot] = []
        self._positions: List[PositionSnapshot] = []
        self._trades: List[TradeRecord] = []
        self._verification_stats: Dict[str, int] = {
            "total": 0, "correct": 0, "incorrect": 0
        }
        self._failure_counts: Dict[str, int] = {}
        self._log_lines: List[str] = []
        self._is_halted: bool = False
        self._halt_reason: str = ""
        self._health_metrics: Dict[str, Any] = {}
        self._validation_metrics: Dict[str, Any] = {}

    def update_account(self, balance: float, equity: float) -> None:
        with self._lock:
            self._balance = balance
            self._equity = equity

    def set_start_balance(self, balance: float) -> None:
        with self._lock:
            self._start_balance = balance

    def set_target_pct(self, pct: float) -> None:
        with self._lock:
            self._target_pct = pct

    def update_signals(self, signals: List[SignalSnapshot]) -> None:
        with self._lock:
            self._signals = list(signals)

    def update_positions(self, positions: List[PositionSnapshot]) -> None:
        with self._lock:
            self._positions = list(positions)

    def add_trade(self, trade: TradeRecord) -> None:
        with self._lock:
            self._trades.append(trade)
            if len(self._trades) > 100:
                self._trades = self._trades[-100:]

    def update_verification_stats(self, stats: Dict[str, int], failures: Dict[str, int]) -> None:
        with self._lock:
            self._verification_stats = dict(stats)
            self._failure_counts = dict(failures)

    def add_log_line(self, line: str) -> None:
        with self._lock:
            self._log_lines.append(line)
            if len(self._log_lines) > 100:
                self._log_lines = self._log_lines[-100:]

    def set_halted(self, halted: bool, reason: str = "") -> None:
        with self._lock:
            self._is_halted = halted
            self._halt_reason = reason

    def update_health_metrics(self, metrics: Dict[str, Any]) -> None:
        with self._lock:
            self._health_metrics = dict(metrics)

    def update_validation_metrics(self, metrics: Dict[str, Any]) -> None:
        with self._lock:
            self._validation_metrics = dict(metrics)

    def snapshot(self) -> BotSnapshot:
        """Create an immutable snapshot for the dashboard."""
        with self._lock:
            progress = 0.0
            if self._start_balance > 0 and self._target_pct > 0:
                gain = (self._balance - self._start_balance) / self._start_balance * 100
                progress = min(gain / self._target_pct * 100, 100.0)

            stats = dict(self._verification_stats)
            stats.update({f"fail_{k}": v for k, v in self._failure_counts.items()})

            return BotSnapshot(
                balance=self._balance,
                equity=self._equity,
                goal_progress_pct=round(progress, 1),
                signals=list(self._signals),
                positions=list(self._positions),
                recent_trades=list(self._trades[-20:]),
                verification_stats=stats,
                log_lines=list(self._log_lines[-30:]),
                timestamp=datetime.now(timezone.utc).isoformat(),
                is_halted=self._is_halted,
                halt_reason=self._halt_reason,
                health_metrics=dict(self._health_metrics),
            )
