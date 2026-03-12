"""
core/config_loader.py
─────────────────────────────────────────────────────────────────────────────
Parses strategy_config.json into typed dataclasses with full validation.

Usage
-----
    from core.config_loader import ConfigLoader
    config = ConfigLoader.load("config/strategy_config.json")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from loguru import logger


# ─────────────────────────────────────────────────────────────────────────────
#  Nested config dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AccountConfig:
    login: int = 0
    password: str = ""
    server: str = ""
    demo_mode: bool = True


@dataclass
class GoalConfig:
    target_profit_pct: float = 10.0
    notify_on_goal: bool = True


@dataclass
class EntryConditions:
    require_price_above_cloud: bool = True
    require_tenkan_above_kijun: bool = True
    require_chikou_clear: bool = True
    require_bullish_cloud: bool = True
    require_future_cloud_bullish: bool = False
    chikou_clear_lookback: int = 5


@dataclass
class ExitConditions:
    exit_on_tk_cross_against: bool = True
    exit_on_price_enter_cloud: bool = False
    exit_on_chikou_cross_down: bool = False


@dataclass
class SignalScoringConfig:
    enabled: bool = False
    min_score_threshold: float = 0.5
    scale_lot_by_score: bool = False
    weights: dict = field(default_factory=lambda: {
        "tk_alignment": 0.15,
        "price_vs_cloud": 0.20,
        "chikou_clear": 0.20,
        "cloud_direction": 0.15,
        "cloud_thickness": 0.10,
        "trend_filter": 0.20,
    })


@dataclass
class IchimokuConfig:
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    displacement: int = 26
    signal_mode: str = "tk_cross"
    entry_conditions: EntryConditions = field(default_factory=EntryConditions)
    exit_conditions: ExitConditions = field(default_factory=ExitConditions)
    cloud_min_thickness_pips: float = 5.0
    use_virtual_tp: bool = False
    signal_scoring: SignalScoringConfig = field(default_factory=SignalScoringConfig)


@dataclass
class StopLossConfig:
    method: str = "kijun"
    fixed_pips: float = 40.0
    atr_period: int = 14
    atr_multiplier: float = 1.5
    buffer_pips: float = 5.0


@dataclass
class TakeProfitConfig:
    method: str = "ratio"
    rr_ratio: float = 2.0
    fixed_pips: float = 80.0


@dataclass
class BreakEvenConfig:
    enabled: bool = True
    trigger_pips: float = 20.0
    lock_in_pips: float = 2.0


@dataclass
class TrailingStopConfig:
    enabled: bool = True
    method: str = "kijun"
    fixed_trail_pips: float = 20.0
    trail_step_pips: float = 5.0


@dataclass
class RiskManagementConfig:
    risk_per_trade_pct: float = 1.0
    max_open_trades: int = 3
    max_daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 8.0
    lot_mode: str = "risk_pct"
    fixed_lot_size: float = 0.01
    stop_loss: StopLossConfig = field(default_factory=StopLossConfig)
    take_profit: TakeProfitConfig = field(default_factory=TakeProfitConfig)
    break_even: BreakEvenConfig = field(default_factory=BreakEvenConfig)
    trailing_stop: TrailingStopConfig = field(default_factory=TrailingStopConfig)


@dataclass
class ExecutionConfig:
    slippage_points: int = 20
    magic_number: int = 20260309
    order_comment: str = "IchiBot_v3"
    retry_attempts: int = 3
    retry_delay_ms: int = 500
    use_market_orders: bool = True


@dataclass
class TimeframeConfig:
    primary: str = "H4"
    confirmation: str = "D1"


@dataclass
class SessionFilterConfig:
    enabled: bool = True
    start_hour_utc: int = 7
    end_hour_utc: int = 20
    trade_friday_close: bool = False


@dataclass
class NewsFilterConfig:
    enabled: bool = False
    minutes_before: int = 30
    minutes_after: int = 30
    impact_levels: List[str] = field(default_factory=lambda: ["high"])
    calendar_source: str = "static"
    api_url: str = ""
    cache_ttl_hours: int = 24
    static_events_path: str = "data/news_events.json"


@dataclass
class SchedulerConfig:
    bar_check_interval_sec: int = 60
    use_ontrade_transaction: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_to_file: bool = True
    log_dir: str = "logs"
    max_file_mb: int = 10
    log_trades_csv: bool = True


@dataclass
class HealthMonitorConfig:
    enabled: bool = True
    max_tick_gap_sec: int = 300
    max_consecutive_errors: int = 3
    alert_cooldown_sec: int = 900
    heartbeat_interval_sec: int = 3600


@dataclass
class DashboardConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    keep_alive_url: str = ""
    keep_alive_interval_sec: int = 600


@dataclass
class QualityChecksConfig:
    max_slippage_pips: float = 3.0
    min_fill_ratio: float = 0.95
    max_spread_pips: float = 5.0


@dataclass
class ValidationConfig:
    adversarial_validation: bool = False
    min_rtr_score: float = 0.6
    momentum_scoring: bool = False
    strength_classification: bool = False
    quality_checks: QualityChecksConfig = field(default_factory=QualityChecksConfig)
    strength_lot_multiplier: dict = field(default_factory=lambda: {
        "STRONG": 1.0, "MODERATE": 0.7, "WEAK": 0.4
    })


@dataclass
class Config:
    account: AccountConfig = field(default_factory=AccountConfig)
    goal: GoalConfig = field(default_factory=GoalConfig)
    ichimoku: IchimokuConfig = field(default_factory=IchimokuConfig)
    pairs: List[str] = field(default_factory=list)
    timeframes: TimeframeConfig = field(default_factory=TimeframeConfig)
    session_filter: SessionFilterConfig = field(default_factory=SessionFilterConfig)
    news_filter: NewsFilterConfig = field(default_factory=NewsFilterConfig)
    risk_management: RiskManagementConfig = field(default_factory=RiskManagementConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    health_monitor: HealthMonitorConfig = field(default_factory=HealthMonitorConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)


# ─────────────────────────────────────────────────────────────────────────────
#  Loader
# ─────────────────────────────────────────────────────────────────────────────

VALID_SIGNAL_MODES = {"tk_cross", "chikou_cross", "kumo_breakout", "full_confirm"}
VALID_LOT_MODES = {"risk_pct", "fixed", "compound"}
VALID_SL_METHODS = {"kijun", "atr", "cloud_edge", "fixed_pips"}
VALID_TP_METHODS = {"ratio", "next_cloud", "fixed_pips"}


class ConfigLoader:
    """Load and validate strategy_config.json into a Config dataclass."""

    @staticmethod
    def load(path: str | Path) -> Config:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            raw = json.load(f)

        config = ConfigLoader._build(raw)
        ConfigLoader._validate(config)
        ConfigLoader._print_summary(config)
        return config

    @staticmethod
    def _build(raw: dict) -> Config:
        acc = raw.get("account", {})
        goal = raw.get("goal", {})
        ichi_raw = raw.get("ichimoku", {})
        risk_raw = raw.get("risk_management", {})
        exec_raw = raw.get("execution", {})
        tf_raw = raw.get("timeframes", {})
        sess_raw = raw.get("session_filter", {})
        news_raw = raw.get("news_filter", {})
        sched_raw = raw.get("scheduler", {})
        log_raw = raw.get("logging", {})
        dash_raw = raw.get("dashboard", {})
        health_raw = raw.get("health_monitor", {})
        validation_raw = raw.get("validation", {})

        entry_raw = ichi_raw.pop("entry_conditions", {})
        exit_raw = ichi_raw.pop("exit_conditions", {})
        scoring_raw = ichi_raw.pop("signal_scoring", {})

        sl_raw = risk_raw.pop("stop_loss", {})
        tp_raw = risk_raw.pop("take_profit", {})
        be_raw = risk_raw.pop("break_even", {})
        ts_raw = risk_raw.pop("trailing_stop", {})

        qc_raw = validation_raw.pop("quality_checks", {})
        slm_raw = validation_raw.pop("strength_lot_multiplier", None)
        validation_kwargs = dict(validation_raw)
        validation_kwargs["quality_checks"] = QualityChecksConfig(**qc_raw)
        if slm_raw is not None:
            validation_kwargs["strength_lot_multiplier"] = slm_raw

        return Config(
            account=AccountConfig(**acc),
            goal=GoalConfig(**goal),
            ichimoku=IchimokuConfig(
                entry_conditions=EntryConditions(**entry_raw),
                exit_conditions=ExitConditions(**exit_raw),
                signal_scoring=SignalScoringConfig(**scoring_raw),
                **ichi_raw,
            ),
            pairs=raw.get("pairs", []),
            timeframes=TimeframeConfig(**tf_raw),
            session_filter=SessionFilterConfig(**sess_raw),
            news_filter=NewsFilterConfig(**news_raw),
            risk_management=RiskManagementConfig(
                stop_loss=StopLossConfig(**sl_raw),
                take_profit=TakeProfitConfig(**tp_raw),
                break_even=BreakEvenConfig(**be_raw),
                trailing_stop=TrailingStopConfig(**ts_raw),
                **risk_raw,
            ),
            execution=ExecutionConfig(**exec_raw),
            scheduler=SchedulerConfig(**sched_raw),
            logging=LoggingConfig(**log_raw),
            dashboard=DashboardConfig(**dash_raw),
            health_monitor=HealthMonitorConfig(**health_raw),
            validation=ValidationConfig(**validation_kwargs),
        )

    @staticmethod
    def _validate(cfg: Config) -> None:
        errors: list[str] = []

        # Period ordering
        ichi = cfg.ichimoku
        if not (ichi.tenkan_period < ichi.kijun_period < ichi.senkou_b_period):
            errors.append(
                f"Ichimoku periods must be strictly ascending: "
                f"tenkan({ichi.tenkan_period}) < kijun({ichi.kijun_period}) "
                f"< senkou_b({ichi.senkou_b_period})"
            )

        # Displacement warning
        if ichi.displacement != ichi.kijun_period:
            logger.warning(
                f"displacement ({ichi.displacement}) != kijun_period ({ichi.kijun_period}) "
                f"— this is unusual but allowed"
            )

        # Signal mode
        if ichi.signal_mode not in VALID_SIGNAL_MODES:
            errors.append(
                f"signal_mode '{ichi.signal_mode}' invalid. "
                f"Must be one of: {VALID_SIGNAL_MODES}"
            )

        # Lot mode
        rm = cfg.risk_management
        if rm.lot_mode not in VALID_LOT_MODES:
            errors.append(
                f"lot_mode '{rm.lot_mode}' invalid. "
                f"Must be one of: {VALID_LOT_MODES}"
            )

        # Risk range
        if not (0 < rm.risk_per_trade_pct <= 5):
            errors.append(
                f"risk_per_trade_pct must be in (0, 5], got {rm.risk_per_trade_pct}"
            )

        # SL method
        if rm.stop_loss.method not in VALID_SL_METHODS:
            errors.append(
                f"stop_loss.method '{rm.stop_loss.method}' invalid. "
                f"Must be one of: {VALID_SL_METHODS}"
            )

        # TP method
        if rm.take_profit.method not in VALID_TP_METHODS:
            errors.append(
                f"take_profit.method '{rm.take_profit.method}' invalid. "
                f"Must be one of: {VALID_TP_METHODS}"
            )

        # RR ratio
        if rm.take_profit.rr_ratio < 1.0:
            errors.append(
                f"take_profit.rr_ratio must be >= 1.0, got {rm.take_profit.rr_ratio}"
            )

        # Target profit
        if cfg.goal.target_profit_pct <= 0:
            errors.append(
                f"target_profit_pct must be > 0, got {cfg.goal.target_profit_pct}"
            )

        # Pairs not empty
        if not cfg.pairs:
            errors.append("pairs list must not be empty")

        if errors:
            raise ValueError("Config validation failed:\n  - " + "\n  - ".join(errors))

    @staticmethod
    def _print_summary(cfg: Config) -> None:
        logger.info("=" * 60)
        logger.info("STRATEGY CONFIG LOADED")
        logger.info("=" * 60)
        logger.info(f"  Account: login={cfg.account.login}, demo={cfg.account.demo_mode}")
        logger.info(f"  Goal: {cfg.goal.target_profit_pct}% profit target")
        logger.info(f"  Pairs: {cfg.pairs}")
        logger.info(f"  Timeframes: primary={cfg.timeframes.primary}, confirm={cfg.timeframes.confirmation}")
        logger.info(f"  Signal mode: {cfg.ichimoku.signal_mode}")
        logger.info(f"  Risk: {cfg.risk_management.risk_per_trade_pct}% per trade, "
                     f"lot_mode={cfg.risk_management.lot_mode}")
        logger.info(f"  SL: {cfg.risk_management.stop_loss.method}, "
                     f"TP: {cfg.risk_management.take_profit.method} "
                     f"(RR={cfg.risk_management.take_profit.rr_ratio})")
        logger.info(f"  Max open: {cfg.risk_management.max_open_trades}, "
                     f"Max DD: {cfg.risk_management.max_drawdown_pct}%")
        logger.info(f"  Session filter: {'ON' if cfg.session_filter.enabled else 'OFF'}")
        logger.info(f"  Dashboard: {'ON' if cfg.dashboard.enabled else 'OFF'} "
                     f"(port {cfg.dashboard.port})")
        v = cfg.validation
        logger.info(f"  Validation: adversarial={'ON' if v.adversarial_validation else 'OFF'}, "
                     f"momentum={'ON' if v.momentum_scoring else 'OFF'}, "
                     f"strength={'ON' if v.strength_classification else 'OFF'}")
        logger.info("=" * 60)
