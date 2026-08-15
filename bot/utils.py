"""Utility helpers."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from telegram import Message, Update
from telegram.constants import ChatType

logger = logging.getLogger(__name__)


def extract_text_or_caption(message: Optional[Message]) -> Tuple[Optional[str], str]:
    """
    Returns (text_or_caption, field_type)
    field_type is "text" or "caption"
    """
    if message is None:
        return None, "text"
    if message.text is not None:
        return message.text, "text"
    if message.caption is not None:
        return message.caption, "caption"
    return None, "text"


def is_bot_message(message: Optional[Message], bot_id: int) -> bool:
    if message is None or message.from_user is None:
        return False
    return message.from_user.id == bot_id


def parse_keyword_args(text: str) -> Optional[Tuple[str, str]]:
    """
    Parse "/addkeyword OLD | NEW" style arguments.
    Supports spaces in the replacement text.
    Separator is the first occurrence of " | " (space-pipe-space) or "|".
    """
    if not text:
        return None

    # Remove the command part
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    args = parts[1].strip()

    # Prefer " | " then fall back to "|"
    if " | " in args:
        old, new = args.split(" | ", 1)
    elif "|" in args:
        old, new = args.split("|", 1)
    else:
        return None

    old = old.strip()
    new = new.strip()
    if not old:
        return None
    # new can be empty (delete the keyword by replacing with nothing)
    return old, new


def format_rule_line(old: str, new: str) -> str:
    return f"🔴 `{old}`\n🟢 `{new}`"


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def chat_type_label(chat_type: str) -> str:
    mapping = {
        ChatType.PRIVATE: "Private",
        ChatType.GROUP: "Group",
        ChatType.SUPERGROUP: "Supergroup",
        ChatType.CHANNEL: "Channel",
    }
    return mapping.get(chat_type, chat_type)