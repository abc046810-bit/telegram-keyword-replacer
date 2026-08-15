"""Configuration loaded from environment variables."""

import os
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Required
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID: int = int(os.getenv("OWNER_ID", "0") or "0")

# Database
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./bot.db"
).strip()

# Optional
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
DEFAULT_MATCH_MODE: str = os.getenv("DEFAULT_MATCH_MODE", "contains").lower()

# Validate critical settings early
def validate_config() -> None:
    """Raise ValueError if critical config is missing."""
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN is required. Set it in environment variables or .env file."
        )
    if OWNER_ID == 0:
        raise ValueError(
            "OWNER_ID is required. Set your Telegram numeric user ID "
            "(get it from @userinfobot or by sending /myid to the bot)."
        )
    if DEFAULT_MATCH_MODE not in ("contains", "word"):
        raise ValueError("DEFAULT_MATCH_MODE must be 'contains' or 'word'.")


def setup_logging() -> None:
    """Configure structured logging."""
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=level,
    )
    # Reduce noise from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)