# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (one-shot setup)
bash setup_env.sh
# or manually:
pip install -r requirements.txt

# Copy and populate secrets
cp .env.example .env   # then add DISCORD_WEBHOOK_URL

# Run all tests (no MT5 required)
pytest tests/ -v

# Run a single test file
pytest tests/test_indicator.py -v

# Run backtest (uses yfinance or MT5 data)
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
- `indicator.py` — Pure-pandas Ichimoku calculator. `IchimokuIndicator.calculate()` returns a full DataFrame; `latest_values()` returns a flat dict (current + previous values for each line) that feeds directly into `SignalDetector.check()`.
- `signal_detector.py` — Stateful detector consuming the `latest_values()` dict. Maintains per-`(pair, timeframe, signal_type)` cooldown timers. Emits `Signal` dataclasses.
- `candle_buffer.py` — Rolling OHLC window with deduplication. Seeded with historical candles at startup, then appended to on each scheduler tick.
- `data_fetcher.py` — MT5 data layer (via `mt5linux` on Linux/Wine, native on Windows). Exposes `fetch_latest()` and `fetch_historical()`.
- `notifier.py` — Discord webhook client with retry and 429 rate-limit handling. `dry_run=True` logs instead of POSTing.

### Live bot (`bot.py`)
APScheduler fires `process_candle(symbol, timeframe)` at the close of each configured timeframe. Global `BotState` holds all component instances and per-pair `CandleBuffer`s. Each tick: fetch → append buffer → compute Ichimoku → detect signals → notify.

### Backtest (`backtest/`)
`BacktestEngine.run()` replays candles chronologically through the identical `CandleBuffer → IchimokuIndicator → SignalDetector` pipeline. `warmup_candles` (default 100, minimum 78) must elapse before signals are checked. `backtest/report.py` exports CSV and prints a console summary.

### Dashboard (`app.py`, `gui/`)
Streamlit app with sidebar navigation. Uses `gui/demo_data.py` for synthetic data (no live connection needed) and `gui/chart.py` (Plotly) for Ichimoku chart rendering. Reads and writes `config.yaml` live.

### Configuration
`config.yaml` is the single source of truth for pairs, timeframes, Ichimoku periods, signal behaviour, and backtest date ranges. Environment variables in the YAML (e.g. `${DISCORD_WEBHOOK_URL}`) are expanded at load time via `os.path.expandvars`. Secrets live in `.env` (loaded via `python-dotenv`).

### Linux / MT5 on Wine
On Linux, `mt5linux` communicates with a Windows MT5 terminal running inside Wine. Run `setup_mt5_wine.sh` once to configure Wine, then keep `start_mt5_bridge.py` running alongside the bot. The bridge listens on `localhost:18812`.

### Key constraints
- Ichimoku needs ≥78 candles for valid values (52 for Senkou B + 26 for displacement). `CandleBuffer` seeds with 300 candles by default.
- Chikou is the current close shifted back 26 bars; signal detection compares it against the close at that historical index — not the current close.
- All signal crossovers compare `prev_*` vs current values (two-bar edge detection).
- Tests mock MT5 entirely; `pytest tests/ -v` runs on any OS without a broker connection.
