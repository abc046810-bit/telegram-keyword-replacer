"""Helpers."""

from __future__ import annotations

from typing import Optional, Tuple

from telegram import Message
from telegram.constants import ChatType


def extract_text_or_caption(message: Optional[Message]) -> Tuple[Optional[str], str]:
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


def format_rule_line(old: str, new: str) -> str:
    return f"🔴 `{old}`\n🟢 `{new}`"


def chat_type_label(chat_type: str) -> str:
    mapping = {
        ChatType.PRIVATE: "Private",
        ChatType.GROUP: "Group",
        ChatType.SUPERGROUP: "Supergroup",
        ChatType.CHANNEL: "Channel",
    }
    return mapping.get(chat_type, chat_type)
