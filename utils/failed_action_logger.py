"""
utils/failed_action_logger.py
─────────────────────────────────────────────────────────────────────────────
Thread-safe CSV appender for failed trade action records.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from filelock import FileLock
from loguru import logger


COLUMNS = [
    "timestamp_utc", "order_id", "symbol", "action_type", "entry_price",
    "exit_price", "sl_price", "tp_price", "lot_size", "pnl_usd",
    "duration_minutes", "failure_type", "signal_mode", "timeframe",
    "entry_bar_time", "tenkan_at_entry", "kijun_at_entry",
    "cloud_top_at_entry", "cloud_bot_at_entry", "cloud_pips_at_entry",
    "d1_cloud_direction", "d1_price_vs_cloud", "session_utc_hour",
    "conditions_met", "risk_reward_planned", "risk_reward_actual",
    "account_balance_at_entry", "drawdown_pct_at_entry", "notes",
    "validation_layer", "rtr_score", "momentum_score",
]


@dataclass
class FailedActionRecord:
    timestamp_utc: str = ""
    order_id: int = 0
    symbol: str = ""
    action_type: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    lot_size: float = 0.0
    pnl_usd: float = 0.0
    duration_minutes: float = 0.0
    failure_type: str = ""
    signal_mode: str = ""
    timeframe: str = ""
    entry_bar_time: str = ""
    tenkan_at_entry: float = 0.0
    kijun_at_entry: float = 0.0
    cloud_top_at_entry: float = 0.0
    cloud_bot_at_entry: float = 0.0
    cloud_pips_at_entry: float = 0.0
    d1_cloud_direction: str = ""
    d1_price_vs_cloud: str = ""
    session_utc_hour: int = 0
    conditions_met: str = ""
    risk_reward_planned: float = 0.0
    risk_reward_actual: float = 0.0
    account_balance_at_entry: float = 0.0
    drawdown_pct_at_entry: float = 0.0
    notes: str = ""
    validation_layer: str = ""
    rtr_score: float = 0.0
    momentum_score: float = 0.0


class FailedActionLogger:
    """Thread-safe CSV appender for failed actions."""

    def __init__(self, log_dir: str = "logs") -> None:
        self._path = Path(log_dir) / "failed_actions.csv"
        self._lock_path = Path(log_dir) / "failed_actions.csv.lock"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: FailedActionRecord) -> None:
        """Append a record to the CSV file (thread-safe)."""
        lock = FileLock(str(self._lock_path))
        with lock:
            write_header = not self._path.exists() or self._path.stat().st_size == 0
            with open(self._path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=COLUMNS)
                if write_header:
                    writer.writeheader()
                row = asdict(record)
                # Format floats
                for key in row:
                    if isinstance(row[key], float):
                        if key in ("entry_price", "exit_price", "sl_price",
                                   "tp_price", "tenkan_at_entry", "kijun_at_entry",
                                   "cloud_top_at_entry", "cloud_bot_at_entry"):
                            row[key] = f"{row[key]:.5f}"
                        elif key in ("pnl_usd", "risk_reward_planned",
                                     "risk_reward_actual", "drawdown_pct_at_entry",
                                     "account_balance_at_entry", "cloud_pips_at_entry",
                                     "duration_minutes"):
                            row[key] = f"{row[key]:.2f}"
                writer.writerow(row)

        logger.debug(f"Failed action logged: {record.symbol} {record.failure_type}")

    @property
    def file_path(self) -> Path:
        return self._path
