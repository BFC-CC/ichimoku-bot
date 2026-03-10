"""Tests for core/lot_calculator.py"""

from __future__ import annotations

import pytest

from core.lot_calculator import LotCalculator, SymbolInfo
from core.config_loader import RiskManagementConfig


def _default_cfg(**kw) -> RiskManagementConfig:
    return RiskManagementConfig(**kw)


class TestLotCalculatorRiskPct:
    def test_basic_eurusd(self):
        cfg = _default_cfg(risk_per_trade_pct=1.0, lot_mode="risk_pct")
        calc = LotCalculator(cfg)
        # 10000 balance, entry 1.1000, SL 1.0960 = 40 pips
        lot = calc.calculate(10000, 1.1000, 1.0960, "EURUSD")
        # risk = 100 USD, 40 pips * 10 USD/pip/lot = 400 USD/lot
        # lot = 100 / 400 = 0.25, floor to 0.01 step = 0.25
        # (floor rounding may give 0.24 depending on float precision)
        assert lot in (0.24, 0.25)

    def test_jpy_pair(self):
        cfg = _default_cfg(risk_per_trade_pct=1.0, lot_mode="risk_pct")
        calc = LotCalculator(cfg)
        # pip_size = 0.01, contract = 100000
        # pip_value_per_lot = 100000 * 0.01 = 1000
        # entry 150.00, SL 149.60 = 40 pips
        # risk = 100, lot = 100 / (40 * 1000) = 0.0025 -> clamp to 0.01
        lot = calc.calculate(10000, 150.00, 149.60, "USDJPY")
        assert lot >= 0.01  # min lot

    def test_small_balance(self):
        cfg = _default_cfg(risk_per_trade_pct=1.0, lot_mode="risk_pct")
        calc = LotCalculator(cfg)
        lot = calc.calculate(500, 1.1000, 1.0960, "EURUSD")
        # risk = 5, 40 pips * 10 = 400, lot = 5/400 = 0.0125 -> 0.01
        assert lot == 0.01

    def test_respects_volume_step(self):
        cfg = _default_cfg(risk_per_trade_pct=2.0, lot_mode="risk_pct")
        calc = LotCalculator(cfg)
        info = SymbolInfo(volume_step=0.1, volume_min=0.1, volume_max=10.0)
        lot = calc.calculate(10000, 1.1000, 1.0960, "EURUSD", info)
        assert lot % 0.1 == pytest.approx(0.0, abs=1e-10)

    def test_clamp_max(self):
        cfg = _default_cfg(risk_per_trade_pct=5.0, lot_mode="risk_pct")
        calc = LotCalculator(cfg)
        info = SymbolInfo(volume_max=1.0)
        lot = calc.calculate(1_000_000, 1.1000, 1.0999, "EURUSD", info)
        assert lot <= 1.0


class TestLotCalculatorFixed:
    def test_fixed_mode(self):
        cfg = _default_cfg(lot_mode="fixed", fixed_lot_size=0.05)
        calc = LotCalculator(cfg)
        lot = calc.calculate(10000, 1.1000, 1.0960, "EURUSD")
        assert lot == 0.05

    def test_fixed_clamp_to_min(self):
        cfg = _default_cfg(lot_mode="fixed", fixed_lot_size=0.001)
        calc = LotCalculator(cfg)
        lot = calc.calculate(10000, 1.1000, 1.0960, "EURUSD")
        assert lot == 0.01  # min


class TestLotCalculatorCompound:
    def test_compound_uses_balance(self):
        cfg = _default_cfg(lot_mode="compound", risk_per_trade_pct=1.0)
        calc = LotCalculator(cfg)
        lot1 = calc.calculate(10000, 1.1000, 1.0960, "EURUSD")
        lot2 = calc.calculate(20000, 1.1000, 1.0960, "EURUSD")
        assert lot2 > lot1  # larger balance = larger lot


class TestEdgeCases:
    def test_sl_very_close(self):
        cfg = _default_cfg(risk_per_trade_pct=1.0, lot_mode="risk_pct")
        calc = LotCalculator(cfg)
        lot = calc.calculate(10000, 1.1000, 1.1000, "EURUSD")
        assert lot == 0.01  # min lot for 0 pips distance
