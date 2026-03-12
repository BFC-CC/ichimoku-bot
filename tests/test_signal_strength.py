"""Tests for signal strength classification in core/signal_engine.py"""

from __future__ import annotations

import pytest

from core.signal_engine import classify_signal_strength


class TestClassifyStrong:
    def test_all_conditions_high_momentum(self):
        conditions = {
            "price_above_cloud": True,
            "chikou_clear": True,
            "tk_cross_occurred": True,
            "tk_above_kijun": True,
        }
        # pts: 2 + 2 + 1 + 1 + 2 = 8 (momentum > 70)
        result = classify_signal_strength(0.9, 75.0, conditions)
        assert result == "STRONG"

    def test_sell_side_strong(self):
        conditions = {
            "price_below_cloud": True,
            "chikou_clearance": True,
            "tk_cross_occurred": True,
            "tk_below_kijun": True,
        }
        result = classify_signal_strength(0.8, 80.0, conditions)
        assert result == "STRONG"


class TestClassifyModerate:
    def test_partial_conditions(self):
        conditions = {
            "price_above_cloud": True,
            "chikou_clear": False,
            "tk_cross_occurred": True,
        }
        # pts: 2 + 0 + 1 + 1 = 4 (momentum 55 > 50 -> +1 = 5)
        result = classify_signal_strength(0.7, 55.0, conditions)
        assert result == "MODERATE"

    def test_moderate_with_chikou_no_momentum(self):
        conditions = {
            "price_above_cloud": True,
            "chikou_clear": True,
        }
        # pts: 2 + 2 + 0 = 4, momentum 40 <= 50 -> 0 => total 4
        result = classify_signal_strength(0.5, 40.0, conditions)
        assert result == "MODERATE"


class TestClassifyWeak:
    def test_minimal_conditions(self):
        conditions = {
            "price_above_cloud": False,
            "chikou_clear": False,
            "tk_cross_occurred": True,
        }
        # pts: 0 + 0 + 1 + 0 = 1, momentum 30 -> 0 => total 1
        result = classify_signal_strength(0.3, 30.0, conditions)
        assert result == "WEAK"

    def test_empty_conditions(self):
        result = classify_signal_strength(0.5, 50.0, {})
        assert result == "WEAK"


class TestDefaultMomentum:
    def test_no_momentum_uses_neutral(self):
        """When momentum scoring disabled, use 50.0 as neutral default."""
        conditions = {
            "price_above_cloud": True,
            "chikou_clear": True,
            "tk_cross_occurred": True,
        }
        # pts: 2 + 2 + 1 + 0 = 5, momentum 50 <= 50 -> 0 => total 5
        result = classify_signal_strength(0.7, 50.0, conditions)
        assert result == "MODERATE"

    def test_boundary_strong(self):
        """Exactly 6 points should be STRONG."""
        conditions = {
            "price_above_cloud": True,
            "chikou_clear": True,
            "tk_cross_occurred": True,
            "tk_above_kijun": True,
        }
        # pts: 2 + 2 + 1 + 1 = 6, momentum 50 -> 0 => total 6
        result = classify_signal_strength(0.8, 50.0, conditions)
        assert result == "STRONG"

    def test_boundary_moderate(self):
        """Exactly 3 points should be MODERATE."""
        conditions = {
            "price_above_cloud": True,
            "tk_cross_occurred": True,
        }
        # pts: 2 + 0 + 1 = 3, momentum 30 -> 0 => total 3
        result = classify_signal_strength(0.5, 30.0, conditions)
        assert result == "MODERATE"
