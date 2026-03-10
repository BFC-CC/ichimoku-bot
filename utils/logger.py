"""
utils/logger.py
─────────────────────────────────────────────────────────────────────────────
Configure loguru from JSON config settings.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from core.config_loader import LoggingConfig


def setup_logging(
    config: Optional[LoggingConfig] = None,
    bot_state: Optional[object] = None,
) -> None:
    """Configure loguru with settings from config."""
    cfg = config or LoggingConfig()

    # Remove default handler
    logger.remove()

    # Console handler
    logger.add(
        sys.stderr,
        level=cfg.level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
               "<level>{message}</level>",
    )

    # File handler
    if cfg.log_to_file:
        log_dir = Path(cfg.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_dir / "bot.log"),
            level=cfg.level,
            rotation=f"{cfg.max_file_mb} MB",
            retention="30 days",
            compression="zip",
        )

    # Optional: feed log lines to BotState for dashboard
    if bot_state and hasattr(bot_state, "add_log_line"):
        def _state_sink(message):
            bot_state.add_log_line(str(message).strip())
        logger.add(_state_sink, level=cfg.level, format="{time:HH:mm:ss} | {level} | {message}")

    logger.info(f"Logging configured: level={cfg.level}, file={cfg.log_to_file}")
