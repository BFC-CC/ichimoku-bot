"""
core/notifier.py
─────────────────────────────────────────────────────────────────────────────
Discord webhook notifier.

Formats a Signal as a rich Discord embed and POSTs it to the configured
webhook URL.  Uses a retry wrapper for transient HTTP failures.

Discord embed colours:
    Green  (#00C851)  – BUY signals
    Red    (#FF4444)  – SELL signals

Usage
-----
    from core.notifier import DiscordNotifier
    notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/...")
    notifier.send(signal)
"""

from __future__ import annotations

import json
import time
from typing import Optional

import requests
from loguru import logger

from core.signal_detector import Signal


# ─────────────────────────────────────────────────────────────────────────────
#  Signal type → human-readable label
# ─────────────────────────────────────────────────────────────────────────────

_SIGNAL_LABELS = {
    "tk_cross_up":          "TK Cross ↑",
    "tk_cross_down":        "TK Cross ↓",
    "kumo_breakout_up":     "Kumo Breakout ↑",
    "kumo_breakout_down":   "Kumo Breakout ↓",
    "chikou_cross_up":      "Chikou Cross ↑",
    "chikou_cross_down":    "Chikou Cross ↓",
}

_BUY_COLOR  = 0x00C851   # green
_SELL_COLOR = 0xFF4444   # red


# ─────────────────────────────────────────────────────────────────────────────
#  Notifier
# ─────────────────────────────────────────────────────────────────────────────

class DiscordNotifier:
    """
    Sends Ichimoku signals as Discord embed messages via a webhook.

    Parameters
    ----------
    webhook_url : str
        Discord webhook URL from your server's channel settings.
    dry_run : bool
        If True, log the message instead of sending it.
    max_retries : int
        Number of HTTP retry attempts on failure.
    retry_delay : float
        Initial delay in seconds between retries (doubles each attempt).
    """

    def __init__(
        self,
        webhook_url: str,
        dry_run: bool = False,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        if not webhook_url.startswith("https://discord.com/api/webhooks/"):
            raise ValueError(
                "Invalid Discord webhook URL.  "
                "It should start with 'https://discord.com/api/webhooks/'"
            )
        self.webhook_url = webhook_url
        self.dry_run     = dry_run
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    # ── public API ────────────────────────────────────────────────────────────

    def send(self, signal: Signal) -> bool:
        """
        Format and send a signal to Discord.

        Returns
        -------
        bool – True if sent successfully (or dry_run), False on failure.
        """
        payload = self._build_payload(signal)

        if self.dry_run:
            logger.info(f"[DRY RUN] Discord message:\n{json.dumps(payload, indent=2)}")
            return True

        return self._post_with_retry(payload)

    def send_text(self, message: str) -> bool:
        """Send a plain-text message (e.g. heartbeat, error alert)."""
        payload = {"content": message}
        if self.dry_run:
            logger.info(f"[DRY RUN] Discord text: {message}")
            return True
        return self._post_with_retry(payload)

    # ── message formatting ────────────────────────────────────────────────────

    def _build_payload(self, signal: Signal) -> dict:
        """Build a Discord webhook payload with a rich embed."""
        is_buy  = signal.direction == "BUY"
        color   = _BUY_COLOR if is_buy else _SELL_COLOR
        icon    = "🟢" if is_buy else "🔴"
        label   = _SIGNAL_LABELS.get(signal.signal_type, signal.signal_type.upper())

        # Build detail fields from signal.details dict
        extra_fields = []
        detail_labels = {
            "tenkan":       "Tenkan",
            "kijun":        "Kijun",
            "cloud_top":    "Cloud Top",
            "cloud_bottom": "Cloud Bottom",
            "chikou":       "Chikou",
            "ref_close":    "Ref. Close",
        }
        for key, display in detail_labels.items():
            val = signal.details.get(key)
            if val is not None:
                extra_fields.append({
                    "name": display,
                    "value": f"`{val:.5f}`",
                    "inline": True,
                })

        embed = {
            "title":       f"{icon} {signal.direction} – {label}",
            "color":       color,
            "fields": [
                {"name": "Pair",       "value": f"`{signal.pair}`",      "inline": True},
                {"name": "Timeframe",  "value": f"`{signal.timeframe}`", "inline": True},
                {"name": "Price",      "value": f"`{signal.price:.5f}`", "inline": True},
                *extra_fields,
            ],
            "footer": {
                "text": f"Ichimoku Bot  •  {signal.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
            },
            "timestamp": signal.timestamp.isoformat(),
        }

        return {"embeds": [embed]}

    # ── HTTP posting ──────────────────────────────────────────────────────────

    def _post_with_retry(self, payload: dict) -> bool:
        delay = self.retry_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 204:
                    logger.debug("Discord message sent successfully.")
                    return True

                # 429 = rate limited – honour retry-after header
                if resp.status_code == 429:
                    retry_after = float(resp.json().get("retry_after", delay))
                    logger.warning(
                        f"Discord rate limit hit. Waiting {retry_after:.1f}s "
                        f"(attempt {attempt}/{self.max_retries})"
                    )
                    time.sleep(retry_after)
                    continue

                logger.warning(
                    f"Discord webhook returned {resp.status_code} "
                    f"(attempt {attempt}/{self.max_retries}): {resp.text[:200]}"
                )

            except requests.RequestException as exc:
                logger.warning(
                    f"Discord HTTP error (attempt {attempt}/{self.max_retries}): {exc}"
                )

            if attempt < self.max_retries:
                time.sleep(delay)
                delay *= 2

        logger.error(
            f"Failed to send Discord message after {self.max_retries} attempts."
        )
        return False
