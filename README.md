# Ichimoku Kinko Hyo Forex Trading System

Two coexisting systems — a **signal bot** (Discord alerts) and a **fully automated trading bot** — built on the Ichimoku Kinko Hyo indicator with MetaTrader 5.

---

## Features

### Signal Bot (v1) — `bot.py`
- **6 signal types** — TK Cross, Kumo Breakout, and Chikou Cross (BUY & SELL for each)
- **Cloud filter** — TK crosses only fire when price is on the correct side of the cloud
- **Per-signal cooldown** — prevents duplicate alerts on the same condition
- **Live scheduler** — APScheduler fires jobs at the close of each configured timeframe
- **Backtest engine** — zero look-ahead bias, same pipeline as live
- **Discord embeds** — colour-coded, rich-field notifications with retry + rate-limit handling

### Trading Bot (v3) — `trade_bot.py`
- **4 signal modes** — `tk_cross`, `chikou_cross`, `kumo_breakout`, `full_confirm`
- **Chikou clearance** — validates Chikou against high-low range (not just close[-26])
- **Signal scoring** — 6-component weighted score (0–1) with configurable threshold
- **Full trade lifecycle** — entry, break-even, trailing stop, ichimoku-based exits
- **Risk management** — per-trade risk %, max open trades, daily loss cap, max drawdown halt
- **3 lot modes** — `fixed`, `risk_pct`, `compound` with optional score-based scaling
- **Filters** — session hours, D1 trend confirmation, news calendar blackouts
- **Health monitoring** — tick gap detection, error tracking, Discord alerts
- **FastAPI dashboard** — live HTML UI + `/api/health` JSON endpoint on port 8000
- **Optional validation layers** — adversarial validation, momentum scoring, signal strength classification

### Shared
- **375 tests** — full coverage of all modules, no MT5 required
- **Simulation mode** — runs on any OS without a broker connection
- **Streamlit dashboard** — Plotly Ichimoku charts with synthetic data

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Broker data | MetaTrader 5 (Windows native / Linux via Wine + mt5linux) |
| v1 Scheduler | APScheduler 3.x |
| v3 Dashboard | FastAPI + WebSocket (port 8000) |
| Streamlit UI | Streamlit + Plotly (port 8501) |
| Notifications | Discord Webhooks |
| v1 Config | YAML (`config.yaml`) + `.env` |
| v3 Config | JSON (`config/strategy_config.json`) |
| Thread safety | `threading.Lock` (state), `filelock` (CSV) |
| Tests | pytest |

---

## Project Structure

```
Colpo_Groso_BFC/
│
├── config/
│   └── strategy_config.json          # v3 config — all trading parameters
│
├── core/
│   ├── indicator.py                  # Shared: pure-pandas Ichimoku calculator (9/26/52)
│   ├── candle_buffer.py              # Shared: rolling OHLC window with dedup
│   ├── signal_detector.py            # v1: 6 signal rules + cooldown registry
│   ├── data_fetcher.py               # v1: MT5 data layer with retry
│   ├── notifier.py                   # v1: Discord webhook client
│   ├── config_loader.py              # v3: JSON → typed dataclasses with validation
│   ├── candle_close_guard.py         # v3: strip live bar, track last processed bar
│   ├── ichimoku_calculator.py        # v3: frozen IchimokuValues snapshot
│   ├── signal_engine.py              # v3: 4 signal modes + scoring + exit conditions
│   ├── lot_calculator.py             # v3: risk_pct / fixed / compound lot sizing
│   ├── sltp_builder.py               # v3: SL/TP for kijun, ATR, cloud_edge, fixed_pips
│   ├── risk_manager.py               # v3: RiskGuard (goal, drawdown, daily loss)
│   ├── mt5_connector.py              # v3: MT5 bridge + simulation fallback
│   ├── order_executor.py             # v3: send orders with retry + magic number
│   ├── session_filter.py             # v3: UTC hour window + Friday filter
│   ├── trend_filter.py               # v3: D1 cloud direction check
│   ├── news_filter.py                # v3: static calendar blackout windows
│   ├── news_calendar.py              # v3: recurring + specific date event matching
│   ├── break_even_manager.py         # v3: move SL to entry after trigger_pips profit
│   ├── position_manager.py           # v3: trailing stop + ichimoku exit conditions
│   ├── action_verifier.py            # v3: post-trade quality + failure classification
│   ├── trade_event_listener.py       # v3: poll MT5 deal history for closes
│   ├── health_monitor.py             # v3: tick gaps, errors, Discord alerts
│   ├── adversarial_validator.py      # v3: 3-critic RTR scoring (optional)
│   └── momentum.py                   # v3: RSI, ADX, EMA, ATR scoring (optional)
│
├── backtest/
│   ├── engine.py                     # Candle-by-candle replay engine
│   └── report.py                     # CSV export + console summary
│
├── utils/
│   ├── logger.py                     # Loguru setup from config
│   ├── trade_logger.py               # Write/append trades.csv
│   ├── failed_action_logger.py       # Write/append failed_actions.csv
│   ├── state.py                      # Thread-safe shared bot state (BotState)
│   ├── dashboard_server.py           # FastAPI + WebSocket HTML dashboard
│   ├── state_pusher.py               # Push state to remote dashboard
│   ├── keep_alive.py                 # Background ping for Render free tier
│   └── verify_deploy.py              # Screenshot + health check verification
│
├── data/
│   └── news_events.json              # FOMC, NFP, ECB, BOJ dates for news filter
│
├── gui/
│   ├── demo_data.py                  # Synthetic data for Streamlit
│   ├── chart.py                      # Plotly Ichimoku charts
│   └── live_feed.py                  # Live data display
│
├── tests/                            # 375 tests (36 test files + validation/)
├── prompts/                          # Research agent prompts
│
├── bot.py                            # v1: Signal bot entry point
├── trade_bot.py                      # v3: Trading bot entry point
├── run_backtest.py                   # Backtest CLI entry point
├── app.py                            # Streamlit dashboard entry point
├── config.yaml                       # v1 config: pairs, timeframes, signals
├── .env.example                      # Secret template
├── requirements.txt
└── setup_env.sh                      # One-shot environment bootstrap
```

---

## Quick Start

### 1. Install dependencies

```bash
bash setup_env.sh
# or manually:
pip install -r requirements.txt
```

### 2. Configure secrets

```bash
cp .env.example .env
```

Edit `.env` and add your Discord webhook URL:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

### 3. Run tests (no MT5 required)

```bash
source venv/bin/activate
pytest tests/ -v
```

### 4. Signal Bot (v1)

Edit `config.yaml` to set pairs and signals:

```yaml
pairs:
  - symbol: EURUSD
    timeframes: [H1, H4]
    enabled_signals:
      - tk_cross
      - kumo_breakout
      - chikou_cross
```

```bash
python bot.py              # dry_run=true by default
python bot.py --dry-run    # force dry run (no Discord messages)
```

### 5. Trading Bot (v3)

Edit `config/strategy_config.json` to set pairs, signal mode, and risk parameters.

```bash
python trade_bot.py                # uses config/strategy_config.json
python trade_bot.py --sim          # force simulation mode (no MT5 needed)
python trade_bot.py --sim --once   # single cycle & exit (good for testing)
```

The FastAPI dashboard starts automatically at `http://localhost:8000`.

### 6. Backtest

```bash
python run_backtest.py                                # full config
python run_backtest.py --from 2024-01-01 --to 2024-12-31
python run_backtest.py --symbol EURUSD --tf H1
python run_backtest.py --dry-run                      # skip CSV output
```

### 7. Streamlit Dashboard

```bash
streamlit run app.py   # http://localhost:8501
```

### 8. Linux: MT5 via Wine Bridge

```bash
bash setup_mt5_wine.sh              # one-time Wine setup
python3 start_mt5_bridge.py         # keep running in separate terminal
```

---

## Signal Types

### v1 Signal Bot (6 types)

| Signal | Direction | Condition |
|---|---|---|
| `tk_cross_up` | BUY | Tenkan crosses above Kijun |
| `tk_cross_down` | SELL | Tenkan crosses below Kijun |
| `kumo_breakout_up` | BUY | Close crosses above the cloud |
| `kumo_breakout_down` | SELL | Close crosses below the cloud |
| `chikou_cross_up` | BUY | Chikou crosses above close from 26 bars ago |
| `chikou_cross_down` | SELL | Chikou crosses below close from 26 bars ago |

**Cloud Filter:** When `cloud_filter: true` (default), TK crosses only fire when price is on the correct side of the cloud.

**Cooldown:** `cooldown_minutes: 30` (default) per `(pair, timeframe, signal_type)`.

### v3 Trading Bot (4 modes)

| Mode | Speed | Entry Conditions |
|---|---|---|
| `tk_cross` | Fastest | TK cross + price vs cloud + (optional) chikou clear |
| `chikou_cross` | Moderate | Chikou crosses close[-26] + chikou above cloud at -26 + close above cloud |
| `kumo_breakout` | Moderate | Price breaks cloud boundary + (optional) future cloud bullish |
| `full_confirm` | Conservative | All: price > cloud + TK alignment + chikou clear + bullish cloud + min thickness |

All modes evaluate on **closed bars only** (live bar is always stripped).

---

## v3 Configuration Reference

`config/strategy_config.json` — full schema:

```json
{
  "account":          { "login": 0, "password": "", "server": "", "demo_mode": true },
  "goal":             { "target_profit_pct": 10.0, "notify_on_goal": true },
  "ichimoku": {
    "tenkan_period": 9, "kijun_period": 26, "senkou_b_period": 52, "displacement": 26,
    "signal_mode": "tk_cross",
    "entry_conditions": {
      "require_price_above_cloud": true, "require_tenkan_above_kijun": true,
      "require_chikou_clear": true, "require_bullish_cloud": true,
      "require_future_cloud_bullish": false
    },
    "exit_conditions": {
      "exit_on_tk_cross_against": true, "exit_on_price_enter_cloud": false,
      "exit_on_chikou_cross_down": false
    },
    "cloud_min_thickness_pips": 5, "use_virtual_tp": false,
    "signal_scoring": {
      "enabled": false, "min_score_threshold": 0.5, "scale_lot_by_score": false,
      "weights": {
        "tk_alignment": 0.15, "price_vs_cloud": 0.20, "chikou_clear": 0.20,
        "cloud_direction": 0.15, "cloud_thickness": 0.10, "trend_filter": 0.20
      }
    }
  },
  "pairs": ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","EURGBP","NZDUSD","EURJPY"],
  "timeframes":       { "primary": "H4", "confirmation": "D1" },
  "session_filter":   { "enabled": true, "start_hour_utc": 7, "end_hour_utc": 20, "trade_friday_close": false },
  "news_filter":      { "enabled": false, "minutes_before": 30, "minutes_after": 30, "impact_levels": ["high"] },
  "risk_management": {
    "risk_per_trade_pct": 1.0, "max_open_trades": 3,
    "max_daily_loss_pct": 3.0, "max_drawdown_pct": 8.0,
    "lot_mode": "risk_pct", "fixed_lot_size": 0.01,
    "stop_loss":    { "method": "kijun", "fixed_pips": 40, "atr_period": 14, "atr_multiplier": 1.5, "buffer_pips": 5 },
    "take_profit":  { "method": "ratio", "rr_ratio": 2.0, "fixed_pips": 80 },
    "break_even":   { "enabled": true, "trigger_pips": 20, "lock_in_pips": 2 },
    "trailing_stop": { "enabled": true, "method": "kijun", "fixed_trail_pips": 20, "trail_step_pips": 5 }
  },
  "execution":        { "slippage_points": 20, "magic_number": 20260309, "order_comment": "IchiBot_v3", "retry_attempts": 3, "retry_delay_ms": 500, "use_market_orders": true },
  "scheduler":        { "bar_check_interval_sec": 60, "use_ontrade_transaction": true },
  "logging":          { "level": "INFO", "log_to_file": true, "log_dir": "logs", "max_file_mb": 10, "log_trades_csv": true },
  "dashboard":        { "enabled": true, "host": "0.0.0.0", "port": 8000 },
  "health_monitor":   { "enabled": true, "max_tick_gap_sec": 300, "max_consecutive_errors": 3, "alert_cooldown_sec": 900 },
  "validation": {
    "adversarial_validation": false, "min_rtr_score": 0.6,
    "momentum_scoring": false, "strength_classification": false,
    "quality_checks": { "max_slippage_pips": 3.0, "min_fill_ratio": 0.95, "max_spread_pips": 5.0 },
    "strength_lot_multiplier": { "STRONG": 1.0, "MODERATE": 0.7, "WEAK": 0.4 }
  }
}
```

### Config Validation Rules (enforced by ConfigLoader)
- `tenkan_period < kijun_period < senkou_b_period` — strictly ascending
- `signal_mode` must be one of: `tk_cross`, `chikou_cross`, `kumo_breakout`, `full_confirm`
- `lot_mode` must be one of: `risk_pct`, `fixed`, `compound`
- `stop_loss.method` must be one of: `kijun`, `atr`, `cloud_edge`, `fixed_pips`
- `take_profit.method` must be one of: `ratio`, `next_cloud`, `fixed_pips`
- `0 < risk_per_trade_pct <= 5`
- `take_profit.rr_ratio >= 1.0`
- `target_profit_pct > 0`
- `pairs` list must not be empty

---

## v1 Configuration Reference

`config.yaml`:

```yaml
general:
  log_level: INFO        # DEBUG | INFO | WARNING | ERROR
  dry_run: true          # true = log only, no Discord messages

ichimoku:
  tenkan_period: 9
  kijun_period: 26
  senkou_b_period: 52
  displacement: 26
  chikou_shift: 26

signals:
  cooldown_minutes: 30
  cloud_filter: true
  strong_signal_only: false

backtest:
  from_date: "2024-01-01"
  to_date:   "2024-12-31"
  output_dir: "./backtest_results"
```

---

## Deployment

### Local (development)

```bash
source venv/bin/activate
python trade_bot.py --sim --once    # verify single cycle
python trade_bot.py --sim           # continuous sim mode
```

### Render (free tier)

The v3 dashboard deploys to Render. Key settings:

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `python trade_bot.py --sim`
- **Health check path:** `/api/health`
- **Port:** `8000`

The built-in `KeepAlive` thread pings the dashboard URL at a configurable interval (default 600s) to prevent Render free-tier spin-down. Set `dashboard.keep_alive_url` in `strategy_config.json`.

### Deployment verification

```bash
python utils/verify_deploy.py --url https://your-app.onrender.com
```

Runs three checks: health endpoint, screenshot capture (headless Firefox), and image content validation.

### Remote state push

For split deployments (bot on one server, dashboard on another):

```bash
python trade_bot.py --dashboard-url https://your-dashboard.onrender.com --dashboard-secret mysecret
```

---

## Running Tests

No MT5 terminal required — all 375 tests run on any OS.

```bash
pytest tests/ -v
```

| Test area | Files | What it covers |
|---|---|---|
| Ichimoku math | `test_indicator.py`, `test_ichimoku_calculator.py` | Senkou shift, Chikou, frozen values, NaN handling |
| v1 Signals | `test_signals.py` | All 6 signal types, cloud filter, cooldown |
| v3 Signal engine | `test_signal_engine.py`, `test_signal_scoring.py`, `test_signal_strength.py` | 4 modes, scoring, strength classification |
| Chikou clearance | `test_chikou_clearance.py` | High-low range validation |
| Candle handling | `test_candle_buffer.py`, `test_candle_close_guard.py` | Seed, append, dedup, live bar strip |
| Data layer | `test_data_fetcher.py`, `test_mt5_connector.py` | MT5 config, sim fallback, data fetching |
| Risk & lots | `test_lot_calculator.py`, `test_risk_manager.py`, `test_sltp_builder.py` | All lot modes, SL/TP methods, JPY pip math |
| Position mgmt | `test_position_manager.py`, `test_break_even_manager.py` | Trailing, break-even, exit conditions |
| Filters | `test_session_filter.py`, `test_trend_filter.py`, `test_news_filter_v2.py` | Session hours, D1 cloud, news blackout |
| Execution | `test_order_executor.py`, `test_trade_event_listener.py` | Order retry, deal polling |
| Verification | `test_action_verifier.py`, `test_post_trade_quality.py` | PnL scoring, failure classification, quality checks |
| Validation | `test_adversarial_validator.py`, `test_momentum.py` | RTR scoring, momentum components |
| Health | `test_health_monitor.py`, `test_keep_alive.py` | Tick gaps, error tracking, ping thread |
| Logging & state | `test_config_loader.py`, `test_failed_action_logger.py`, `test_state.py`, `test_trade_logger.py` | Config parsing, CSV writing, thread-safe state |
| Notifications | `test_notifier.py` | Payload formatting, dry_run, HTTP retry, 429 handling |
| Backtest | `test_backtest_engine.py`, `test_backtest_report.py` | Replay engine, warmup, CSV export |
| Integration | `test_trade_bot.py` | Orchestrator wiring |
| Historical | `tests/validation/test_h2_historical.py` | H2 timeframe signal validation on known patterns |

---

## Timeframe → Cron Schedule (v1 Signal Bot)

| Timeframe | Fires |
|---|---|
| M1 | Every minute |
| M5 | Every 5 minutes |
| M15 | Every 15 minutes |
| M30 | Every 30 minutes |
| H1 | 1 minute past each hour |
| H4 | 1 minute past 00:00, 04:00, 08:00 … |
| D1 | 00:01 UTC daily |

---

## License

MIT
