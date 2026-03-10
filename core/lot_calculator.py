"""
core/lot_calculator.py
─────────────────────────────────────────────────────────────────────────────
Calculates position lot size based on risk parameters.

Modes: risk_pct (default), fixed, compound.
JPY-aware pip size. Rounds to volume_step, clamps to [volume_min, volume_max].
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from loguru import logger

from core.config_loader import RiskManagementConfig
from core.ichimoku_calculator import pip_size


@dataclass
class SymbolInfo:
    """Minimal symbol info needed for lot calculation."""
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    contract_size: float = 100_000.0
    name: str = ""


class LotCalculator:
    """Calculate lot sizes for trades."""

    def __init__(self, config: RiskManagementConfig) -> None:
        self.cfg = config

    def calculate(
        self,
        balance: float,
        entry: float,
        sl: float,
        symbol: str,
        symbol_info: SymbolInfo | None = None,
    ) -> float:
        """
        Calculate lot size based on configured lot_mode.

        Returns the lot size rounded to volume_step and clamped.
        """
        info = symbol_info or SymbolInfo(name=symbol)

        if self.cfg.lot_mode == "fixed":
            return self._clamp(self.cfg.fixed_lot_size, info)

        # risk_pct and compound both use the same formula
        # compound uses current balance (passed in), risk_pct uses it too
        ps = pip_size(symbol)
        pip_value_per_lot = info.contract_size * ps
        risk_pips = abs(entry - sl) / ps

        if risk_pips < 0.1:
            logger.warning(f"SL too close to entry ({risk_pips:.1f} pips), returning min lot")
            return info.volume_min

        risk_amount = balance * self.cfg.risk_per_trade_pct / 100.0
        lot_size = risk_amount / (risk_pips * pip_value_per_lot)

        lot_size = self._round_to_step(lot_size, info.volume_step)
        return self._clamp(lot_size, info)

    @staticmethod
    def _round_to_step(value: float, step: float) -> float:
        """Round down to the nearest volume step."""
        if step <= 0:
            return value
        return math.floor(value / step) * step

    @staticmethod
    def _clamp(value: float, info: SymbolInfo) -> float:
        """Clamp to [volume_min, volume_max]."""
        return max(info.volume_min, min(value, info.volume_max))
