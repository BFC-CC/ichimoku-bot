"""
utils/keep_alive.py
---------------------------------------------------------------------
Background daemon thread that pings the dashboard /api/health endpoint
to prevent Render free tier spin-down (15min inactivity timeout).
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import requests
from loguru import logger


class KeepAlive:
    """Periodically GET /api/health to keep the dashboard alive."""

    def __init__(self, url: str, interval_sec: int = 600) -> None:
        self.url = url.rstrip("/")
        self.interval_sec = interval_sec
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the keep-alive daemon thread."""
        if not self.url:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"KeepAlive started: pinging {self.url} every {self.interval_sec}s")

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            ok, detail = self._ping()
            if ok:
                logger.debug(f"KeepAlive ping OK: {detail}")
            else:
                logger.warning(f"KeepAlive ping failed: {detail}")
            self._stop_event.wait(self.interval_sec)

    def _ping(self) -> tuple[bool, str]:
        """GET {url}/api/health with a 10s timeout."""
        try:
            resp = requests.get(f"{self.url}/api/health", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "ok":
                return True, "status=ok"
            return False, f"unexpected: {data}"
        except Exception as e:
            return False, str(e)
