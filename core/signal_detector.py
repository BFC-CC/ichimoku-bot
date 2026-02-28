"""
core/signal_detector.py
─────────────────────────────────────────────────────────────────────────────
Evaluates Ichimoku indicator values and emits Signal objects when a
trading condition is met.

Six signal types are supported:

  BUY signals
  ───────────
  tk_cross_up      – Tenkan crosses above Kijun (+ optional cloud filter)
  kumo_breakout_up – Close crosses above the cloud top
  chikou_cross_up  – Chikou crosses above the close from 26 bars ago

  SELL signals
  ────────────
  tk_cross_down       – Tenkan crosses below Kijun (+ optional cloud filter)
  kumo_breakout_down  – Close crosses below the cloud bottom
  chikou_cross_down   – Chikou crosses below the close from 26 bars ago

Each (pair, timeframe, signal_type) combination has its own independent
cooldown timer so signals don't fire repeatedly on the same condition.

Usage
-----
    from core.signal_detector import SignalDetector, DetectorConfig
    detector = SignalDetector(DetectorConfig(cooldown_minutes=30, cloud_filter=True))
    signals  = detector.check(pair="EURUSD", timeframe="H1",
                              indicators=indicator.latest_values(buffer.data),
                              candle_time=candle.time)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger


# ─────────────────────────────────────────────────────────────────────────────
#  Signal dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    pair:        str
    timeframe:   str
    signal_type: str        # e.g. 'tk_cross_up', 'kumo_breakout_down'
    direction:   str        # 'BUY' or 'SELL'
    timestamp:   datetime
    price:       float
    details:     dict = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"[{self.direction}] {self.signal_type.upper()} | "
            f"{self.pair} {self.timeframe} | "
            f"price={self.price:.5f} | {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Detector configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DetectorConfig:
    cooldown_minutes: int = 30
    cloud_filter: bool = True      # TK cross only fires if price is on correct side of cloud
    strong_signal_only: bool = False  # future: require all three signals to align


# ─────────────────────────────────────────────────────────────────────────────
#  Main detector
# ─────────────────────────────────────────────────────────────────────────────

# Type alias for the cooldown dict key
_CooldownKey = Tuple[str, str, str]   # (pair, timeframe, signal_type)


class SignalDetector:
    """
    Stateful signal detector.  Maintains its own cooldown registry so it
    can be reused across many candles without external state management.

    Parameters
    ----------
    config : DetectorConfig
    enabled_signals : set of str, optional
        Whitelist of signal_type strings to evaluate.  If None, all six
        signal types are active.
    """

    ALL_SIGNALS: Set[str] = {
        "tk_cross_up", "tk_cross_down",
        "kumo_breakout_up", "kumo_breakout_down",
        "chikou_cross_up", "chikou_cross_down",
    }

    def __init__(
        self,
        config: Optional[DetectorConfig] = None,
        enabled_signals: Optional[Set[str]] = None,
    ):
        self.cfg = config or DetectorConfig()
        self.enabled = enabled_signals if enabled_signals is not None else self.ALL_SIGNALS
        self._last_signal_time: Dict[_CooldownKey, datetime] = {}

    # ── public API ────────────────────────────────────────────────────────────

    def check(
        self,
        pair: str,
        timeframe: str,
        indicators: Dict[str, float],
        candle_time: datetime,
    ) -> List[Signal]:
        """
        Evaluate all enabled signal rules against the provided indicator values.

        Parameters
        ----------
        pair        : e.g. 'EURUSD'
        timeframe   : e.g. 'H1'
        indicators  : dict from IchimokuIndicator.latest_values()
        candle_time : UTC datetime of the candle that just closed

        Returns
        -------
        List[Signal] – may be empty if no conditions are met or all are on cooldown.
        """
        if self._has_nan(indicators):
            logger.debug(f"{pair} {timeframe}: skipping – NaN values in indicators.")
            return []

        signals: List[Signal] = []

        rules = [
            ("tk_cross_up",         self._tk_cross_up),
            ("tk_cross_down",       self._tk_cross_down),
            ("kumo_breakout_up",    self._kumo_breakout_up),
            ("kumo_breakout_down",  self._kumo_breakout_down),
            ("chikou_cross_up",     self._chikou_cross_up),
            ("chikou_cross_down",   self._chikou_cross_down),
        ]

        for signal_type, rule_fn in rules:
            if signal_type not in self.enabled:
                continue

            fired, details = rule_fn(indicators)
            if not fired:
                continue

            if self._on_cooldown(pair, timeframe, signal_type, candle_time):
                logger.debug(f"Cooldown active: {pair} {timeframe} {signal_type}")
                continue

            direction = "BUY" if signal_type.endswith("_up") else "SELL"
            sig = Signal(
                pair=pair,
                timeframe=timeframe,
                signal_type=signal_type,
                direction=direction,
                timestamp=candle_time,
                price=indicators["close"],
                details=details,
            )
            signals.append(sig)
            self._record_signal(pair, timeframe, signal_type, candle_time)
            logger.info(f"Signal fired: {sig}")

        return signals

    def reset_cooldowns(self) -> None:
        """Clear all cooldown state – useful between backtest runs."""
        self._last_signal_time.clear()

    # ── signal rules ──────────────────────────────────────────────────────────

    def _tk_cross_up(self, ind: Dict) -> Tuple[bool, dict]:
        """Tenkan crosses above Kijun on this candle."""
        cross = (
            ind["prev_tenkan"] <= ind["prev_kijun"] and
            ind["tenkan"] > ind["kijun"]
        )
        if not cross:
            return False, {}

        # Optional cloud filter: price should be above the cloud for a BUY
        if self.cfg.cloud_filter and ind["close"] < ind["cloud_top"]:
            return False, {}

        return True, {
            "tenkan":    ind["tenkan"],
            "kijun":     ind["kijun"],
            "cloud_top": ind["cloud_top"],
        }

    def _tk_cross_down(self, ind: Dict) -> Tuple[bool, dict]:
        """Tenkan crosses below Kijun on this candle."""
        cross = (
            ind["prev_tenkan"] >= ind["prev_kijun"] and
            ind["tenkan"] < ind["kijun"]
        )
        if not cross:
            return False, {}

        if self.cfg.cloud_filter and ind["close"] > ind["cloud_bottom"]:
            return False, {}

        return True, {
            "tenkan":       ind["tenkan"],
            "kijun":        ind["kijun"],
            "cloud_bottom": ind["cloud_bottom"],
        }

    def _kumo_breakout_up(self, ind: Dict) -> Tuple[bool, dict]:
        """Price closes above the cloud after being at or below it."""
        was_outside_or_inside = ind["prev_close"] <= ind["prev_cloud_top"]
        now_above = ind["close"] > ind["cloud_top"]
        fired = was_outside_or_inside and now_above
        details = {"cloud_top": ind["cloud_top"]} if fired else {}
        return fired, details

    def _kumo_breakout_down(self, ind: Dict) -> Tuple[bool, dict]:
        """Price closes below the cloud after being at or above it."""
        was_outside_or_inside = ind["prev_close"] >= ind["prev_cloud_bottom"]
        now_below = ind["close"] < ind["cloud_bottom"]
        fired = was_outside_or_inside and now_below
        details = {"cloud_bottom": ind["cloud_bottom"]} if fired else {}
        return fired, details

    def _chikou_cross_up(self, ind: Dict) -> Tuple[bool, dict]:
        """
        Chikou (current close shifted back 26) crosses above the close
        that was recorded 26 bars ago.  In latest_values(), 'chikou' is
        the close of 26 bars ago's *future* candle, and 'prev_close' of
        that same shifted index is the prior close.

        Simpler interpretation: chikou > close_26_bars_ago, and on the
        previous step it was not.  Since chikou IS the current close shifted
        back, we compare:
            chikou     (= current close, placed on candle-26)
            prev_close (= close of candle 1 step before that reference point)
        """
        fired = (
            ind["prev_chikou"] <= ind["prev_close"] and
            ind["chikou"] > ind["prev_close"]
        )
        details = {"chikou": ind["chikou"], "ref_close": ind["prev_close"]} if fired else {}
        return fired, details

    def _chikou_cross_down(self, ind: Dict) -> Tuple[bool, dict]:
        fired = (
            ind["prev_chikou"] >= ind["prev_close"] and
            ind["chikou"] < ind["prev_close"]
        )
        details = {"chikou": ind["chikou"], "ref_close": ind["prev_close"]} if fired else {}
        return fired, details

    # ── cooldown helpers ──────────────────────────────────────────────────────

    def _on_cooldown(
        self, pair: str, timeframe: str, signal_type: str, now: datetime
    ) -> bool:
        key = (pair, timeframe, signal_type)
        last = self._last_signal_time.get(key)
        if last is None:
            return False
        delta = now - last
        return delta < timedelta(minutes=self.cfg.cooldown_minutes)

    def _record_signal(
        self, pair: str, timeframe: str, signal_type: str, now: datetime
    ) -> None:
        self._last_signal_time[(pair, timeframe, signal_type)] = now

    # ── utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _has_nan(indicators: Dict[str, float]) -> bool:
        return any(
            isinstance(v, float) and math.isnan(v)
            for v in indicators.values()
        )
