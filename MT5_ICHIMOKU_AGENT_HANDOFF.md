# MT5 Ichimoku Trading Bot — Agent Handoff Document
**Version:** 3.0
**Status:** Implementation complete (375 tests passing)
**Purpose:** Architecture reference and specification for the v3 Trading Bot

---

## 0. AGENT INSTRUCTIONS (READ FIRST)

This document was originally a build plan for the v3 Trading Bot. The implementation is now **complete**. Use this as an architecture reference. Key rules that remain enforced in the codebase:

1. **Never** evaluate signals on an open/forming bar — always use the last confirmed closed bar (index `df.iloc[-1]` after stripping the live bar with `df = df.iloc[:-1]`)
2. **Always** run the ActionVerifier after every trade close and append failures to `logs/failed_actions.csv`
3. All files listed in Section 7 are implemented and tested
4. Additional features added post-plan: signal scoring, chikou clearance (high-low range), health monitor, news filter (static calendar), adversarial validation, momentum scoring, signal strength classification, keep-alive pings

---

## 1. SYSTEM OVERVIEW

A fully automated Forex trading bot that:
- Parses a **JSON configuration file** on startup — all parameters live there, nothing is hardcoded
- Connects to **MetaTrader 5** (demo account only — safety-locked in config)
- Scans **8 major forex pairs** on H4 timeframe using the **Ichimoku Kinko Hyo** strategy
- Executes trades when signal conditions are met on **closed bar data only**
- Automatically **halts and closes all positions** when the account reaches `goal.target_profit_pct` profit
- Runs an **ActionVerifier** after every trade close, scoring CORRECT/INCORRECT and logging failures to CSV
- Serves a **live HTML dashboard** via FastAPI + WebSocket

---

## 2. NON-NEGOTIABLE RULES

These are absolute constraints. The implementation must enforce all of them:

| Rule | Enforcement Point | Detail |
|------|-------------------|--------|
| **Closed-bar only** | `CandleCloseGuard` | Strip live bar before any calculation: `df = df.iloc[:-1]`. Signal uses `df.iloc[-1]`. |
| **Bar de-duplication** | `CandleCloseGuard` | Track `last_processed_bar[symbol]` timestamp. Skip if same bar has already been acted on. |
| **Demo-mode lock** | `ConfigLoader` | If `account.demo_mode = true`, refuse to connect to any account where `trade_mode != 0` (demo). |
| **Goal auto-halt** | `RiskGuard` + `TradeBot` | When `balance >= start_balance * (1 + target_profit_pct/100)`, close all positions and stop the bot. |
| **Action verification** | `TradeEventListener` | Every closed trade triggers `ActionVerifier.verify()`. Failures appended to `failed_actions.csv`. |
| **Magic number isolation** | `OrderExecutor` | All queries (positions, history) filter by `magic_number` from config. Never touch orders from other EAs. |
| **JPY pip math** | `LotCalculator`, `SLTPBuilder` | Pip = `0.01` for JPY pairs, `0.0001` for all others. Point = pip / 10. Check `"JPY" in symbol`. |

---

## 3. JSON CONFIG — COMPLETE SCHEMA (v3)

File path: `config/strategy_config.json`

Every parameter below must be parsed by `ConfigLoader` into a typed dataclass. No parameter may be hardcoded anywhere else in the system.

```json
{
  "account": {
    "login": 0,
    "password": "",
    "server": "",
    "demo_mode": true
  },

  "goal": {
    "target_profit_pct": 10.0,
    "notify_on_goal": true
  },

  "ichimoku": {
    "tenkan_period": 9,
    "kijun_period": 26,
    "senkou_b_period": 52,
    "displacement": 26,

    "signal_mode": "tk_cross",

    "entry_conditions": {
      "require_price_above_cloud": true,
      "require_tenkan_above_kijun": true,
      "require_chikou_clear": true,
      "require_bullish_cloud": true,
      "require_future_cloud_bullish": false
    },

    "exit_conditions": {
      "exit_on_tk_cross_against": true,
      "exit_on_price_enter_cloud": false,
      "exit_on_chikou_cross_down": false
    },

    "cloud_min_thickness_pips": 5,
    "use_virtual_tp": false
  },

  "pairs": ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","EURGBP","NZDUSD","EURJPY"],

  "timeframes": {
    "primary": "H4",
    "confirmation": "D1"
  },

  "session_filter": {
    "enabled": true,
    "start_hour_utc": 7,
    "end_hour_utc": 20,
    "trade_friday_close": false
  },

  "news_filter": {
    "enabled": false,
    "minutes_before": 30,
    "minutes_after": 30,
    "impact_levels": ["high"]
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
      "buffer_pips": 5
    },

    "take_profit": {
      "method": "ratio",
      "rr_ratio": 2.0,
      "fixed_pips": 80
    },

    "break_even": {
      "enabled": true,
      "trigger_pips": 20,
      "lock_in_pips": 2
    },

    "trailing_stop": {
      "enabled": true,
      "method": "kijun",
      "fixed_trail_pips": 20,
      "trail_step_pips": 5
    }
  },

  "execution": {
    "slippage_points": 20,
    "magic_number": 20260309,
    "order_comment": "IchiBot_v3",
    "retry_attempts": 3,
    "retry_delay_ms": 500,
    "use_market_orders": true
  },

  "scheduler": {
    "bar_check_interval_sec": 60,
    "use_ontrade_transaction": true
  },

  "logging": {
    "level": "INFO",
    "log_to_file": true,
    "log_dir": "logs",
    "max_file_mb": 10,
    "log_trades_csv": true
  },

  "dashboard": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8000,
    "keep_alive_url": "",
    "keep_alive_interval_sec": 600
  },

  "health_monitor": {
    "enabled": true,
    "max_tick_gap_sec": 300,
    "max_consecutive_errors": 3,
    "alert_cooldown_sec": 900,
    "heartbeat_interval_sec": 3600
  },

  "validation": {
    "adversarial_validation": false,
    "min_rtr_score": 0.6,
    "momentum_scoring": false,
    "strength_classification": false,
    "quality_checks": {
      "max_slippage_pips": 3.0,
      "min_fill_ratio": 0.95,
      "max_spread_pips": 5.0
    },
    "strength_lot_multiplier": {
      "STRONG": 1.0,
      "MODERATE": 0.7,
      "WEAK": 0.4
    }
  }
}
```

> **Note (added post-implementation):** The `ichimoku` section also supports a `signal_scoring` sub-object with `enabled`, `min_score_threshold`, `scale_lot_by_score`, and `weights` (6 components). See `config/strategy_config.json` for the live config or `core/config_loader.py:SignalScoringConfig` for the dataclass definition.

### Config Validation Rules (enforced by ConfigLoader)
- `tenkan_period < kijun_period < senkou_b_period` — must be strictly ascending
- `displacement == kijun_period` — warn if different, do not hard-fail
- `signal_mode` must be one of: `tk_cross`, `chikou_cross`, `kumo_breakout`, `full_confirm`
- `lot_mode` must be one of: `risk_pct`, `fixed`, `compound`
- `stop_loss.method` must be one of: `kijun`, `atr`, `cloud_edge`, `fixed_pips`
- `take_profit.method` must be one of: `ratio`, `next_cloud`, `fixed_pips`
- `0 < risk_per_trade_pct <= 5` — fail if outside this range
- `take_profit.rr_ratio >= 1.0` — fail if below
- `target_profit_pct > 0` — fail if zero or negative
- `pairs` list must not be empty

---

## 4. ICHIMOKU STRATEGY — COMPLETE SPECIFICATION

### 4.1 Component Formulas
All computations on **confirmed closed bars only** (live bar stripped).

| Component | Formula | Period | Notes |
|-----------|---------|--------|-------|
| Tenkan-sen | `(highest_high + lowest_low) / 2` | 9 | Conversion line |
| Kijun-sen | `(highest_high + lowest_low) / 2` | 26 | Base line |
| Senkou Span A | `(Tenkan + Kijun) / 2` | — | Plotted +26 forward |
| Senkou Span B | `(highest_high + lowest_low) / 2` | 52 | Plotted +26 forward |
| Chikou Span | `current_close` | — | Plotted −26 backward |

### 4.2 Signal Modes

#### `tk_cross` (default — fastest)
**BUY** when (on last closed bar):
- Tenkan-sen > Kijun-sen (cross occurred this bar or is currently above)
- Close > cloud top
- *(optional)* Chikou > close[−26]
- *(optional)* Span A > Span B

**SELL** is exact mirror.

#### `chikou_cross` (strong confirmation)
**BUY** when:
- Chikou span crosses above close[−26] **on this bar** (was below, now above)
- Chikou span is above the cloud at −26 offset
- Close > cloud top

#### `kumo_breakout` (trend continuation)
**BUY** when:
- Close[−1] (prev bar) was inside or below cloud
- Close (this bar) is above cloud top
- Future cloud (Span A & B projected 26 bars forward from this bar) is bullish (A > B)

#### `full_confirm` (all four — most conservative)
**BUY** when ALL of:
- Close > cloud top
- Tenkan > Kijun
- Chikou > close[−26]
- Span A > Span B (bullish cloud color)
- Cloud thickness >= `cloud_min_thickness_pips`

### 4.3 Cloud Computation at Current Bar
```
# At bar index idx (last closed bar):
cloud_idx = idx - displacement          # cloud visible NOW was projected 26 bars ago
current_span_a = span_a_series[cloud_idx]
current_span_b = span_b_series[cloud_idx]
cloud_top    = max(current_span_a, current_span_b)
cloud_bottom = min(current_span_a, current_span_b)

# Future cloud (projected from this bar, 26 forward):
future_span_a = span_a_series[idx]
future_span_b = span_b_series[idx]
```

### 4.4 Ichimoku-Based Exit Conditions (checked every cycle on open positions)
- `exit_on_tk_cross_against`: close BUY if Tenkan crosses below Kijun on a new closed bar
- `exit_on_price_enter_cloud`: close BUY if close drops into cloud (`close < cloud_top`)
- `exit_on_chikou_cross_down`: close BUY if Chikou drops below price 26 bars ago

---

## 5. RISK MANAGEMENT — COMPLETE SPECIFICATION

### 5.1 Lot Size Calculation

**`risk_pct` mode** (default):
```
pip_value_per_lot = contract_size * pip_size   # e.g. 100000 * 0.0001 = 10 USD/pip
risk_pips = abs(entry - stop_loss) / pip_size
risk_amount = account_balance * risk_per_trade_pct / 100
lot_size = risk_amount / (risk_pips * pip_value_per_lot)
lot_size = round_to_volume_step(lot_size, symbol_info)
lot_size = clamp(lot_size, volume_min, volume_max)
```

**`fixed` mode**: always use `fixed_lot_size` from config  
**`compound` mode**: same as `risk_pct` but `account_balance` updates to current balance each trade (auto-compounding)

### 5.2 Stop Loss Placement

| Method | Logic |
|--------|-------|
| `kijun` | SL = Kijun-sen ± buffer_pips. BUY: below Kijun. SELL: above Kijun. |
| `atr` | SL = entry ± (ATR(14) × atr_multiplier). |
| `cloud_edge` | SL = cloud boundary ± buffer_pips. BUY: below cloud_bottom. SELL: above cloud_top. |
| `fixed_pips` | SL = entry ± fixed_pips in pip units. |

Always add `buffer_pips` beyond the anchor point to avoid spike hits.  
Minimum SL distance: 2 pips. Reject trade if SL would be < 2 pips from entry.

### 5.3 Take Profit Placement

| Method | Logic |
|--------|-------|
| `ratio` | TP = entry ± (SL_distance × rr_ratio). |
| `next_cloud` | TP = far edge of future cloud. Fallback to ratio if R:R < 1.0. |
| `fixed_pips` | TP = entry ± fixed_pips. |

### 5.4 Position Lifecycle

```
OPEN → [check every cycle on closed bar]
  ├── Break-even check: if profit_pips >= trigger_pips → move SL to entry + lock_in_pips
  ├── Trailing stop: if method=kijun → new_sl = kijun ± buffer. Only update if new_sl improves by >= trail_step_pips
  ├── Ichimoku exit conditions (see 4.4)
  └── Virtual TP check (if use_virtual_tp=true): close manually when price >= tp_price
CLOSE → TradeEventListener detects → ActionVerifier.verify() → log
```

### 5.5 Risk Guards (checked before every new trade)

1. **Max open trades**: `len(open_positions_by_magic) >= max_open_trades` → skip
2. **Duplicate symbol**: position already open in same symbol → skip
3. **Daily loss cap**: `sum(closed_pnl_today) <= -(balance * max_daily_loss_pct/100)` → halt for day
4. **Max drawdown**: `(start_balance - equity) / start_balance * 100 >= max_drawdown_pct` → emergency close all + halt
5. **Goal reached**: `balance >= start_balance * (1 + target_profit_pct/100)` → close all + halt permanently

---

## 6. CODE STATUS (post-implementation)

All files from the original plan have been implemented, tested, and are in production.

| File | Status | Notes |
|------|--------|-------|
| `core/config_loader.py` | ✅ Complete | All v3 fields + `SignalScoringConfig` + `ValidationConfig` + `HealthMonitorConfig` + `NewsFilterConfig` |
| `core/ichimoku_calculator.py` | ✅ Complete | Frozen `IchimokuValues` dataclass + `is_chikou_clear()` (high-low range) + `pip_size()` |
| `core/signal_engine.py` | ✅ Complete | 4 modes + signal scoring (6 weights) + `classify_signal_strength()` + `check_exit()` |
| `core/mt5_connector.py` | ✅ Complete | Sim fallback with `force_sim=True`, `get_deal_history()` implemented |
| `core/risk_manager.py` | ✅ Complete | Split into `RiskGuard` + `LotCalculator` + `SLTPBuilder` + `BreakEvenManager` |
| `core/news_filter.py` | ✅ Complete | Delegates to `news_calendar.py`, uses `data/news_events.json` (static calendar) |
| `core/health_monitor.py` | ✅ Complete | Tick gaps, consecutive errors, Discord alerts with cooldown |
| `core/adversarial_validator.py` | ✅ Complete | 3 critics → RTR score, `ValidationMetrics` thread-safe counters |
| `core/momentum.py` | ✅ Complete | RSI, ADX, EMA alignment, ATR consistency → 0–100 score |
| `utils/keep_alive.py` | ✅ Complete | Background ping thread for Render free tier |
| `utils/dashboard_server.py` | ✅ Complete | FastAPI + WebSocket, `/api/health`, `/api/validation/metrics` |
| `trade_bot.py` | ✅ Complete | Full orchestrator: all filters, scoring, validation wired in |

Legacy files (`config_parser.py`, `ichimoku.py`, `main.py`, `mt5_bridge.py`, root `risk_manager.py`, `strategy.json`) have been removed.

---

## 7. COMPLETE FILE MAP — CURRENT STATE

All files are implemented and tested:

```
Colpo_Groso_BFC/
│
├── config/
│   └── strategy_config.json          # v3 schema — all parameters
│
├── core/
│   ├── config_loader.py              # Parse JSON → typed Config dataclasses + validation
│   ├── candle_close_guard.py         # Strip live bar, track last processed bar per symbol
│   ├── mt5_connector.py              # MT5 bridge + simulation fallback (force_sim=True in tests)
│   ├── trade_event_listener.py       # Poll MT5 deal history, trigger ActionVerifier
│   ├── indicator.py                  # Shared: pure-pandas Ichimoku calculator
│   ├── ichimoku_calculator.py        # Frozen IchimokuValues + is_chikou_clear() + pip_size()
│   ├── signal_engine.py              # 4 modes + signal scoring + classify_signal_strength()
│   ├── trend_filter.py               # D1 cloud direction check
│   ├── session_filter.py             # UTC hour window + Friday filter
│   ├── news_filter.py                # Static calendar blackout (delegates to news_calendar.py)
│   ├── news_calendar.py              # Recurring + specific date event matching
│   ├── lot_calculator.py             # risk_pct / fixed / compound, JPY-aware
│   ├── sltp_builder.py               # SL/TP for kijun, ATR, cloud_edge, fixed_pips
│   ├── risk_manager.py               # RiskGuard (goal, drawdown, daily loss, can_trade)
│   ├── break_even_manager.py         # Move SL to entry after trigger_pips profit
│   ├── position_manager.py           # Trailing stop + ichimoku exit conditions
│   ├── order_executor.py             # Send orders with retry + magic number isolation
│   ├── action_verifier.py            # Post-close scoring + failure classification + quality checks
│   ├── health_monitor.py             # Tick gaps, error tracking, Discord alerts with cooldown
│   ├── adversarial_validator.py      # 3 critics → RTR score (optional, disabled by default)
│   └── momentum.py                   # RSI, ADX, EMA, ATR → 0-100 score (optional)
│
├── data/
│   └── news_events.json              # FOMC, NFP, ECB, BOJ dates for news filter
│
├── utils/
│   ├── logger.py                     # Loguru setup from config
│   ├── trade_logger.py               # Write/append trades.csv
│   ├── failed_action_logger.py       # Write/append failed_actions.csv (filelock)
│   ├── state.py                      # Thread-safe BotState (threading.Lock)
│   ├── dashboard_server.py           # FastAPI + WebSocket + /api/health + /api/validation/metrics
│   ├── state_pusher.py               # Push state to remote dashboard
│   ├── keep_alive.py                 # Background ping for Render free tier
│   └── verify_deploy.py              # Screenshot + health check verification
│
├── logs/                             # Auto-created on first run
│   ├── bot.log                       # Rotating log file
│   ├── trades.csv                    # All trades (wins and losses)
│   └── failed_actions.csv            # Failed action records only
│
├── trade_bot.py                      # Main orchestrator — entry point
├── requirements.txt
└── README.md
```

---

## 8. NEW MODULES — FULL SPECIFICATION

### 8.1 `core/candle_close_guard.py`

**Responsibility:** Ensure no signal ever touches the live forming bar.

**Interface:**
```python
class CandleCloseGuard:
    def __init__(self):
        self._last_processed: dict[str, pd.Timestamp] = {}

    def get_closed_bars(self, df: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame | None, bool]:
        """
        Strip the live bar. Check if the last closed bar is new.
        Returns (df_closed, is_new_bar).
        df_closed has live bar removed. is_new_bar=False means skip this cycle.
        """
        df_closed = df.iloc[:-1].copy()           # ALWAYS strip index -1
        last_bar_time = df_closed.iloc[-1]["time"]
        if self._last_processed.get(symbol) == last_bar_time:
            return df_closed, False               # same bar, already processed
        self._last_processed[symbol] = last_bar_time
        return df_closed, True                    # new closed bar — proceed
```

**Critical notes:**
- `df.iloc[:-1]` is always applied regardless of `is_new_bar` — even for position management checks, never use the live bar
- On bot restart, `_last_processed` resets — this is acceptable, the bar timestamp check will catch duplicates within the same session

---

### 8.2 `core/signal_engine.py`

**Responsibility:** Route signal evaluation to the correct mode. Return `Signal.BUY`, `Signal.SELL`, or `Signal.NEUTRAL`.

**Interface:**
```python
class SignalEngine:
    def __init__(self, config: IchimokuConfig): ...

    def evaluate(self, ichi: IchimokuValues, df_closed: pd.DataFrame) -> SignalResult:
        """
        Routes to correct mode based on config.signal_mode.
        All inputs are computed from closed bar data only.
        Returns SignalResult(signal, reasons, conditions_met_dict).
        """

    def _tk_cross(self, ichi, df) -> SignalResult: ...
    def _chikou_cross(self, ichi, df) -> SignalResult: ...
    def _kumo_breakout(self, ichi, df) -> SignalResult: ...
    def _full_confirm(self, ichi, df) -> SignalResult: ...
```

**`SignalResult` dataclass:**
```python
@dataclass
class SignalResult:
    signal: Signal                      # BUY / SELL / NEUTRAL
    mode_used: str                      # which mode fired
    reasons: list[str]                  # human-readable conditions met
    conditions_met: dict[str, bool]     # {"price_above_cloud": True, ...}
    bar_time: pd.Timestamp              # the closed bar that triggered this
    ichi: IchimokuValues                # full snapshot for logging
```

---

### 8.3 `core/action_verifier.py`

**Responsibility:** After every trade close, score it CORRECT or INCORRECT, classify failure type, and trigger CSV logging.

**Interface:**
```python
class ActionVerifier:
    def __init__(self, config: Config, mt5: MT5Connector, failed_logger: FailedActionLogger):
        ...

    def verify(self, closed_trade: ClosedTrade) -> VerificationResult:
        """
        Called by TradeEventListener after every close event.
        1. Determine CORRECT or INCORRECT from PnL.
        2. If INCORRECT: reconstruct signal state at entry, classify failure type.
        3. Build FailedActionRecord.
        4. Call failed_logger.append(record).
        Returns VerificationResult for logging/dashboard.
        """
```

**Scoring logic:**
```
if closed_trade.pnl > 0  → CORRECT
if closed_trade.pnl == 0 → CORRECT (break-even, capital preserved)
if closed_trade.pnl < 0  → INCORRECT → classify failure type
```

**Failure classification (checked in order):**
1. `SL_HIT` — exit_reason is "sl" (primary, most common)
2. `AGAINST_D1_TREND` — re-fetch D1 bars at entry time, check if price was against D1 cloud → elevate from SL_HIT if true
3. `WEAK_SIGNAL` — re-run signal engine on entry bar, check if fewer than required conditions were actually met
4. `SESSION_ANOMALY` — entry_hour outside `session_filter.start_hour_utc` to `end_hour_utc`
5. `OVERTRADED` — more than 2 concurrent open trades at entry time, and multiple lost same day
6. `SYSTEM_ERROR` — entry bar data cannot be reconstructed (fallback)

---

### 8.4 `utils/failed_action_logger.py`

**Responsibility:** Append failed action records to `logs/failed_actions.csv`.

**CSV columns (exact order):**
```
timestamp_utc, order_id, symbol, action_type, entry_price, exit_price,
sl_price, tp_price, lot_size, pnl_usd, duration_minutes, failure_type,
signal_mode, timeframe, entry_bar_time, tenkan_at_entry, kijun_at_entry,
cloud_top_at_entry, cloud_bot_at_entry, cloud_pips_at_entry,
d1_cloud_direction, d1_price_vs_cloud, session_utc_hour,
conditions_met, risk_reward_planned, risk_reward_actual,
account_balance_at_entry, drawdown_pct_at_entry, notes
```

**Behaviour:**
- Create file with header row on first write if it does not exist
- Append (never overwrite) on subsequent writes
- All float values: 5 decimal places for prices, 2 for PnL and percentages
- `conditions_met` column: serialise as `"price_above_cloud=True|tk_above_kijun=True|chikou_clear=False|bullish_cloud=True"`
- Thread-safe: use a file lock or queue-based writer

---

### 8.5 `core/trade_event_listener.py`

**Responsibility:** Detect MT5 deal close events and trigger ActionVerifier.

**Polling approach** (Python-side, since Python MT5 lib doesn't support true callbacks):
```python
class TradeEventListener:
    def __init__(self, mt5: MT5Connector, verifier: ActionVerifier, logger: TradeLogger):
        self._known_deals: set[int] = set()   # deal tickets already processed

    def poll(self):
        """Called every cycle from trade_bot main loop."""
        recent_deals = self.mt5.get_deal_history(hours_back=24)
        for deal in recent_deals:
            if deal.ticket in self._known_deals:
                continue
            if deal.entry == DEAL_ENTRY_OUT:    # this is a close
                closed_trade = self._build_closed_trade(deal)
                self.logger.log(closed_trade)
                self.verifier.verify(closed_trade)
                self._known_deals.add(deal.ticket)
```

---

### 8.6 `core/session_filter.py`

```python
class SessionFilter:
    def __init__(self, config: SessionFilterConfig): ...

    def is_tradeable(self, now_utc: datetime) -> tuple[bool, str]:
        """Returns (True, "ok") or (False, reason)."""
        if not self.cfg.enabled:
            return True, "ok"
        hour = now_utc.hour
        if hour < self.cfg.start_hour_utc or hour >= self.cfg.end_hour_utc:
            return False, f"Outside session ({hour} UTC)"
        if now_utc.weekday() == 4 and hour >= 17 and not self.cfg.trade_friday_close:
            return False, "Friday close — no new trades"
        return True, "ok"
```

---

## 9. BUILD ORDER (completed)

All phases have been implemented and tested. Original build order preserved for reference:

| Phase | Files | Test Milestone |
|-------|-------|----------------|
| **1** | `config/strategy_config.json` → `core/config_loader.py` | Parse all v3 fields, fail on invalid values, print config summary |
| **2** | `core/candle_close_guard.py` → `core/ichimoku_calculator.py` | Calculate all 5 components on sim data, confirm live bar is never used |
| **3** | `core/signal_engine.py` | All 4 signal modes produce correct BUY/SELL/NEUTRAL on known test OHLCV |
| **4** | `core/lot_calculator.py` → `core/sltp_builder.py` → `core/risk_manager.py` | Lot, SL, TP correct for all methods and both JPY/non-JPY pairs |
| **5** | `core/mt5_connector.py` (simulation mode) → `core/order_executor.py` | Full trade lifecycle in sim: entry → trailing → exit → logged |
| **6** | `core/session_filter.py` → `core/trend_filter.py` → `core/break_even_manager.py` → `core/position_manager.py` | Position lifecycle complete with all filters active |
| **7** | `utils/failed_action_logger.py` → `core/action_verifier.py` → `core/trade_event_listener.py` | After sim close: CORRECT/INCORRECT scored, failed_actions.csv written correctly |
| **8** | `utils/trade_logger.py` → `utils/state.py` → `utils/dashboard_server.py` | Dashboard live at localhost:8000, shows signals + trades + verification stats |
| **9** | `trade_bot.py` (full orchestrator) | Full end-to-end sim run: 8 pairs scanned, signals fire, trades execute, verifier runs |
| **10** | `core/mt5_connector.py` (real MT5) | Connect to real demo terminal, first real order placed and verified |

---

## 10. `trades.csv` SCHEMA

Written by `utils/trade_logger.py` for every closed trade (win or loss).

```
order_id, symbol, action_type, entry_price, exit_price, sl_price, tp_price,
lot_size, pnl_usd, pnl_pips, duration_minutes, exit_reason,
signal_mode, timeframe, entry_bar_time, verification_result,
risk_per_trade_usd, risk_reward_planned, risk_reward_actual,
account_balance_before, account_balance_after, running_profit_pct
```

- `exit_reason`: `"tp"` | `"sl"` | `"trailing"` | `"ichimoku_exit"` | `"goal_halt"` | `"drawdown_halt"` | `"manual"`
- `verification_result`: `"CORRECT"` | `"INCORRECT:SL_HIT"` | `"INCORRECT:WEAK_SIGNAL"` | etc.

---

## 11. REQUIREMENTS

```
# requirements.txt
MetaTrader5>=5.0.45      # Windows only — bot runs in SIMULATION mode if not available
pandas>=2.0.0
numpy>=1.24.0
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
websockets>=12.0
python-dateutil>=2.8.2
filelock>=3.13.0         # For thread-safe CSV writing
```

---

## 12. SIMULATION MODE

When `MetaTrader5` library is not installed (Mac/Linux dev), `MT5Connector` falls back to simulation:
- `_simulate_bars()` generates realistic OHLCV with a bullish trend injected in the last 80 bars (ensures signals fire for testing)
- `send_order()` returns a fake order ID and logs `[SIM]` prefix
- `get_account_info()` returns a mock account with `balance=10000`, `equity=10000`, `currency="USD"`
- All other logic (Ichimoku, risk, verifier, CSV writing) runs identically to production

---

## 13. DASHBOARD REQUIREMENTS

The FastAPI dashboard at `http://localhost:8000` must display:

1. **Account panel**: Balance, Equity, Goal progress bar (% toward `target_profit_pct`)
2. **Signals table**: All 8 pairs — signal, close price, Tenkan, Kijun, cloud position, cloud thickness
3. **Open positions**: Symbol, direction, entry price, current SL, unrealised PnL, trailing status
4. **Trade log**: Last 20 closed trades with PnL and verification result (CORRECT/INCORRECT badge)
5. **Verification stats**: Total trades, correct count, incorrect count, most common failure type
6. **System log**: Last 30 log lines streamed via WebSocket

All data pushed via WebSocket every 2 seconds from `BotState.snapshot()`.

---

## 14. KEY DECISIONS SUMMARY (do not revisit without good reason)

| Decision | Rationale |
|----------|-----------|
| Ichimoku periods 9-26-52 | Hosoda's original. All reviewed MQL5 EAs use these. Do not change. |
| H4 primary + D1 confirmation | Industry standard for Ichimoku forex. Validated across 6 MQL5 EAs. |
| Signal on closed bar only | Prevents ghost signals, re-entry spam, unstable Ichimoku values. |
| Kijun-sen as default SL | Structurally correct — invalidation of trend. Used by all reviewed EAs. |
| 5 pip SL buffer | Prevents stop-hunting on indicator levels. Best practice from MQL5 forums. |
| 2:1 R:R default | Minimum for positive expectancy at typical ~45% win rate. |
| trail_step_pips = 5 | Prevents broker API spam from micro-adjustments. From CodeBase #21661. |
| Magic number isolation | Essential in shared accounts — never touch other EA's orders. |
| Post-close verification | Enables strategy learning loop via failed_actions.csv pattern analysis. |
| Demo mode safety lock | `demo_mode=true` in JSON refuses to connect to live account. |

---

*End of handoff document — Architecture Reference v3.0 (implementation complete)*
