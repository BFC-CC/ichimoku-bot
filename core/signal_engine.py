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
from core.ichimoku_calculator import IchimokuValues, pip_size, is_chikou_clear


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
    score: float = 1.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    strength: str = ""
    momentum_score: float = 0.0


def classify_signal_strength(
    signal_score: float,
    momentum_score: float,
    conditions_met: dict[str, bool],
) -> str:
    """
    Classify signal as STRONG / MODERATE / WEAK based on a point system.

    Points:
    - price_above_cloud / price_below_cloud True: +2
    - chikou_clear / chikou_clearance True: +2
    - tk_cross_occurred True: +1; if also tk_above_kijun / tk_below_kijun: +1
    - momentum > 70: +2; > 50: +1
    - Sum >= 6: STRONG, >= 3: MODERATE, else: WEAK
    """
    pts = 0

    if conditions_met.get("price_above_cloud") or conditions_met.get("price_below_cloud"):
        pts += 2

    if conditions_met.get("chikou_clear") or conditions_met.get("chikou_clearance"):
        pts += 2

    if conditions_met.get("tk_cross_occurred"):
        pts += 1
        if conditions_met.get("tk_above_kijun") or conditions_met.get("tk_below_kijun"):
            pts += 1

    if momentum_score > 70:
        pts += 2
    elif momentum_score > 50:
        pts += 1

    if pts >= 6:
        return "STRONG"
    if pts >= 3:
        return "MODERATE"
    return "WEAK"


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
            clear, _margin = is_chikou_clear(
                df, "BUY", self.cfg.displacement, entry.chikou_clear_lookback
            )
            conditions["chikou_clear"] = clear
            buy_signal = buy_signal and clear

        if entry.require_bullish_cloud:
            bullish_cloud = ichi.senkou_a > ichi.senkou_b
            conditions["bullish_cloud"] = bullish_cloud
            buy_signal = buy_signal and bullish_cloud

        if buy_signal:
            reasons = [k for k, v in conditions.items() if v]
            result = SignalResult(
                signal=Signal.BUY, mode_used="tk_cross",
                reasons=reasons, conditions_met=conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )
            self._apply_score(result, ichi, df, "BUY")
            return result

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
            clear, _margin = is_chikou_clear(
                df, "SELL", self.cfg.displacement, entry.chikou_clear_lookback
            )
            sell_conditions["chikou_clear"] = clear
            sell_signal = sell_signal and clear

        if entry.require_bullish_cloud:
            bearish_cloud = ichi.senkou_a < ichi.senkou_b
            sell_conditions["bearish_cloud"] = bearish_cloud
            sell_signal = sell_signal and bearish_cloud

        if sell_signal:
            reasons = [k for k, v in sell_conditions.items() if v]
            result = SignalResult(
                signal=Signal.SELL, mode_used="tk_cross",
                reasons=reasons, conditions_met=sell_conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )
            self._apply_score(result, ichi, df, "SELL")
            return result

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

        buy_signal = chikou_cross_up and price_above_cloud

        entry = self.cfg.entry_conditions
        if buy_signal and entry.require_chikou_clear:
            clear, _ = is_chikou_clear(
                df, "BUY", self.cfg.displacement, entry.chikou_clear_lookback
            )
            conditions["chikou_clearance"] = clear
            buy_signal = buy_signal and clear

        if buy_signal:
            result = SignalResult(
                signal=Signal.BUY, mode_used="chikou_cross",
                reasons=[k for k, v in conditions.items() if v],
                conditions_met=conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )
            self._apply_score(result, ichi, df, "BUY")
            return result

        # SELL: chikou crosses below close[-26]
        chikou_cross_dn = ichi.chikou < chikou_ref and ichi.prev_chikou >= prev_chikou_ref
        price_below_cloud = ichi.close < ichi.cloud_bottom

        sell_conditions = {
            "chikou_cross_down": chikou_cross_dn,
            "price_below_cloud": price_below_cloud,
        }

        sell_signal = chikou_cross_dn and price_below_cloud

        if sell_signal and entry.require_chikou_clear:
            clear, _ = is_chikou_clear(
                df, "SELL", self.cfg.displacement, entry.chikou_clear_lookback
            )
            sell_conditions["chikou_clearance"] = clear
            sell_signal = sell_signal and clear

        if sell_signal:
            result = SignalResult(
                signal=Signal.SELL, mode_used="chikou_cross",
                reasons=[k for k, v in sell_conditions.items() if v],
                conditions_met=sell_conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )
            self._apply_score(result, ichi, df, "SELL")
            return result

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

        buy_signal = prev_inside_or_below and now_above and future_bullish

        entry = self.cfg.entry_conditions
        if buy_signal and entry.require_chikou_clear:
            clear, _ = is_chikou_clear(
                df, "BUY", self.cfg.displacement, entry.chikou_clear_lookback
            )
            conditions["chikou_clearance"] = clear
            buy_signal = buy_signal and clear

        if buy_signal:
            result = SignalResult(
                signal=Signal.BUY, mode_used="kumo_breakout",
                reasons=[k for k, v in conditions.items() if v],
                conditions_met=conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )
            self._apply_score(result, ichi, df, "BUY")
            return result

        # SELL mirror
        prev_inside_or_above = ichi.prev_close >= ichi.prev_cloud_bottom
        now_below = ichi.close < ichi.cloud_bottom
        future_bearish = ichi.future_span_a < ichi.future_span_b

        sell_conditions = {
            "prev_inside_or_above_cloud": prev_inside_or_above,
            "price_below_cloud": now_below,
            "future_cloud_bearish": future_bearish,
        }

        sell_signal = prev_inside_or_above and now_below and future_bearish

        if sell_signal and entry.require_chikou_clear:
            clear, _ = is_chikou_clear(
                df, "SELL", self.cfg.displacement, entry.chikou_clear_lookback
            )
            sell_conditions["chikou_clearance"] = clear
            sell_signal = sell_signal and clear

        if sell_signal:
            result = SignalResult(
                signal=Signal.SELL, mode_used="kumo_breakout",
                reasons=[k for k, v in sell_conditions.items() if v],
                conditions_met=sell_conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )
            self._apply_score(result, ichi, df, "SELL")
            return result

        return SignalResult(signal=Signal.NEUTRAL, mode_used="kumo_breakout",
                            conditions_met=conditions, bar_time=ichi.bar_time, ichi=ichi)

    def _full_confirm(self, ichi: IchimokuValues, df: pd.DataFrame) -> SignalResult:
        """Full confirm mode: most conservative, all conditions required."""
        ps = pip_size("EURUSD")  # approximate for cloud thickness check
        min_thickness = self.cfg.cloud_min_thickness_pips

        entry = self.cfg.entry_conditions

        # BUY conditions
        price_above_cloud = ichi.close > ichi.cloud_top
        tk_above = ichi.tenkan > ichi.kijun
        chikou_clear_buy, _ = is_chikou_clear(
            df, "BUY", self.cfg.displacement, entry.chikou_clear_lookback
        )
        bullish_cloud = ichi.senkou_a > ichi.senkou_b
        thick_enough = ichi.cloud_thickness_pips >= min_thickness

        conditions = {
            "price_above_cloud": price_above_cloud,
            "tk_above_kijun": tk_above,
            "chikou_clear": chikou_clear_buy,
            "bullish_cloud": bullish_cloud,
            "cloud_thick_enough": thick_enough,
        }

        if all(conditions.values()):
            result = SignalResult(
                signal=Signal.BUY, mode_used="full_confirm",
                reasons=[k for k, v in conditions.items() if v],
                conditions_met=conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )
            self._apply_score(result, ichi, df, "BUY")
            return result

        # SELL mirror
        price_below_cloud = ichi.close < ichi.cloud_bottom
        tk_below = ichi.tenkan < ichi.kijun
        chikou_clear_sell, _ = is_chikou_clear(
            df, "SELL", self.cfg.displacement, entry.chikou_clear_lookback
        )
        bearish_cloud = ichi.senkou_a < ichi.senkou_b

        sell_conditions = {
            "price_below_cloud": price_below_cloud,
            "tk_below_kijun": tk_below,
            "chikou_below": chikou_clear_sell,
            "bearish_cloud": bearish_cloud,
            "cloud_thick_enough": thick_enough,
        }

        if all(sell_conditions.values()):
            result = SignalResult(
                signal=Signal.SELL, mode_used="full_confirm",
                reasons=[k for k, v in sell_conditions.items() if v],
                conditions_met=sell_conditions,
                bar_time=ichi.bar_time, ichi=ichi,
            )
            self._apply_score(result, ichi, df, "SELL")
            return result

        return SignalResult(signal=Signal.NEUTRAL, mode_used="full_confirm",
                            conditions_met=conditions, bar_time=ichi.bar_time, ichi=ichi)

    # ── Scoring ──────────────────────────────────────────────────────────────

    def _apply_score(
        self, result: SignalResult, ichi: IchimokuValues, df: pd.DataFrame, direction: str
    ) -> None:
        """Compute and attach score to a non-NEUTRAL result."""
        scoring = self.cfg.signal_scoring
        if not scoring.enabled:
            return
        score, breakdown = self._compute_score(ichi, df, direction)
        result.score = score
        result.score_breakdown = breakdown

    def _compute_score(
        self, ichi: IchimokuValues, df: pd.DataFrame, direction: str
    ) -> tuple[float, dict[str, float]]:
        """
        Score a signal from 0.0-1.0 based on weighted components.
        Each component scores 0.0-1.0, final = weighted sum capped [0, 1].
        """
        weights = self.cfg.signal_scoring.weights
        breakdown: dict[str, float] = {}

        # 1. TK alignment: how far tenkan is from kijun in the right direction
        tk_diff = ichi.tenkan - ichi.kijun
        if direction == "SELL":
            tk_diff = -tk_diff
        ps = pip_size("EURUSD")
        tk_pips = tk_diff / ps
        breakdown["tk_alignment"] = min(max(tk_pips / 20.0, 0.0), 1.0)

        # 2. Price vs cloud: distance from cloud edge
        if direction == "BUY":
            cloud_dist = (ichi.close - ichi.cloud_top) / ps
        else:
            cloud_dist = (ichi.cloud_bottom - ichi.close) / ps
        breakdown["price_vs_cloud"] = min(max(cloud_dist / 30.0, 0.0), 1.0)

        # 3. Chikou clearance: uses margin from is_chikou_clear
        entry = self.cfg.entry_conditions
        _, margin = is_chikou_clear(
            df, direction, self.cfg.displacement, entry.chikou_clear_lookback
        )
        margin_pips = margin / ps
        breakdown["chikou_clear"] = min(max(margin_pips / 20.0, 0.0), 1.0)

        # 4. Cloud direction
        if direction == "BUY":
            cloud_dir = 1.0 if ichi.senkou_a > ichi.senkou_b else 0.0
        else:
            cloud_dir = 1.0 if ichi.senkou_a < ichi.senkou_b else 0.0
        breakdown["cloud_direction"] = cloud_dir

        # 5. Cloud thickness: thicker = stronger
        breakdown["cloud_thickness"] = min(ichi.cloud_thickness_pips / 30.0, 1.0)

        # 6. Trend filter: defaults to 1.0, set externally if needed
        breakdown["trend_filter"] = 1.0

        # Weighted sum
        score = 0.0
        for key, weight in weights.items():
            score += breakdown.get(key, 0.0) * weight
        score = min(max(score, 0.0), 1.0)

        return round(score, 4), breakdown

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
