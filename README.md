# Ichimoku Kinko Hyo Forex Signal Bot

A production-ready Forex signal bot built on the **Ichimoku Kinko Hyo** indicator.
Connects to MetaTrader 5, detects 6 signal types across multiple pairs and timeframes,
sends rich Discord notifications, and includes a full candle-by-candle backtest engine.

---

## Features

- **6 signal types** — TK Cross, Kumo Breakout, and Chikou Cross (BUY & SELL for each)
- **Cloud filter** — TK crosses only fire when price is on the correct side of the cloud
- **Per-signal cooldown** — prevents duplicate alerts on the same condition
- **Live scheduler** — APScheduler fires jobs at the close of each configured timeframe
- **Backtest engine** — zero look-ahead bias, same pipeline as live
- **Discord embeds** — colour-coded, rich-field notifications with retry + rate-limit handling
- **133 unit tests** — full coverage of all modules (no MT5 required)

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Broker data | MetaTrader 5 (Windows) |
| Scheduler | APScheduler 3.x |
| Notifications | Discord Webhooks |
| Config | YAML + `.env` |
| Tests | pytest |

---

## Project Structure

```
ichimoku-bot/
├── core/
│   ├── indicator.py          # Ichimoku math engine (9/26/52)
│   ├── signal_detector.py    # 6 signal rules + cooldown registry
│   ├── candle_buffer.py      # Rolling OHLC window
│   ├── data_fetcher.py       # MT5 data layer with retry
│   └── notifier.py           # Discord webhook client
├── backtest/
│   ├── engine.py             # Candle-by-candle replay engine
│   └── report.py             # CSV export + console summary
├── tests/
│   ├── test_indicator.py
│   ├── test_signals.py
│   ├── test_candle_buffer.py
│   ├── test_notifier.py
│   ├── test_data_fetcher.py
│   ├── test_backtest_engine.py
│   └── test_backtest_report.py
├── bot.py                    # Live bot entry point
├── run_backtest.py           # Backtest CLI entry point
├── config.yaml               # Pairs, timeframes, signal settings
├── .env.example              # Secret template
├── requirements.txt
└── setup_env.sh              # One-shot environment bootstrap
```

---

## Quick Start

### 1. Install dependencies

```bash
bash setup_env.sh
# or manually:
pip install -r requirements.txt
```

> **Note:** MetaTrader 5 must be installed and running on the **same Windows machine**.
> The `MetaTrader5` Python package communicates with the terminal directly and is Windows-only.

### 2. Configure secrets

```bash
cp .env.example .env
```

Edit `.env` and add your Discord webhook URL:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

Get a webhook URL from: Discord server → **Settings → Integrations → Webhooks → New Webhook → Copy URL**

### 3. Configure pairs and signals

Edit `config.yaml`:

```yaml
pairs:
  - symbol: EURUSD
    timeframes: [H1, H4]
    enabled_signals:
      - tk_cross
      - kumo_breakout
      - chikou_cross
```

### 4. Run backtest

```bash
python run_backtest.py                          # full config
python run_backtest.py --from 2024-01-01 --to 2024-12-31
python run_backtest.py --symbol EURUSD --tf H1
python run_backtest.py --dry-run               # skip CSV output
```

### 5. Go live

```bash
python bot.py              # dry_run=true by default (config.yaml)
python bot.py --dry-run    # force dry run (no Discord messages sent)
```

Set `dry_run: false` in `config.yaml` when ready for real alerts.

---

## Signal Types

| Signal | Direction | Condition |
|---|---|---|
| `tk_cross_up` | BUY | Tenkan crosses above Kijun |
| `tk_cross_down` | SELL | Tenkan crosses below Kijun |
| `kumo_breakout_up` | BUY | Close crosses above the cloud |
| `kumo_breakout_down` | SELL | Close crosses below the cloud |
| `chikou_cross_up` | BUY | Chikou crosses above close from 26 bars ago |
| `chikou_cross_down` | SELL | Chikou crosses below close from 26 bars ago |

### Cloud Filter
When `cloud_filter: true` (default), TK crosses are only fired when price is already on the correct side of the cloud — significantly reducing false signals.

### Cooldown
`cooldown_minutes: 30` (default) — each `(pair, timeframe, signal_type)` combination has its own independent cooldown timer.

---

## Configuration Reference

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

## Running Tests

No MT5 terminal required — all 133 tests run on any OS.

```bash
pytest tests/ -v
```

```
133 passed in 9.85s
```

| Test file | Tests | What it covers |
|---|---|---|
| `test_indicator.py` | 15 | Ichimoku math, Senkou shift, Chikou, NaN handling |
| `test_signals.py` | 20 | All 6 signal types, cloud filter, cooldown, NaN guard |
| `test_candle_buffer.py` | 20 | seed, append, deduplication, trimming, properties |
| `test_notifier.py` | 19 | Payload formatting, dry_run, HTTP retry, 429 handling |
| `test_data_fetcher.py` | 16 | MT5Config, `_utc()`, `_rates_to_df()`, env guard |
| `test_backtest_engine.py` | 12 | run(), warmup boundary, filters, independence |
| `test_backtest_report.py` | 17 | CSV export, summary printing, DataFrame output |

---

## Timeframe → Cron Schedule

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
