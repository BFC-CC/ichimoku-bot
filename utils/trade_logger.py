"""
utils/trade_logger.py
─────────────────────────────────────────────────────────────────────────────
CSV appender for trades.csv — logs all closed trades (wins and losses).
"""

from __future__ import annotations

import csv
from pathlib import Path

from filelock import FileLock
from loguru import logger


TRADE_COLUMNS = [
    "order_id", "symbol", "action_type", "entry_price", "exit_price",
    "sl_price", "tp_price", "lot_size", "pnl_usd", "pnl_pips",
    "duration_minutes", "exit_reason", "signal_mode", "timeframe",
    "entry_bar_time", "verification_result", "risk_per_trade_usd",
    "risk_reward_planned", "risk_reward_actual",
    "account_balance_before", "account_balance_after", "running_profit_pct",
]


class TradeLogger:
    """Thread-safe CSV appender for all closed trades."""

    def __init__(self, log_dir: str = "logs") -> None:
        self._path = Path(log_dir) / "trades.csv"
        self._lock_path = Path(log_dir) / "trades.csv.lock"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, closed_trade, verification_result: str = "", **extra) -> None:
        """Append a closed trade record to CSV."""
        lock = FileLock(str(self._lock_path))
        with lock:
            write_header = not self._path.exists() or self._path.stat().st_size == 0
            with open(self._path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_COLUMNS)
                if write_header:
                    writer.writeheader()

                row = {
                    "order_id": getattr(closed_trade, "order_id", 0),
                    "symbol": getattr(closed_trade, "symbol", ""),
                    "action_type": getattr(closed_trade, "action_type", ""),
                    "entry_price": f"{getattr(closed_trade, 'entry_price', 0):.5f}",
                    "exit_price": f"{getattr(closed_trade, 'exit_price', 0):.5f}",
                    "sl_price": f"{getattr(closed_trade, 'sl_price', 0):.5f}",
                    "tp_price": f"{getattr(closed_trade, 'tp_price', 0):.5f}",
                    "lot_size": getattr(closed_trade, "lot_size", 0),
                    "pnl_usd": f"{getattr(closed_trade, 'pnl', 0):.2f}",
                    "pnl_pips": extra.get("pnl_pips", ""),
                    "duration_minutes": extra.get("duration_minutes", ""),
                    "exit_reason": getattr(closed_trade, "exit_reason", ""),
                    "signal_mode": extra.get("signal_mode", ""),
                    "timeframe": extra.get("timeframe", ""),
                    "entry_bar_time": str(getattr(closed_trade, "entry_time", "")),
                    "verification_result": verification_result,
                    "risk_per_trade_usd": extra.get("risk_per_trade_usd", ""),
                    "risk_reward_planned": extra.get("risk_reward_planned", ""),
                    "risk_reward_actual": extra.get("risk_reward_actual", ""),
                    "account_balance_before": extra.get("account_balance_before", ""),
                    "account_balance_after": extra.get("account_balance_after", ""),
                    "running_profit_pct": extra.get("running_profit_pct", ""),
                }
                writer.writerow(row)

        logger.debug(f"Trade logged: {row['symbol']} PnL={row['pnl_usd']}")

    @property
    def file_path(self) -> Path:
        return self._path
