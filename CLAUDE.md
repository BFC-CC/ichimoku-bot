# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Activate the project venv (do this first in every terminal)
source venv/bin/activate

# Install dependencies (one-shot setup; requires sudo for apt-get)
bash setup_env.sh
# or manually:
pip install -r requirements.txt

# Copy and populate secrets
cp .env.example .env   # then add DISCORD_WEBHOOK_URL

# Run all tests (no MT5 required)
pytest tests/ -v

# Run a single test file / single test function
pytest tests/test_indicator.py -v
pytest tests/test_signals.py -v -k "test_tk_cross"

# Run backtest (uses MT5 data if available, else synthetic data on Linux)
python run_backtest.py
python run_backtest.py --from 2024-01-01 --to 2024-12-31
python run_backtest.py --symbol EURUSD --tf H1
python run_backtest.py --dry-run    # skip CSV output

# Launch live bot (dry_run=true by default in config.yaml)
python bot.py
python bot.py --dry-run
python bot.py --config dev.yaml

# Launch Streamlit dashboard
streamlit run app.py   # http://localhost:8501

# Linux-only: start the mt5linux Wine bridge (keep running in a separate terminal)
python3 start_mt5_bridge.py

# ── v3 Trading Bot ──
python trade_bot.py                     # Normal run (config/strategy_config.json)
python trade_bot.py --sim               # Force simulation mode (no MT5 needed)
python trade_bot.py --sim --once        # Single cycle & exit (good for testing)

# v3 FastAPI dashboard (started automatically by trade_bot.py)
# http://localhost:8000 (HTML), /api/health (JSON)
```

## Architecture

Two independent systems coexist in this repo. They share `core/indicator.py` and `core/candle_buffer.py` but are otherwise separate — zero shared files are modified by both.

- **v1 Signal Bot**: `bot.py` + `config.yaml` + `signal_detector.py` → Discord notifications only
- **v3 Trading Bot**: `trade_bot.py` + `config/strategy_config.json` + `signal_engine.py` → full trade lifecycle (entry, position management, exit)

### v1 Signal Bot pipeline

The v1 pipeline follows: **data → buffer → indicator → detector → notifier**.
All layers are decoupled with dataclasses as configuration objects.

### Core pipeline (`core/`)
- `indicator.py` — Pure-pandas Ichimoku calculator. `IchimokuIndicator.calculate()` returns a full DataFrame; `latest_values()` returns a 16-key flat dict that feeds directly into `SignalDetector.check()`. Keys: `tenkan`, `kijun`, `senkou_a`, `senkou_b`, `chikou`, `close`, `cloud_top`, `cloud_bottom`, and `prev_*` variants of each. Both sides must agree on this contract.
- `signal_detector.py` — Stateful detector consuming the `latest_values()` dict. Maintains per-`(pair, timeframe, signal_type)` cooldown timers. Emits `Signal` dataclasses.
- `candle_buffer.py` — Rolling OHLC window with deduplication. Seeded with historical candles at startup, then appended to on each scheduler tick.
- `data_fetcher.py` — MT5 data layer (via `mt5linux` on Linux/Wine, native on Windows). Exposes `fetch_latest()`, `fetch_historical()`, and `fetch_from_date()`. Import chain: `MetaTrader5` → `mt5linux` → `MT5_AVAILABLE=False` (graceful degradation).
- `notifier.py` — Discord webhook client with retry and 429 rate-limit handling. `dry_run=True` logs instead of POSTing.

### Signal types
Six signal types exist in `SignalDetector.ALL_SIGNALS`:
- `tk_cross_up` / `tk_cross_down` — Tenkan crosses Kijun (+ optional cloud filter)
- `kumo_breakout_up` / `kumo_breakout_down` — Close crosses cloud boundary
- `chikou_cross_up` / `chikou_cross_down` — Chikou crosses close from 26 bars ago

**Config naming vs code naming:** `config.yaml` `enabled_signals` uses short names (`tk_cross`, `kumo_breakout`, `chikou_cross`). These map to both `_up` and `_down` variants. In the backtest, per-pair `enabled_signals` are respected. The live bot (`bot.py`) creates a single global `SignalDetector` with all signals enabled — per-pair filtering from config is not applied at runtime.

### Live bot (`bot.py`)
APScheduler fires `process_candle(symbol, timeframe)` at the close of each configured timeframe. Global `BotState` holds all component instances and per-pair `CandleBuffer`s. Each tick: fetch → append buffer → compute Ichimoku → detect signals → notify. H1 and H4 jobs fire 1 minute after candle close to avoid incomplete candles.

### Backtest (`backtest/`)
`BacktestEngine.run()` replays candles chronologically through the identical `CandleBuffer → IchimokuIndicator → SignalDetector` pipeline. `warmup_candles` (default 100, minimum 78) must elapse before signals are checked. When MT5 is unavailable (Linux without Wine bridge), `run_backtest.py` automatically falls back to `make_synthetic_candles()` — a deterministic random-walk seeded by symbol name. `backtest/report.py` exports CSV and prints a console summary.

### Dashboard (`app.py`, `gui/`)
Streamlit app with sidebar navigation. `gui/demo_data.py` provides synthetic data (no live connection needed), `gui/chart.py` renders Plotly Ichimoku charts, and `gui/live_feed.py` handles live data display. Reads and writes `config.yaml` live.

### Trading Bot v3 (`trade_bot.py`)
`TradeBotOrchestrator` drives a polling loop (configurable interval, default 60 s). Each cycle: fetch bars → compute Ichimoku → evaluate signal → apply filters → calculate lot → execute order → manage positions → poll trade events.

**Config & loading:** `config/strategy_config.json` (JSON, not YAML). `ConfigLoader.load()` parses it into typed dataclasses. `validation` section controls all optional features (all disabled by default). JPY pairs use pip size 0.01 vs 0.0001 for others.

**Signal engine** (`core/signal_engine.py`): 4 modes — `tk_cross`, `chikou_cross`, `kumo_breakout`, `full_confirm`. Returns `SignalResult` with BUY/SELL/NEUTRAL + score + conditions_met dict. `check_exit()` evaluates ichimoku-based exit conditions for open positions.

**Chikou clearance** (`ichimoku_calculator.py:is_chikou_clear()`): checks high-low range over 26 bars, not just close[-26]. Applies to all 4 signal modes when `require_chikou_clear=True`.

**Signal scoring** (disabled by default): 6-component weighted score (0–1). `signal_scoring.min_score_threshold` filters weak signals. `scale_lot_by_score` scales lot size proportionally.

**Lot calculation** (`core/lot_calculator.py`): 3 modes — `fixed`, `risk_pct`, `compound`. Score scaling applies `max(signal_score, 0.1)` — never zero. Rounds to `volume_step`, clamps to `[volume_min, volume_max]`.

**Risk management** (`core/risk_manager.py`): max open trades, daily loss limit (%), max drawdown (%). `RiskGuard` halts the bot when limits are breached.

**Position management**: `BreakEvenManager` moves SL to entry + lock_in_pips after trigger_pips profit. `PositionManager` handles trailing stops (kijun or fixed method) and ichimoku-based exit conditions.

**Optional validation layers** (all disabled by default via `validation` config section):
- `core/momentum.py` — RSI, ADX, EMA alignment, ATR consistency → 0–100 score
- `core/adversarial_validator.py` — 3 critics (logical/contextual/structural) → RTR score; rejects below `min_rtr_score`
- `signal_engine.py:classify_signal_strength()` — STRONG/MODERATE/WEAK classification with point system
- `action_verifier.py:verify_trade_quality()` — post-trade slippage/fill/spread checks
- Strength-based lot multiplier: STRONG=1.0, MODERATE=0.7, WEAK=0.4

**Health monitor** (`core/health_monitor.py`): tracks tick gaps, consecutive errors, connection loss. Discord alerts with cooldown.

**FastAPI dashboard** (`utils/dashboard_server.py`): HTML UI on port 8000, `/api/health` JSON endpoint, `/api/validation/metrics` when adversarial validation enabled. `KeepAlive` (`utils/keep_alive.py`) pings the dashboard for Render free-tier deployments.

### Configuration
`config.yaml` is the single source of truth for the **v1 Signal Bot** — pairs, timeframes, Ichimoku periods, signal behaviour, and backtest date ranges. Environment variables in the YAML (e.g. `${DISCORD_WEBHOOK_URL}`) are expanded at load time via `os.path.expandvars`. Secrets live in `.env` (loaded via `python-dotenv`).

`config/strategy_config.json` is the config for the **v3 Trading Bot** — typed JSON parsed into dataclasses by `ConfigLoader`.

### Linux / MT5 on Wine
On Linux, `mt5linux` communicates with a Windows MT5 terminal running inside Wine. Run `setup_mt5_wine.sh` once to configure Wine, then keep `start_mt5_bridge.py` running alongside the bot. The bridge listens on `localhost:18812`.

### Logging
All modules use `loguru.logger` (not stdlib `logging`). `bot.py:main()` configures loguru with daily rotation to `logs/bot.log`.

### Key constraints
- Ichimoku needs ≥78 candles for valid values (52 for Senkou B + 26 for displacement). `CandleBuffer` seeds with 300 candles by default.
- Chikou is the current close shifted back 26 bars; signal detection compares it against the close at that historical index — not the current close.
- All signal crossovers compare `prev_*` vs current values (two-bar edge detection).
- `CandleBuffer.append()` silently deduplicates by timestamp index; calling it with the same candle twice is safe.
- Tests mock MT5 entirely; `pytest tests/ -v` runs on any OS without a broker connection.
- `IchimokuValues` is a frozen dataclass (immutable for thread safety between bot loop and dashboard).
- `BotState` in `utils/state.py` uses `threading.Lock` for all reads/writes — dashboard accesses state from a different thread.
- `MT5Connector` uses `force_sim=True` in all tests — never connects to a real broker in CI.
- Lot score floor: `max(signal_score, 0.1)` ensures lot size is never zero when score scaling is enabled.
