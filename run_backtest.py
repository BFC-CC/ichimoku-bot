"""
run_backtest.py
─────────────────────────────────────────────────────────────────────────────
Backtest entry point.

Reads config.yaml, connects to MT5, fetches historical candles for every
configured pair/timeframe, runs the backtest engine, and prints a report.

Usage
-----
    python run_backtest.py                         # uses config.yaml defaults
    python run_backtest.py --from 2024-01-01 --to 2024-12-31
    python run_backtest.py --symbol EURUSD --tf H1
    python run_backtest.py --dry-run               # don't save CSV
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

# ── project imports ───────────────────────────────────────────────────────────
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.report import BacktestReport
from core.candle_buffer import CandleBuffer
from core.data_fetcher import MT5Config, MT5DataFetcher
from core.indicator import IchimokuConfig
from core.signal_detector import DetectorConfig, SignalDetector

# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()

ROOT = Path(__file__).parent


# ─────────────────────────────────────────────────────────────────────────────
#  Config loading
# ─────────────────────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    with open(ROOT / path) as f:
        cfg = yaml.safe_load(f)
    # Substitute env vars in string values  (e.g. "${DISCORD_WEBHOOK_URL}")
    def _expand(obj):
        if isinstance(obj, str):
            return os.path.expandvars(obj)
        if isinstance(obj, dict):
            return {k: _expand(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_expand(i) for i in obj]
        return obj
    return _expand(cfg)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Ichimoku Backtest Runner")
    parser.add_argument("--symbol", help="Override symbol (e.g. EURUSD)")
    parser.add_argument("--tf",     help="Override timeframe (e.g. H1)")
    parser.add_argument("--from",   dest="from_date", help="Start date YYYY-MM-DD")
    parser.add_argument("--to",     dest="to_date",   help="End date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Don't save CSV output")
    parser.add_argument("--config",  default="config.yaml")
    return parser.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args   = parse_args()
    config = load_config(args.config)

    # ── logging setup ─────────────────────────────────────────────────────────
    log_level = config.get("general", {}).get("log_level", "INFO")
    logger.remove()
    logger.add(sys.stderr, level=log_level, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")

    logger.info("=" * 55)
    logger.info("  Ichimoku Backtest Starting")
    logger.info("=" * 55)

    # ── build configs from YAML ───────────────────────────────────────────────
    ichi_cfg = config.get("ichimoku", {})
    ichimoku = IchimokuConfig(
        tenkan_period   = ichi_cfg.get("tenkan_period",   9),
        kijun_period    = ichi_cfg.get("kijun_period",   26),
        senkou_b_period = ichi_cfg.get("senkou_b_period", 52),
        displacement    = ichi_cfg.get("displacement",   26),
        chikou_shift    = ichi_cfg.get("chikou_shift",   26),
    )

    sig_cfg = config.get("signals", {})
    detector_cfg = DetectorConfig(
        cooldown_minutes  = sig_cfg.get("cooldown_minutes", 30),
        cloud_filter      = sig_cfg.get("cloud_filter", True),
        strong_signal_only= sig_cfg.get("strong_signal_only", False),
    )

    bt_cfg_raw = config.get("backtest", {})
    backtest_cfg = BacktestConfig(
        ichimoku  = ichimoku,
        detector  = detector_cfg,
        warmup_candles = 100,
        buffer_size    = 300,
    )

    # ── date range ────────────────────────────────────────────────────────────
    from_str = args.from_date or bt_cfg_raw.get("from_date", "2024-01-01")
    to_str   = args.to_date   or bt_cfg_raw.get("to_date",   "2024-12-31")
    from_dt  = datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    to_dt    = datetime.strptime(to_str,   "%Y-%m-%d").replace(tzinfo=timezone.utc)

    # ── determine which pairs/timeframes to backtest ──────────────────────────
    pairs_cfg = config.get("pairs", [])

    if args.symbol and args.tf:
        # Single override from CLI — use all signal types
        pairs_cfg = [{
            "symbol": args.symbol,
            "timeframes": [args.tf],
            "enabled_signals": list(SignalDetector.ALL_SIGNALS),
        }]
    elif args.symbol:
        pairs_cfg = [p for p in pairs_cfg if p["symbol"] == args.symbol]

    if not pairs_cfg:
        logger.error("No pairs configured or found.  Check config.yaml.")
        sys.exit(1)

    # ── connect to MT5 ────────────────────────────────────────────────────────
    broker_cfg = config.get("broker", {}).get("mt5", {})
    mt5_config = MT5Config(
        login    = broker_cfg.get("login", 0) or 0,
        server   = broker_cfg.get("server", "") or "",
        password = broker_cfg.get("password", "") or "",
    )

    fetcher = MT5DataFetcher(mt5_config)
    fetcher.connect()

    # ── run backtests ─────────────────────────────────────────────────────────
    engine  = BacktestEngine(backtest_cfg)
    report  = BacktestReport()

    try:
        for pair_entry in pairs_cfg:
            symbol   = pair_entry["symbol"]
            timeframes = pair_entry["timeframes"]
            enabled  = set(pair_entry.get("enabled_signals", []))

            for tf in timeframes:
                logger.info(f"Fetching candles: {symbol} {tf} | {from_str} → {to_str}")
                try:
                    candles = fetcher.fetch_from_date(symbol, tf, from_dt, to_dt)
                except Exception as exc:
                    logger.error(f"Failed to fetch {symbol} {tf}: {exc}")
                    continue

                if len(candles) < 150:
                    logger.warning(
                        f"Only {len(candles)} candles for {symbol} {tf} – "
                        f"skipping (need at least 150)."
                    )
                    continue

                signals = engine.run(
                    symbol=symbol,
                    timeframe=tf,
                    candles=candles,
                    enabled_signals=enabled or None,
                )
                report.add_results(symbol, tf, signals)
    finally:
        fetcher.disconnect()

    # ── output ────────────────────────────────────────────────────────────────
    report.print_summary()

    if not args.dry_run:
        output_dir = bt_cfg_raw.get("output_dir", "./backtest_results")
        timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path   = os.path.join(output_dir, f"signals_{timestamp}.csv")
        report.save_csv(csv_path)
        logger.info(f"Results saved to {csv_path}")


if __name__ == "__main__":
    main()
