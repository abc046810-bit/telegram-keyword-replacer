"""Environment config."""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID: int = int(os.getenv("OWNER_ID", "0") or "0")
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db").strip()
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


def validate_config() -> None:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is required.")
    if OWNER_ID == 0:
        raise ValueError("OWNER_ID is required (numeric Telegram ID).")


def setup_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=level,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
