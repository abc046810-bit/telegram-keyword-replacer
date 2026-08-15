"""Permission helpers."""

from __future__ import annotations

from typing import Optional

from telegram import User

from bot.config import OWNER_ID


async def is_owner(user: Optional[User]) -> bool:
    if user is None:
        return False
    return user.id == OWNER_ID
