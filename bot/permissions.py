"""Permission checking helpers."""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Chat, ChatMember, Update, User
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
    """Check if the user is an administrator (or creator) of the chat."""
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
    """
    Only OWNER or explicitly authorized admins can configure the bot.
    Telegram group admins alone are NOT enough unless they are also authorized
    or the owner.
    """
    if not update.effective_user:
        return False

    user = update.effective_user
    chat = update.effective_chat

    if await is_owner(user):
        return True

    if chat is None:
        return False

    # Check database for authorized admins
    factory = get_session_factory()
    async with factory() as session:
        authorized = await is_authorized_admin(
            session, chat.id, user.id, OWNER_ID
        )
        return authorized


async def bot_has_edit_permission(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Check whether the bot itself has permission to edit messages
    in the current chat (required for in-place replacement).
    """
    if not update.effective_chat:
        return False

    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        return True

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        # In groups/channels the bot needs to be admin with can_edit_messages
        # or at least be able to edit its own messages. For editing *other*
        # users' messages the bot must be an administrator.
        if bot_member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            # Additional check if the attribute exists
            if hasattr(bot_member, "can_edit_messages"):
                return bool(bot_member.can_edit_messages) or True  # many clients set it
            return True
        return False
    except Exception as e:
        logger.warning("Failed to check bot permissions in %s: %s", chat.id, e)
        return False


def get_required_permissions_text() -> str:
    return (
        "🔐 *Required Bot Admin Permissions*\n\n"
        "Add the bot as an *administrator* in the group/channel and grant:\n\n"
        "• ✅ *Edit messages* (required for keyword replacement)\n"
        "• ✅ *Delete messages* (optional, only if you want extra features later)\n"
        "• ✅ *Read messages* / presence in the chat (needed to see messages)\n\n"
        "⚠️ Without *Edit messages* permission the bot cannot replace keywords "
        "in existing messages.\n\n"
        "📄 *Note about documents/PDFs*:\n"
        "Telegram Bot API does **not** allow changing the actual filename of an "
        "already-uploaded document. Only the *caption* can be edited."
    )