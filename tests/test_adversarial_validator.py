"""Tests for core/adversarial_validator.py"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from core.adversarial_validator import (
    AdversarialValidator,
    SignalContext,
    ValidationMetrics,
)
from core.config_loader import ValidationConfig, QualityChecksConfig, NewsFilterConfig
from core.trend_filter import TrendFilter
from core.news_filter import NewsFilter
from core.ichimoku_calculator import IchimokuCalculator, IchimokuValues
from core.config_loader import IchimokuConfig


def _make_ichi(
    close=1.1100, cloud_top=1.1060, cloud_bottom=1.1020,
    tenkan=1.1050, kijun=1.1040,
) -> IchimokuValues:
    return IchimokuValues(
        tenkan=tenkan, kijun=kijun,
        senkou_a=cloud_top, senkou_b=cloud_bottom,
        chikou=close, close=close,
        cloud_top=cloud_top, cloud_bottom=cloud_bottom,
        prev_tenkan=tenkan - 0.001, prev_kijun=kijun,
        prev_senkou_a=cloud_top, prev_senkou_b=cloud_bottom,
        prev_chikou=close - 0.001, prev_close=close - 0.001,
        prev_cloud_top=cloud_top, prev_cloud_bottom=cloud_bottom,
        future_span_a=cloud_top + 0.001, future_span_b=cloud_bottom,
        cloud_thickness_pips=40.0,
        bar_time=pd.Timestamp("2024-06-01 00:00", tz="UTC"),
    )


@dataclass
class _MockSLTP:
    sl: float = 1.0900
    tp: float = 1.1300
    sl_pips: float = 200.0
    tp_pips: float = 200.0
    sl_method: str = "kijun"
    tp_method: str = "ratio"


def _make_df(n=200, base=1.1) -> pd.DataFrame:
    close = np.linspace(base, base + 0.02, n)
    high = close + 0.003
    low = close - 0.003
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close},
        index=pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"),
    )


def _make_validator(
    adversarial=True, min_rtr=0.6,
    trend_confirms=True, news_clear=True,
) -> AdversarialValidator:
    cfg = ValidationConfig(
        adversarial_validation=adversarial,
        min_rtr_score=min_rtr,
    )
    trend_filter = MagicMock(spec=TrendFilter)
    trend_filter.confirms_direction.return_value = (
        trend_confirms, "D1 confirms" if trend_confirms else "D1 conflicts"
    )

    news_cfg = NewsFilterConfig(enabled=not news_clear)
    news_filter = NewsFilter(news_cfg)
    if not news_clear:
        news_filter = MagicMock(spec=NewsFilter)
        news_filter.is_clear.return_value = (False, "FOMC blackout")

    return AdversarialValidator(cfg, trend_filter, news_filter)


def _make_ctx(
    direction="BUY",
    df_d1=None,
    signal_score=0.8,
    momentum_score=60.0,
) -> SignalContext:
    return SignalContext(
        symbol="EURUSD",
        direction=direction,
        ichi=_make_ichi(),
        df_closed=_make_df(),
        sltp=_MockSLTP(),
        df_d1=df_d1 if df_d1 is not None else _make_df(200),
        now_utc=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
        signal_score=signal_score,
        momentum_score=momentum_score,
    )


class TestAllPass:
    def test_all_critics_pass(self):
        validator = _make_validator(trend_confirms=True, news_clear=True)
        ctx = _make_ctx()
        result = validator.validate(ctx)
        assert result["passed"] is True
        assert result["rtr_score"] > 0.0

    def test_rtr_score_is_average(self):
        validator = _make_validator()
        ctx = _make_ctx()
        result = validator.validate(ctx)
        details = result["details"]
        avg = (
            details["logical"]["score"]
            + details["contextual"]["score"]
            + details["structural"]["score"]
        ) / 3.0
        assert abs(result["rtr_score"] - round(avg, 4)) < 0.01


class TestLogicalReject:
    def test_d1_contradicts(self):
        validator = _make_validator(trend_confirms=False, min_rtr=0.8)
        ctx = _make_ctx()
        result = validator.validate(ctx)
        assert result["details"]["logical"]["score"] == 0.0

    def test_d1_unavailable(self):
        validator = _make_validator(trend_confirms=True)
        ctx = _make_ctx(df_d1=_make_df(10))  # too few bars
        result = validator.validate(ctx)
        assert result["details"]["logical"]["score"] == 0.5


class TestContextualReject:
    def test_news_blocked(self):
        validator = _make_validator(news_clear=False)
        ctx = _make_ctx()
        result = validator.validate(ctx)
        assert result["details"]["contextual"]["score"] == 0.0

    def test_weak_signal_penalty(self):
        validator = _make_validator(news_clear=True)
        ctx = _make_ctx(signal_score=0.3)
        result = validator.validate(ctx)
        # Should be 1.0 - 0.3 = 0.7 for news clear + weak penalty
        assert result["details"]["contextual"]["score"] == 0.7


class TestStructuralReject:
    def test_good_sl_placement(self):
        validator = _make_validator()
        ctx = _make_ctx()
        result = validator.validate(ctx)
        # MockSLTP has SL=1.09, cloud_bottom=1.102 -> SL < cloud_bottom -> +0.5
        assert result["details"]["structural"]["score"] >= 0.5

    def test_no_sltp_data(self):
        validator = _make_validator()
        ctx = _make_ctx()
        ctx.sltp = None
        result = validator.validate(ctx)
        assert result["details"]["structural"]["score"] == 0.5


class TestMetrics:
    def test_metrics_initial(self):
        m = ValidationMetrics()
        metrics = m.get_metrics()
        assert metrics["signals_validated"] == 0
        assert metrics["signals_rejected"] == 0

    def test_metrics_after_validation(self):
        validator = _make_validator()
        ctx = _make_ctx()
        validator.validate(ctx)
        metrics = validator.metrics.get_metrics()
        assert metrics["total_evaluated"] == 1

    def test_rejection_breakdown(self):
        m = ValidationMetrics()
        m.record_validation(False, 0.3, 1.0, "logical")
        m.record_validation(False, 0.2, 1.0, "logical")
        m.record_validation(False, 0.4, 1.0, "contextual")
        metrics = m.get_metrics()
        assert metrics["rejection_breakdown"]["logical"] == 2
        assert metrics["rejection_breakdown"]["contextual"] == 1

    def test_pass_rate(self):
        m = ValidationMetrics()
        m.record_validation(True, 0.8, 1.0)
        m.record_validation(True, 0.9, 1.0)
        m.record_validation(False, 0.3, 1.0, "structural")
        metrics = m.get_metrics()
        assert abs(metrics["pass_rate"] - 2 / 3) < 0.01


class TestDisabledPassthrough:
    def test_low_threshold_passes_all(self):
        validator = _make_validator(min_rtr=0.0)
        ctx = _make_ctx()
        result = validator.validate(ctx)
        assert result["passed"] is True
