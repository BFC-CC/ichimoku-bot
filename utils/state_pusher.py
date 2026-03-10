"""
utils/state_pusher.py
─────────────────────────────────────────────────────────────────────────────
Pushes BotState snapshots to the remote dashboard via HTTP POST.

Runs in a background thread, pushing every N seconds.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from typing import Optional

import requests
from loguru import logger

from utils.state import BotState


class StatePusher:
    """Push bot state to a remote dashboard endpoint."""

    def __init__(
        self,
        state: BotState,
        dashboard_url: str,
        secret: str = "",
        interval_sec: float = 3.0,
    ) -> None:
        self.state = state
        self.url = dashboard_url.rstrip("/") + "/api/state"
        self.secret = secret
        self.interval = interval_sec
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start pushing state in a background thread."""
        if not self.url:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"State pusher started -> {self.url}")

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                snap = self.state.snapshot()
                data = asdict(snap)
                headers = {"Content-Type": "application/json"}
                if self.secret:
                    headers["Authorization"] = f"Bearer {self.secret}"

                resp = requests.post(
                    self.url,
                    data=json.dumps(data, default=str),
                    headers=headers,
                    timeout=5,
                )
                if resp.status_code != 200:
                    logger.warning(f"Dashboard push failed: {resp.status_code}")
            except requests.exceptions.ConnectionError:
                pass  # Dashboard not reachable, silently skip
            except Exception as e:
                logger.debug(f"State push error: {e}")

            time.sleep(self.interval)
