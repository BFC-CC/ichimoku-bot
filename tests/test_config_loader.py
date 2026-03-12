"""Tests for core/config_loader.py"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.config_loader import ConfigLoader, Config


def _write_config(data: dict) -> Path:
    """Write a JSON config dict to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return Path(f.name)


def _valid_raw() -> dict:
    """Return a minimal valid v3 config dict."""
    return {
        "account": {"login": 0, "password": "", "server": "", "demo_mode": True},
        "goal": {"target_profit_pct": 10.0, "notify_on_goal": True},
        "ichimoku": {
            "tenkan_period": 9,
            "kijun_period": 26,
            "senkou_b_period": 52,
            "displacement": 26,
            "signal_mode": "tk_cross",
            "entry_conditions": {
                "require_price_above_cloud": True,
                "require_tenkan_above_kijun": True,
                "require_chikou_clear": True,
                "require_bullish_cloud": True,
                "require_future_cloud_bullish": False,
            },
            "exit_conditions": {
                "exit_on_tk_cross_against": True,
                "exit_on_price_enter_cloud": False,
                "exit_on_chikou_cross_down": False,
            },
            "cloud_min_thickness_pips": 5,
            "use_virtual_tp": False,
        },
        "pairs": ["EURUSD", "GBPUSD"],
        "timeframes": {"primary": "H4", "confirmation": "D1"},
        "session_filter": {
            "enabled": True,
            "start_hour_utc": 7,
            "end_hour_utc": 20,
            "trade_friday_close": False,
        },
        "news_filter": {
            "enabled": False,
            "minutes_before": 30,
            "minutes_after": 30,
            "impact_levels": ["high"],
        },
        "risk_management": {
            "risk_per_trade_pct": 1.0,
            "max_open_trades": 3,
            "max_daily_loss_pct": 3.0,
            "max_drawdown_pct": 8.0,
            "lot_mode": "risk_pct",
            "fixed_lot_size": 0.01,
            "stop_loss": {
                "method": "kijun",
                "fixed_pips": 40,
                "atr_period": 14,
                "atr_multiplier": 1.5,
                "buffer_pips": 5,
            },
            "take_profit": {"method": "ratio", "rr_ratio": 2.0, "fixed_pips": 80},
            "break_even": {"enabled": True, "trigger_pips": 20, "lock_in_pips": 2},
            "trailing_stop": {
                "enabled": True,
                "method": "kijun",
                "fixed_trail_pips": 20,
                "trail_step_pips": 5,
            },
        },
        "execution": {
            "slippage_points": 20,
            "magic_number": 20260309,
            "order_comment": "IchiBot_v3",
            "retry_attempts": 3,
            "retry_delay_ms": 500,
            "use_market_orders": True,
        },
        "scheduler": {"bar_check_interval_sec": 60, "use_ontrade_transaction": True},
        "logging": {
            "level": "INFO",
            "log_to_file": True,
            "log_dir": "logs",
            "max_file_mb": 10,
            "log_trades_csv": True,
        },
        "dashboard": {"enabled": True, "host": "0.0.0.0", "port": 8000},
    }


class TestConfigLoaderValid:
    def test_load_valid_config(self):
        path = _write_config(_valid_raw())
        cfg = ConfigLoader.load(path)
        assert isinstance(cfg, Config)
        assert cfg.ichimoku.signal_mode == "tk_cross"
        assert cfg.pairs == ["EURUSD", "GBPUSD"]
        assert cfg.risk_management.risk_per_trade_pct == 1.0
        assert cfg.risk_management.stop_loss.method == "kijun"
        assert cfg.risk_management.take_profit.rr_ratio == 2.0
        assert cfg.execution.magic_number == 20260309

    def test_all_signal_modes(self):
        for mode in ("tk_cross", "chikou_cross", "kumo_breakout", "full_confirm"):
            raw = _valid_raw()
            raw["ichimoku"]["signal_mode"] = mode
            cfg = ConfigLoader.load(_write_config(raw))
            assert cfg.ichimoku.signal_mode == mode

    def test_all_lot_modes(self):
        for mode in ("risk_pct", "fixed", "compound"):
            raw = _valid_raw()
            raw["risk_management"]["lot_mode"] = mode
            cfg = ConfigLoader.load(_write_config(raw))
            assert cfg.risk_management.lot_mode == mode

    def test_nested_dataclasses(self):
        cfg = ConfigLoader.load(_write_config(_valid_raw()))
        assert cfg.ichimoku.entry_conditions.require_price_above_cloud is True
        assert cfg.ichimoku.exit_conditions.exit_on_tk_cross_against is True
        assert cfg.risk_management.break_even.trigger_pips == 20.0
        assert cfg.risk_management.trailing_stop.trail_step_pips == 5.0


class TestConfigLoaderInvalid:
    def test_invalid_signal_mode(self):
        raw = _valid_raw()
        raw["ichimoku"]["signal_mode"] = "invalid_mode"
        with pytest.raises(ValueError, match="signal_mode"):
            ConfigLoader.load(_write_config(raw))

    def test_invalid_lot_mode(self):
        raw = _valid_raw()
        raw["risk_management"]["lot_mode"] = "bad"
        with pytest.raises(ValueError, match="lot_mode"):
            ConfigLoader.load(_write_config(raw))

    def test_risk_too_high(self):
        raw = _valid_raw()
        raw["risk_management"]["risk_per_trade_pct"] = 6.0
        with pytest.raises(ValueError, match="risk_per_trade_pct"):
            ConfigLoader.load(_write_config(raw))

    def test_risk_zero(self):
        raw = _valid_raw()
        raw["risk_management"]["risk_per_trade_pct"] = 0
        with pytest.raises(ValueError, match="risk_per_trade_pct"):
            ConfigLoader.load(_write_config(raw))

    def test_rr_ratio_below_one(self):
        raw = _valid_raw()
        raw["risk_management"]["take_profit"]["rr_ratio"] = 0.5
        with pytest.raises(ValueError, match="rr_ratio"):
            ConfigLoader.load(_write_config(raw))

    def test_target_profit_zero(self):
        raw = _valid_raw()
        raw["goal"]["target_profit_pct"] = 0
        with pytest.raises(ValueError, match="target_profit_pct"):
            ConfigLoader.load(_write_config(raw))

    def test_empty_pairs(self):
        raw = _valid_raw()
        raw["pairs"] = []
        with pytest.raises(ValueError, match="pairs"):
            ConfigLoader.load(_write_config(raw))

    def test_wrong_period_order(self):
        raw = _valid_raw()
        raw["ichimoku"]["tenkan_period"] = 30
        with pytest.raises(ValueError, match="strictly ascending"):
            ConfigLoader.load(_write_config(raw))

    def test_invalid_sl_method(self):
        raw = _valid_raw()
        raw["risk_management"]["stop_loss"]["method"] = "magic"
        with pytest.raises(ValueError, match="stop_loss.method"):
            ConfigLoader.load(_write_config(raw))

    def test_invalid_tp_method(self):
        raw = _valid_raw()
        raw["risk_management"]["take_profit"]["method"] = "magic"
        with pytest.raises(ValueError, match="take_profit.method"):
            ConfigLoader.load(_write_config(raw))

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ConfigLoader.load("/tmp/nonexistent_config.json")


class TestValidationConfig:
    def test_validation_parsed(self):
        raw = _valid_raw()
        raw["validation"] = {
            "adversarial_validation": True,
            "min_rtr_score": 0.7,
            "momentum_scoring": True,
            "strength_classification": True,
            "quality_checks": {
                "max_slippage_pips": 2.0,
                "min_fill_ratio": 0.9,
                "max_spread_pips": 4.0,
            },
            "strength_lot_multiplier": {
                "STRONG": 1.0, "MODERATE": 0.5, "WEAK": 0.3,
            },
        }
        cfg = ConfigLoader.load(_write_config(raw))
        assert cfg.validation.adversarial_validation is True
        assert cfg.validation.min_rtr_score == 0.7
        assert cfg.validation.momentum_scoring is True
        assert cfg.validation.quality_checks.max_slippage_pips == 2.0
        assert cfg.validation.strength_lot_multiplier["MODERATE"] == 0.5

    def test_missing_validation_defaults(self):
        raw = _valid_raw()
        # No "validation" key at all
        cfg = ConfigLoader.load(_write_config(raw))
        assert cfg.validation.adversarial_validation is False
        assert cfg.validation.min_rtr_score == 0.6
        assert cfg.validation.momentum_scoring is False
        assert cfg.validation.quality_checks.max_slippage_pips == 3.0
