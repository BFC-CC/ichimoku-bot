"""Tests for post-trade quality verification in core/action_verifier.py"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.action_verifier import ActionVerifier
from core.config_loader import (
    Config, ValidationConfig, QualityChecksConfig,
    RiskManagementConfig, IchimokuConfig,
)


def _make_verifier(
    max_slippage=3.0, min_fill=0.95, max_spread=5.0
) -> ActionVerifier:
    cfg = Config(
        pairs=["EURUSD"],
        validation=ValidationConfig(
            quality_checks=QualityChecksConfig(
                max_slippage_pips=max_slippage,
                min_fill_ratio=min_fill,
                max_spread_pips=max_spread,
            ),
        ),
    )
    mt5 = MagicMock()
    failed_logger = MagicMock()
    return ActionVerifier(cfg, mt5, failed_logger)


class TestPerfectQuality:
    def test_perfect_execution(self):
        v = _make_verifier()
        quality = v.verify_trade_quality({
            "expected_price": 1.10000,
            "execution_price": 1.10000,
            "requested_volume": 0.10,
            "filled_volume": 0.10,
            "spread_pips": 1.0,
            "symbol": "EURUSD",
        })
        assert quality >= 0.9

    def test_near_perfect(self):
        v = _make_verifier()
        quality = v.verify_trade_quality({
            "expected_price": 1.10000,
            "execution_price": 1.10001,  # 0.1 pip slip
            "requested_volume": 0.10,
            "filled_volume": 0.10,
            "spread_pips": 1.5,
            "symbol": "EURUSD",
        })
        assert quality >= 0.8


class TestHighSlippage:
    def test_high_slippage_low_score(self):
        v = _make_verifier(max_slippage=3.0)
        quality = v.verify_trade_quality({
            "expected_price": 1.10000,
            "execution_price": 1.10050,  # 5 pip slip > max 3
            "requested_volume": 0.10,
            "filled_volume": 0.10,
            "spread_pips": 1.0,
            "symbol": "EURUSD",
        })
        assert quality < 0.9

    def test_extreme_slippage(self):
        v = _make_verifier(max_slippage=3.0)
        quality = v.verify_trade_quality({
            "expected_price": 1.10000,
            "execution_price": 1.10100,  # 10 pip slip
            "requested_volume": 0.10,
            "filled_volume": 0.10,
            "spread_pips": 1.0,
            "symbol": "EURUSD",
        })
        assert quality < 0.7


class TestPartialFill:
    def test_partial_fill(self):
        v = _make_verifier(min_fill=0.95)
        quality = v.verify_trade_quality({
            "expected_price": 1.10000,
            "execution_price": 1.10000,
            "requested_volume": 0.10,
            "filled_volume": 0.08,  # 80% fill
            "spread_pips": 1.0,
            "symbol": "EURUSD",
        })
        assert quality < 0.95


class TestWideSpread:
    def test_wide_spread_low_score(self):
        v = _make_verifier(max_spread=5.0)
        quality = v.verify_trade_quality({
            "expected_price": 1.10000,
            "execution_price": 1.10000,
            "requested_volume": 0.10,
            "filled_volume": 0.10,
            "spread_pips": 8.0,  # > max 5
            "symbol": "EURUSD",
        })
        assert quality < 0.9

    def test_jpy_pair(self):
        v = _make_verifier()
        quality = v.verify_trade_quality({
            "expected_price": 150.000,
            "execution_price": 150.010,  # 1 pip on JPY
            "requested_volume": 0.10,
            "filled_volume": 0.10,
            "spread_pips": 2.0,
            "symbol": "USDJPY",
        })
        assert quality > 0.5
