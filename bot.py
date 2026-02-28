"""
bot.py
─────────────────────────────────────────────────────────────────────────────
Live Ichimoku bot.

Uses APScheduler to fire a candle-processing job at the close of every
configured timeframe.  On each tick:
  1. Fetch the latest closed candle from MT5
  2. Append it to the rolling buffer
  3. Compute Ichimoku indicators
  4. Check for signals
  5. Send Discord notifications for any new signals

Timeframe → cron schedule mapping:
  M1  → every minute
  M5  → every 5 minutes
  M15 → every 15 minutes
  M30 → every 30 minutes
  H1  → top of every hour
  H4  → every 4 hours  (00:00, 04:00, 08:00, …)
  D1  → daily at 00:00 UTC

Usage
-----
    python bot.py                   # normal run (respects dry_run in config)
    python bot.py --dry-run         # force dry run regardless of config
    python bot.py --config dev.yaml
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Set, Tuple

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from loguru import logger

from core.candle_buffer import CandleBuffer
from core.data_fetcher import MT5Config, MT5DataFetcher
from core.indicator import IchimokuConfig, IchimokuIndicator
from core.notifier import DiscordNotifier
from core.signal_detector import DetectorConfig, SignalDetector

load_dotenv()
ROOT = Path(__file__).parent


# ─────────────────────────────────────────────────────────────────────────────
#  Timeframe → cron trigger mapping
# ─────────────────────────────────────────────────────────────────────────────

_TF_CRON: Dict[str, dict] = {
    "M1":  dict(minute="*"),
    "M5":  dict(minute="*/5"),
    "M15": dict(minute="*/15"),
    "M30": dict(minute="*/30"),
    "H1":  dict(minute=1),                    # fire 1 min after candle close
    "H4":  dict(hour="*/4", minute=1),
    "D1":  dict(hour=0, minute=1),
}


# ─────────────────────────────────────────────────────────────────────────────
#  Config loading
# ─────────────────────────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)

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
#  Bot state (global, shared across scheduler jobs)
# ─────────────────────────────────────────────────────────────────────────────

class BotState:
    def __init__(self):
        # (symbol, timeframe) → CandleBuffer
        self.buffers:   Dict[Tuple[str, str], CandleBuffer]  = {}
        self.indicator: IchimokuIndicator = None
        self.detector:  SignalDetector    = None
        self.fetcher:   MT5DataFetcher    = None
        self.notifier:  DiscordNotifier   = None
        self.last_heartbeat: datetime     = datetime.now(timezone.utc)

    def heartbeat(self):
        self.last_heartbeat = datetime.now(timezone.utc)


_state = BotState()


# ─────────────────────────────────────────────────────────────────────────────
#  Per-candle job (called by scheduler)
# ─────────────────────────────────────────────────────────────────────────────

def process_candle(symbol: str, timeframe: str) -> None:
    """
    Fetch the latest closed candle, update the buffer, compute Ichimoku,
    check signals, and fire Discord notifications.
    """
    try:
        key = (symbol, timeframe)
        buffer = _state.buffers.get(key)
        if buffer is None:
            logger.error(f"No buffer found for {symbol} {timeframe} – skipping.")
            return

        # Fetch the latest 3 candles (in case we missed one)
        new_candles = _state.fetcher.fetch_latest(symbol, timeframe, count=3)
        if new_candles.empty:
            logger.warning(f"No candles returned for {symbol} {timeframe}.")
            return

        buffer.append(new_candles)

        if not buffer.is_ready:
            logger.debug(f"{symbol} {timeframe}: buffer not yet ready ({buffer.size} candles).")
            return

        # Compute indicators
        ind = _state.indicator.latest_values(buffer.data)

        # Detect signals
        candle_time = buffer.latest_time.to_pydatetime().replace(tzinfo=timezone.utc)
        signals = _state.detector.check(
            pair=symbol,
            timeframe=timeframe,
            indicators=ind,
            candle_time=candle_time,
        )

        # Send notifications
        for sig in signals:
            _state.notifier.send(sig)

        _state.heartbeat()
        logger.debug(
            f"Tick complete: {symbol} {timeframe} | "
            f"signals={len(signals)} | buffer={buffer.size}"
        )

    except Exception as exc:
        logger.exception(f"Unhandled error in process_candle({symbol}, {timeframe}): {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Initialisation
# ─────────────────────────────────────────────────────────────────────────────

def initialise(config: dict, dry_run: bool = False) -> None:
    """Wire up all components and seed buffers with historical data."""
    global _state

    ichi_raw = config.get("ichimoku", {})
    ichimoku_cfg = IchimokuConfig(
        tenkan_period   = ichi_raw.get("tenkan_period",   9),
        kijun_period    = ichi_raw.get("kijun_period",   26),
        senkou_b_period = ichi_raw.get("senkou_b_period", 52),
        displacement    = ichi_raw.get("displacement",   26),
        chikou_shift    = ichi_raw.get("chikou_shift",   26),
    )

    sig_raw = config.get("signals", {})
    detector_cfg = DetectorConfig(
        cooldown_minutes   = sig_raw.get("cooldown_minutes", 30),
        cloud_filter       = sig_raw.get("cloud_filter", True),
        strong_signal_only = sig_raw.get("strong_signal_only", False),
    )

    _state.indicator = IchimokuIndicator(config=ichimoku_cfg)
    _state.detector  = SignalDetector(config=detector_cfg)

    # MT5 connection
    broker_raw = config.get("broker", {}).get("mt5", {})
    mt5_cfg = MT5Config(
        login    = broker_raw.get("login", 0)    or 0,
        server   = broker_raw.get("server", "")  or "",
        password = broker_raw.get("password", "") or "",
    )
    _state.fetcher = MT5DataFetcher(mt5_cfg)
    _state.fetcher.connect()

    # Discord notifier
    notif_raw = config.get("notifications", {}).get("discord", {})
    webhook   = notif_raw.get("webhook_url", "")
    _is_dry   = dry_run or config.get("general", {}).get("dry_run", False)

    _state.notifier = DiscordNotifier(
        webhook_url = webhook,
        dry_run     = _is_dry,
    )
    logger.info(f"Notifier ready | dry_run={_is_dry}")

    # Seed buffers
    for pair_entry in config.get("pairs", []):
        symbol = pair_entry["symbol"]
        for tf in pair_entry["timeframes"]:
            logger.info(f"Seeding buffer: {symbol} {tf}")
            buf = CandleBuffer(max_size=300)
            hist = _state.fetcher.fetch_historical(symbol, tf, count=300)
            buf.seed(hist)
            _state.buffers[(symbol, tf)] = buf

    logger.info(
        f"Initialisation complete | "
        f"{len(_state.buffers)} pair/timeframe buffers ready."
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Graceful shutdown
# ─────────────────────────────────────────────────────────────────────────────

def _shutdown(signum, frame):
    logger.info("Shutdown signal received – stopping bot.")
    if _state.fetcher:
        _state.fetcher.disconnect()
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ichimoku Live Bot")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config",  default=str(ROOT / "config.yaml"))
    args = parser.parse_args()

    config = load_config(args.config)

    log_level = config.get("general", {}).get("log_level", "INFO")
    logger.remove()
    logger.add(sys.stderr, level=log_level, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")
    logger.add("logs/bot.log", rotation="1 day", retention="30 days",
               level="DEBUG", compression="zip")

    logger.info("=" * 55)
    logger.info("  Ichimoku Live Bot Starting")
    logger.info("=" * 55)

    initialise(config, dry_run=args.dry_run)

    # ── schedule jobs ─────────────────────────────────────────────────────────
    scheduler = BlockingScheduler(timezone="UTC")

    for pair_entry in config.get("pairs", []):
        symbol = pair_entry["symbol"]
        for tf in pair_entry["timeframes"]:
            cron_kwargs = _TF_CRON.get(tf)
            if cron_kwargs is None:
                logger.warning(f"No cron mapping for timeframe '{tf}' – skipping.")
                continue

            scheduler.add_job(
                process_candle,
                trigger=CronTrigger(timezone="UTC", **cron_kwargs),
                args=[symbol, tf],
                id=f"{symbol}_{tf}",
                name=f"Process {symbol} {tf}",
                misfire_grace_time=60,
            )
            logger.info(f"Scheduled: {symbol} {tf}  cron={cron_kwargs}")

    logger.info(f"Bot running with {len(scheduler.get_jobs())} scheduled jobs.")

    try:
        scheduler.start()
    except Exception as exc:
        logger.exception(f"Scheduler error: {exc}")
    finally:
        if _state.fetcher:
            _state.fetcher.disconnect()


if __name__ == "__main__":
    main()
