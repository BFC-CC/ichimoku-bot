"""
tests/test_signals.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for SignalDetector.

Tests inject synthetic indicator dictionaries directly into the detector,
bypassing the indicator calculator, so every signal type can be tested
in isolation with precise control over the values.

Tests cover:
  - Each of the 6 signal types triggers correctly
  - Cloud filter suppresses TK cross when price is on the wrong side
  - Cooldown suppresses duplicate signals
  - NaN input skips signal checking
  - enabled_signals whitelist works
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

import pytest

from core.signal_detector import DetectorConfig, Signal, SignalDetector


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_time(hour: int = 10) -> datetime:
    return datetime(2024, 6, 1, hour, 0, 0, tzinfo=timezone.utc)


def base_indicators() -> dict:
    """Neutral indicators – no signal should fire from this baseline."""
    price = 1.1000
    cloud_top = 1.0980
    return {
        "close":        price,
        "prev_close":   price - 0.0001,
        "tenkan":       1.1005,
        "kijun":        1.1010,
        "prev_tenkan":  1.1004,
        "prev_kijun":   1.1010,
        "senkou_a":     cloud_top,
        "senkou_b":     1.0960,
        "prev_senkou_a": cloud_top,
        "prev_senkou_b": 1.0960,
        "cloud_top":     cloud_top,
        "cloud_bottom":  1.0960,
        "prev_cloud_top":    cloud_top,
        "prev_cloud_bottom": 1.0960,
        "chikou":      price,
        "prev_chikou": price,
    }


def detector_no_filter() -> SignalDetector:
    return SignalDetector(config=DetectorConfig(cooldown_minutes=0, cloud_filter=False))


def detector_with_filter() -> SignalDetector:
    return SignalDetector(config=DetectorConfig(cooldown_minutes=0, cloud_filter=True))


# ─────────────────────────────────────────────────────────────────────────────
#  TK Cross Up
# ─────────────────────────────────────────────────────────────────────────────

class TestTKCrossUp:

    def test_fires_on_cross(self):
        d = detector_no_filter()
        ind = base_indicators()
        # Tenkan crosses above Kijun
        ind["prev_tenkan"] = 1.1000
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1010
        ind["kijun"]       = 1.1005
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert any(s.signal_type == "tk_cross_up" for s in sigs)

    def test_no_fire_without_cross(self):
        d = detector_no_filter()
        ind = base_indicators()
        # Tenkan already above Kijun, no cross this candle
        ind["prev_tenkan"] = 1.1010
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1012
        ind["kijun"]       = 1.1005
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert not any(s.signal_type == "tk_cross_up" for s in sigs)

    def test_cloud_filter_suppresses_when_price_below_cloud(self):
        d = detector_with_filter()
        ind = base_indicators()
        # Cross happens but price is BELOW cloud
        ind["prev_tenkan"] = 1.0900
        ind["prev_kijun"]  = 1.0905
        ind["tenkan"]      = 1.0910
        ind["kijun"]       = 1.0905
        ind["close"]       = 1.0850   # below cloud_bottom
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert not any(s.signal_type == "tk_cross_up" for s in sigs)

    def test_cloud_filter_allows_when_price_above_cloud(self):
        d = detector_with_filter()
        ind = base_indicators()
        # Cross happens AND price is above cloud
        ind["prev_tenkan"] = 1.1000
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1010
        ind["kijun"]       = 1.1005
        ind["close"]       = 1.1050   # above cloud_top = 1.0980
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert any(s.signal_type == "tk_cross_up" for s in sigs)

    def test_direction_is_buy(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_tenkan"] = 1.1000
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1010
        ind["kijun"]       = 1.1005
        sigs = d.check("EURUSD", "H1", ind, make_time())
        tk_sig = next(s for s in sigs if s.signal_type == "tk_cross_up")
        assert tk_sig.direction == "BUY"


# ─────────────────────────────────────────────────────────────────────────────
#  TK Cross Down
# ─────────────────────────────────────────────────────────────────────────────

class TestTKCrossDown:

    def test_fires_on_cross(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_tenkan"] = 1.1010
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1000
        ind["kijun"]       = 1.1005
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert any(s.signal_type == "tk_cross_down" for s in sigs)

    def test_cloud_filter_suppresses_when_price_above_cloud(self):
        d = detector_with_filter()
        ind = base_indicators()
        ind["prev_tenkan"] = 1.1200
        ind["prev_kijun"]  = 1.1190
        ind["tenkan"]      = 1.1185
        ind["kijun"]       = 1.1190
        ind["close"]       = 1.1500   # above cloud – sell should be suppressed
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert not any(s.signal_type == "tk_cross_down" for s in sigs)

    def test_direction_is_sell(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_tenkan"] = 1.1010
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1000
        ind["kijun"]       = 1.1005
        sigs = d.check("EURUSD", "H1", ind, make_time())
        tk_sig = next(s for s in sigs if s.signal_type == "tk_cross_down")
        assert tk_sig.direction == "SELL"


# ─────────────────────────────────────────────────────────────────────────────
#  Kumo Breakout Up
# ─────────────────────────────────────────────────────────────────────────────

class TestKumoBreakoutUp:

    def test_fires_when_price_crosses_above_cloud(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_close"]       = 1.0970   # inside cloud
        ind["prev_cloud_top"]   = 1.0980
        ind["close"]            = 1.1010   # now above cloud
        ind["cloud_top"]        = 1.0980
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert any(s.signal_type == "kumo_breakout_up" for s in sigs)

    def test_no_fire_when_already_above_cloud(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_close"]     = 1.1100   # already above
        ind["prev_cloud_top"] = 1.0980
        ind["close"]          = 1.1110
        ind["cloud_top"]      = 1.0980
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert not any(s.signal_type == "kumo_breakout_up" for s in sigs)


# ─────────────────────────────────────────────────────────────────────────────
#  Kumo Breakout Down
# ─────────────────────────────────────────────────────────────────────────────

class TestKumoBreakoutDown:

    def test_fires_when_price_crosses_below_cloud(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_close"]          = 1.0970   # inside cloud
        ind["prev_cloud_bottom"]   = 1.0960
        ind["close"]               = 1.0940   # now below cloud
        ind["cloud_bottom"]        = 1.0960
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert any(s.signal_type == "kumo_breakout_down" for s in sigs)

    def test_direction_is_sell(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_close"]        = 1.0970
        ind["prev_cloud_bottom"] = 1.0960
        ind["close"]             = 1.0940
        ind["cloud_bottom"]      = 1.0960
        sigs = d.check("EURUSD", "H1", ind, make_time())
        sig = next(s for s in sigs if s.signal_type == "kumo_breakout_down")
        assert sig.direction == "SELL"


# ─────────────────────────────────────────────────────────────────────────────
#  Chikou Cross Up / Down
# ─────────────────────────────────────────────────────────────────────────────

class TestChikouCross:

    def test_chikou_cross_up_fires(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_chikou"] = 1.0990
        ind["prev_close"]  = 1.1000   # chikou was below prev_close
        ind["chikou"]      = 1.1010   # now above
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert any(s.signal_type == "chikou_cross_up" for s in sigs)

    def test_chikou_cross_down_fires(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["prev_chikou"] = 1.1010
        ind["prev_close"]  = 1.1000   # chikou was above prev_close
        ind["chikou"]      = 1.0990   # now below
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert any(s.signal_type == "chikou_cross_down" for s in sigs)


# ─────────────────────────────────────────────────────────────────────────────
#  Cooldown
# ─────────────────────────────────────────────────────────────────────────────

class TestCooldown:

    def _make_tk_cross_up_ind(self) -> dict:
        ind = base_indicators()
        ind["prev_tenkan"] = 1.1000
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1010
        ind["kijun"]       = 1.1005
        return ind

    def test_same_signal_suppressed_within_cooldown(self):
        d = SignalDetector(config=DetectorConfig(cooldown_minutes=30, cloud_filter=False))
        ind = self._make_tk_cross_up_ind()

        t1 = make_time(10)
        t2 = make_time(10) + timedelta(minutes=15)  # within cooldown

        sigs1 = d.check("EURUSD", "H1", ind, t1)
        sigs2 = d.check("EURUSD", "H1", ind, t2)

        assert any(s.signal_type == "tk_cross_up" for s in sigs1)
        assert not any(s.signal_type == "tk_cross_up" for s in sigs2)

    def test_signal_fires_after_cooldown_expires(self):
        d = SignalDetector(config=DetectorConfig(cooldown_minutes=30, cloud_filter=False))
        ind = self._make_tk_cross_up_ind()

        t1 = make_time(10)
        t2 = make_time(10) + timedelta(minutes=31)  # past cooldown

        d.check("EURUSD", "H1", ind, t1)
        sigs2 = d.check("EURUSD", "H1", ind, t2)

        assert any(s.signal_type == "tk_cross_up" for s in sigs2)

    def test_cooldown_is_per_signal_type(self):
        """Cooldown on tk_cross_up should not block kumo_breakout_up."""
        d = SignalDetector(config=DetectorConfig(cooldown_minutes=60, cloud_filter=False))

        # t1: only tk_cross_up fires – price is inside cloud so kumo breakout does NOT fire
        ind_t1 = self._make_tk_cross_up_ind()
        ind_t1["close"]          = 1.0970   # inside cloud, no kumo breakout
        ind_t1["prev_close"]     = 1.0965
        ind_t1["cloud_top"]      = 1.0980
        ind_t1["prev_cloud_top"] = 1.0980

        t1 = make_time(10)
        sigs1 = d.check("EURUSD", "H1", ind_t1, t1)
        assert any(s.signal_type == "tk_cross_up" for s in sigs1)
        assert not any(s.signal_type == "kumo_breakout_up" for s in sigs1)

        # t2: kumo breakout fires (price crossed above cloud); tk is still on cooldown
        ind_t2 = self._make_tk_cross_up_ind()
        ind_t2["prev_close"]     = 1.0970   # was inside cloud
        ind_t2["prev_cloud_top"] = 1.0980
        ind_t2["close"]          = 1.1010   # now above cloud → kumo fires
        ind_t2["cloud_top"]      = 1.0980

        t2 = make_time(10) + timedelta(minutes=5)
        sigs2 = d.check("EURUSD", "H1", ind_t2, t2)

        # kumo_breakout_up fires (its own independent cooldown)
        assert any(s.signal_type == "kumo_breakout_up" for s in sigs2)
        # tk_cross_up is still suppressed by its 60-min cooldown
        assert not any(s.signal_type == "tk_cross_up" for s in sigs2)


# ─────────────────────────────────────────────────────────────────────────────
#  NaN handling
# ─────────────────────────────────────────────────────────────────────────────

class TestNaNHandling:

    def test_nan_input_returns_empty(self):
        d = detector_no_filter()
        ind = base_indicators()
        ind["tenkan"] = float("nan")
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert sigs == []


# ─────────────────────────────────────────────────────────────────────────────
#  Enabled signals whitelist
# ─────────────────────────────────────────────────────────────────────────────

class TestEnabledSignals:

    def test_disabled_signal_does_not_fire(self):
        d = SignalDetector(
            config=DetectorConfig(cooldown_minutes=0, cloud_filter=False),
            enabled_signals={"kumo_breakout_up"},  # only kumo
        )
        ind = base_indicators()
        # Trigger TK cross – should not fire because it's disabled
        ind["prev_tenkan"] = 1.1000
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1010
        ind["kijun"]       = 1.1005
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert not any(s.signal_type == "tk_cross_up" for s in sigs)

    def test_only_enabled_signal_fires(self):
        d = SignalDetector(
            config=DetectorConfig(cooldown_minutes=0, cloud_filter=False),
            enabled_signals={"tk_cross_up"},
        )
        ind = base_indicators()
        ind["prev_tenkan"] = 1.1000
        ind["prev_kijun"]  = 1.1005
        ind["tenkan"]      = 1.1010
        ind["kijun"]       = 1.1005
        sigs = d.check("EURUSD", "H1", ind, make_time())
        assert any(s.signal_type == "tk_cross_up" for s in sigs)
        signal_types = {s.signal_type for s in sigs}
        assert signal_types.issubset({"tk_cross_up"})
