"""
core/signal_engine.py
─────────────────────────────────────────────────────────────────────────────
Routes signal evaluation to the correct Ichimoku mode (tk_cross, chikou_cross,
kumo_breakout, full_confirm). Returns SignalResult with BUY/SELL/NEUTRAL.

Also provides check_exit() for ichimoku-based position exit conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd
from loguru import logger

from core.config_loader import IchimokuConfig
from core.ichimoku_calculator import IchimokuValues, pip_size


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


@dataclass
class SignalResult:
    signal: Signal
    mode_used: str
    reasons: list[str] = field(default_factory=list)
    conditions_met: dict[str, bool] = field(default_factory=dict)
    bar_time: Optional[pd.Timestamp] = None
    ichi: Optional[IchimokuValues] = None


class SignalEngine:
    """Evaluate Ichimoku signals based on configured signal_mode."""

    def __init__(self, config: IchimokuConfig) -> None:
        self.cfg = config
        self._mode_map = {
            "tk_cross": self._tk_cross,
            "chikou_cross": self._chikou_cross,
            "kumo_breakout": self._kumo_breakout,
            "full_confirm": self._full_confirm,
        }

    def evaluate(self, ichi: IchimokuValues, df_closed: pd.DataFrame) -> SignalResult:
        """Route to the correct signal mode and return the result."""
        handler = self._mode_map.get(self.cfg.signal_mode)
        if handler is None:
            logger.error(f"Unknown signal_mode: {self.cfg.signal_mode}")
            return SignalResult(signal=Signal.NEUTRAL, mode_used=self.cfg.signal_mode)
        return handler(ichi, df_closed)

    def check_exit(
        self, ichi: IchimokuValues, position_direction: str
    ) -> tuple[bool, str]:
        """
        Check ichimoku exit conditions for an open position.

        Returns (should_exit, reason).
        """
        ec = self.cfg.exit_conditions
        is_buy = position_direction.upper() == "BUY"

        if ec.exit_on_tk_cross_against:
            if is_buy and ichi.tenkan < ichi.kijun and ichi.prev_tenkan >= ichi.prev_kijun:
                return True, "TK cross against (bearish)"
            if not is_buy and ichi.tenkan > ichi.kijun and ichi.prev_tenkan <= ichi.prev_kijun:
                return True, "TK cross against (bullish)"

        if ec.exit_on_price_enter_cloud:
            if is_buy and ichi.close < ichi.cloud_top:
                return True, "Price entered cloud (buy)"
            if not is_buy and ichi.close > ichi.cloud_bottom:
                return True, "Price entered cloud (sell)"

        if ec.exit_on_chikou_cross_down:
            chikou_ref = self._chikou_ref(df_closed=None, ichi=ichi)
            if is_buy and ichi.chikou < chikou_ref:
                return True, "Chikou crossed below reference"
            if not is_buy and ichi.chikou > chikou_ref:
                return True, "Chikou crossed above reference"

        return False, ""

    # ── Signal modes ──────────────────────────────────────────────────────────

    def _tk_cross(self, ichi: IchimokuValues, df: pd.DataFrame) -> SignalResult:
        """TK cross mode: fastest signal."""
        conditions: dict[str, bool] = {}
        reasons: list[str] = []

        # BUY check
        tk_bull = ichi.tenkan > ichi.kijun
        tk_cross_up = tk_bull and ichi.prev_tenkan <= ichi.prev_kijun
        price_above_cloud = ichi.close > ichi.cloud_top

        conditions["tk_above_kijun"] = tk_bull
        conditions["tk_cross_occurred"] = tk_cross_up
        conditions["price_above_cloud"] = price_above_cloud

        entry = self.cfg.entry_conditions
        buy_signal = tk_cross_up and price_above_cloud

        if entry.require_chikou_clear:
            chikou_ref = self._get_chikou_ref(df)
            chikou_clear = ichi.chikou > chikou_ref if chikou_ref is not None else True
            conditions["chikou_clear"] = chikou_clear
            buy_signal = buy_signal and chikou_clear

        if entry.require_bullish_cloud:
            bullish_cloud = ichi.senkou_a > ichi.senkou_b
            conditions["bullish_cloud"] = bullish_cloud
            buy_signal = buy_signal and bullish_cloud

        if buy_signal:
            reasons = [k for k, v in conditions.items() if v]
            return SignalResult(
                signal=Signal.BUY, mode_used="tk_cross",
                reasons=reasons, conditions_met=conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )

        # SELL check (mirror)
        tk_bear = ichi.tenkan < ichi.kijun
        tk_cross_dn = tk_bear and ichi.prev_tenkan >= ichi.prev_kijun
        price_below_cloud = ichi.close < ichi.cloud_bottom

        sell_conditions: dict[str, bool] = {
            "tk_below_kijun": tk_bear,
            "tk_cross_occurred": tk_cross_dn,
            "price_below_cloud": price_below_cloud,
        }

        sell_signal = tk_cross_dn and price_below_cloud

        if entry.require_chikou_clear:
            chikou_ref = self._get_chikou_ref(df)
            chikou_clear_sell = ichi.chikou < chikou_ref if chikou_ref is not None else True
            sell_conditions["chikou_clear"] = chikou_clear_sell
            sell_signal = sell_signal and chikou_clear_sell

        if entry.require_bullish_cloud:
            bearish_cloud = ichi.senkou_a < ichi.senkou_b
            sell_conditions["bearish_cloud"] = bearish_cloud
            sell_signal = sell_signal and bearish_cloud

        if sell_signal:
            reasons = [k for k, v in sell_conditions.items() if v]
            return SignalResult(
                signal=Signal.SELL, mode_used="tk_cross",
                reasons=reasons, conditions_met=sell_conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )

        return SignalResult(
            signal=Signal.NEUTRAL, mode_used="tk_cross",
            conditions_met=conditions, bar_time=ichi.bar_time, ichi=ichi,
        )

    def _chikou_cross(self, ichi: IchimokuValues, df: pd.DataFrame) -> SignalResult:
        """Chikou cross mode: strong confirmation."""
        chikou_ref = self._get_chikou_ref(df)
        prev_chikou_ref = self._get_chikou_ref(df, offset=1)

        if chikou_ref is None or prev_chikou_ref is None:
            return SignalResult(signal=Signal.NEUTRAL, mode_used="chikou_cross",
                                bar_time=ichi.bar_time, ichi=ichi)

        # BUY: chikou crosses above close[-26]
        chikou_cross_up = ichi.chikou > chikou_ref and ichi.prev_chikou <= prev_chikou_ref
        price_above_cloud = ichi.close > ichi.cloud_top

        conditions = {
            "chikou_cross_up": chikou_cross_up,
            "price_above_cloud": price_above_cloud,
        }

        if chikou_cross_up and price_above_cloud:
            return SignalResult(
                signal=Signal.BUY, mode_used="chikou_cross",
                reasons=[k for k, v in conditions.items() if v],
                conditions_met=conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )

        # SELL: chikou crosses below close[-26]
        chikou_cross_dn = ichi.chikou < chikou_ref and ichi.prev_chikou >= prev_chikou_ref
        price_below_cloud = ichi.close < ichi.cloud_bottom

        sell_conditions = {
            "chikou_cross_down": chikou_cross_dn,
            "price_below_cloud": price_below_cloud,
        }

        if chikou_cross_dn and price_below_cloud:
            return SignalResult(
                signal=Signal.SELL, mode_used="chikou_cross",
                reasons=[k for k, v in sell_conditions.items() if v],
                conditions_met=sell_conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )

        return SignalResult(signal=Signal.NEUTRAL, mode_used="chikou_cross",
                            conditions_met=conditions, bar_time=ichi.bar_time, ichi=ichi)

    def _kumo_breakout(self, ichi: IchimokuValues, df: pd.DataFrame) -> SignalResult:
        """Kumo breakout mode: trend continuation."""
        # BUY: prev close inside/below cloud, current above cloud top,
        # future cloud is bullish
        prev_inside_or_below = ichi.prev_close <= ichi.prev_cloud_top
        now_above = ichi.close > ichi.cloud_top
        future_bullish = ichi.future_span_a > ichi.future_span_b

        conditions = {
            "prev_inside_or_below_cloud": prev_inside_or_below,
            "price_above_cloud": now_above,
            "future_cloud_bullish": future_bullish,
        }

        if prev_inside_or_below and now_above and future_bullish:
            return SignalResult(
                signal=Signal.BUY, mode_used="kumo_breakout",
                reasons=[k for k, v in conditions.items() if v],
                conditions_met=conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )

        # SELL mirror
        prev_inside_or_above = ichi.prev_close >= ichi.prev_cloud_bottom
        now_below = ichi.close < ichi.cloud_bottom
        future_bearish = ichi.future_span_a < ichi.future_span_b

        sell_conditions = {
            "prev_inside_or_above_cloud": prev_inside_or_above,
            "price_below_cloud": now_below,
            "future_cloud_bearish": future_bearish,
        }

        if prev_inside_or_above and now_below and future_bearish:
            return SignalResult(
                signal=Signal.SELL, mode_used="kumo_breakout",
                reasons=[k for k, v in sell_conditions.items() if v],
                conditions_met=sell_conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )

        return SignalResult(signal=Signal.NEUTRAL, mode_used="kumo_breakout",
                            conditions_met=conditions, bar_time=ichi.bar_time, ichi=ichi)

    def _full_confirm(self, ichi: IchimokuValues, df: pd.DataFrame) -> SignalResult:
        """Full confirm mode: most conservative, all conditions required."""
        ps = pip_size("EURUSD")  # approximate for cloud thickness check
        min_thickness = self.cfg.cloud_min_thickness_pips

        # BUY conditions
        price_above_cloud = ichi.close > ichi.cloud_top
        tk_above = ichi.tenkan > ichi.kijun
        chikou_ref = self._get_chikou_ref(df)
        chikou_clear = ichi.chikou > chikou_ref if chikou_ref is not None else False
        bullish_cloud = ichi.senkou_a > ichi.senkou_b
        thick_enough = ichi.cloud_thickness_pips >= min_thickness

        conditions = {
            "price_above_cloud": price_above_cloud,
            "tk_above_kijun": tk_above,
            "chikou_clear": chikou_clear,
            "bullish_cloud": bullish_cloud,
            "cloud_thick_enough": thick_enough,
        }

        if all(conditions.values()):
            return SignalResult(
                signal=Signal.BUY, mode_used="full_confirm",
                reasons=[k for k, v in conditions.items() if v],
                conditions_met=conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )

        # SELL mirror
        price_below_cloud = ichi.close < ichi.cloud_bottom
        tk_below = ichi.tenkan < ichi.kijun
        chikou_below = ichi.chikou < chikou_ref if chikou_ref is not None else False
        bearish_cloud = ichi.senkou_a < ichi.senkou_b

        sell_conditions = {
            "price_below_cloud": price_below_cloud,
            "tk_below_kijun": tk_below,
            "chikou_below": chikou_below,
            "bearish_cloud": bearish_cloud,
            "cloud_thick_enough": thick_enough,
        }

        if all(sell_conditions.values()):
            return SignalResult(
                signal=Signal.SELL, mode_used="full_confirm",
                reasons=[k for k, v in sell_conditions.items() if v],
                conditions_met=sell_conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )

        return SignalResult(signal=Signal.NEUTRAL, mode_used="full_confirm",
                            conditions_met=conditions, bar_time=ichi.bar_time, ichi=ichi)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_chikou_ref(self, df: pd.DataFrame, offset: int = 0) -> Optional[float]:
        """Get the close price 26 bars ago (chikou reference)."""
        disp = self.cfg.displacement
        idx = len(df) - 1 - offset
        ref_idx = idx - disp
        if ref_idx < 0:
            return None
        col = "close" if "close" in df.columns else "Close"
        if col not in df.columns:
            df_lower = df.copy()
            df_lower.columns = [c.lower() for c in df_lower.columns]
            col = "close"
            return float(df_lower.iloc[ref_idx][col])
        return float(df.iloc[ref_idx][col])

    def _chikou_ref(
        self, df_closed: Optional[pd.DataFrame], ichi: IchimokuValues
    ) -> float:
        """Fallback chikou reference using prev_close when df not available."""
        return ichi.prev_close
