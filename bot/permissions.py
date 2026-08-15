"""Permission checking helpers."""

from __future__ import annotations

import logging
from typing import Optional

from telegram import ChatMember, Update, User
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from bot.config import OWNER_ID
from bot.database import get_session_factory, is_authorized_admin

logger = logging.getLogger(__name__)


async def is_owner(user: Optional[User]) -> bool:
    if user is None:
        return False
    return user.id == OWNER_ID


async def is_chat_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False

    chat = update.effective_chat
    user = update.effective_user

    if chat.type == ChatType.PRIVATE:
        return await is_owner(user)

    try:
        member: ChatMember = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except Exception as e:
        logger.warning("Failed to check admin status for %s in %s: %s", user.id, chat.id, e)
        return False


async def can_configure(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    if not update.effective_user:
        return False

    user = update.effective_user
    chat = update.effective_chat

    if await is_owner(user):
        return True

    if chat is None:
        return False

    factory = get_session_factory()
    async with factory() as session:
        authorized = await is_authorized_admin(
            session, chat.id, user.id, OWNER_ID
        )
        return authorized


def get_required_permissions_text() -> str:
    return (
        "🔐 *Required Bot Permissions (Channel)*\n\n"
        "Add the bot as an *administrator* of the **Channel** and grant:\n\n"
        "• ✅ *Post messages*\n"
        "• ✅ *Edit messages* of others (if available)\n"
        "• ✅ Ability to see channel posts\n\n"
        "⭐ *Recommended usage: Telegram Channel*\n\n"
        "⚠️ In regular *Groups*, Telegram Bot API usually does **not** allow "
        "bots to edit messages sent by other users. That is a Telegram limitation, "
        "not a bug in this bot.\n\n"
        "📄 *Note about documents/PDFs*:\n"
        "Telegram Bot API does **not** allow changing the actual filename of an "
        "already-uploaded document. Only the *caption* can be edited."
    )
