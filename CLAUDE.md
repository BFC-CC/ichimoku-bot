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
```

## Architecture

The codebase follows a strict layered pipeline: **data → buffer → indicator → detector → notifier**.
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

### Configuration
`config.yaml` is the single source of truth for pairs, timeframes, Ichimoku periods, signal behaviour, and backtest date ranges. Environment variables in the YAML (e.g. `${DISCORD_WEBHOOK_URL}`) are expanded at load time via `os.path.expandvars`. Secrets live in `.env` (loaded via `python-dotenv`).

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
