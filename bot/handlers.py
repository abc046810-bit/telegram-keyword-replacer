"""Telegram command and message handlers."""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
)
from telegram.ext import ContextTypes

from bot.config import OWNER_ID
from bot.database import (
    add_keyword_rule,
    clear_keyword_rules,
    delete_keyword_rule,
    get_enabled_rules_for_chat,
    get_or_create_chat,
    get_session_factory,
    list_keyword_rules,
    set_case_sensitive,
    set_chat_enabled,
    set_match_mode,
)
from bot.keyboards import admin_panel_keyboard
from bot.permissions import (
    bot_has_edit_permission,
    can_configure,
    get_required_permissions_text,
    is_owner,
)
from bot.replacer import apply_replacements
from bot.utils import (
    chat_type_label,
    extract_text_or_caption,
    format_rule_line,
    is_bot_message,
    parse_keyword_args,
    truncate,
)

logger = logging.getLogger(__name__)


# -------------------- Command handlers --------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    chat = update.effective_chat

    if await is_owner(user):
        text = (
            "👋 *Welcome, Owner!*\n\n"
            "This bot automatically replaces configured keywords in messages "
            "inside groups and channels where it is an administrator.\n\n"
            "Use /help to see all commands.\n"
            "Use /panel for a quick admin panel.\n\n"
            f"Your ID: `{user.id}`"
        )
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_panel_keyboard()
        )
    else:
        text = (
            "👋 Hello!\n\n"
            "I am a *Keyword Replacer* bot.\n"
            "Only the bot owner and authorized admins can configure me.\n\n"
            "Use /myid to see your Telegram user ID.\n"
            "Use /help for available commands."
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    help_text = (
        "📖 *Keyword Replacer Bot – Help*\n\n"
        "*Configuration commands* (owner / authorized only):\n"
        "`/addkeyword OLD | NEW` – Add or update a replacement rule\n"
        "`/deletekeyword OLD` – Remove a rule\n"
        "`/listkeywords` – Show all rules for this chat\n"
        "`/clearkeywords` – Delete all rules in this chat\n"
        "`/enable` – Enable automatic replacement\n"
        "`/disable` – Disable automatic replacement\n"
        "`/casesensitive on|off` – Toggle case sensitivity\n"
        "`/matchmode contains|word` – Matching mode\n"
        "`/status` – Show current settings\n"
        "`/panel` – Open admin panel\n\n"
        "*Utility commands*:\n"
        "`/myid` – Show your Telegram user ID\n"
        "`/chatid` – Show current chat ID\n"
        "`/permissions` – Required bot admin permissions\n"
        "`/help` – This message\n\n"
        "*Example*\n"
        "`/addkeyword OLDNAME | @NewChannel`\n\n"
        "After adding a rule the bot will automatically edit matching "
        "messages and captions in this chat."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    await update.message.reply_text(
        f"🆔 Your Telegram user ID:\n`{update.effective_user.id}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat = update.effective_chat
    await update.message.reply_text(
        f"💬 Chat ID: `{chat.id}`\n"
        f"Type: {chat_type_label(chat.type)}\n"
        f"Title: {chat.title or 'N/A'}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def permissions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        get_required_permissions_text(), parse_mode=ParseMode.MARKDOWN
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return

    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        db_chat = await get_or_create_chat(session, chat.id, chat.title)
        rules = await list_keyword_rules(session, chat.id, only_enabled=False)
        enabled_count = sum(1 for r in rules if r.enabled)

        status = "🟢 ON" if db_chat.enabled else "🔴 OFF"
        case = "ON" if db_chat.case_sensitive else "OFF"

        text = (
            f"📊 *Status*\n\n"
            f"Bot status: {status}\n"
            f"Chat: {db_chat.chat_title or chat.title or chat.id}\n"
            f"Chat ID: `{chat.id}`\n"
            f"Rules: {enabled_count} active / {len(rules)} total\n"
            f"Case sensitive: {case}\n"
            f"Match mode: `{db_chat.match_mode}`\n"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def enable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return
    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        await set_chat_enabled(session, chat.id, True)
        await session.commit()
    await update.message.reply_text("✅ Keyword replacement *enabled* for this chat.", parse_mode=ParseMode.MARKDOWN)


async def disable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return
    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        await set_chat_enabled(session, chat.id, False)
        await session.commit()
    await update.message.reply_text("🔴 Keyword replacement *disabled* for this chat.", parse_mode=ParseMode.MARKDOWN)


async def casesensitive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/casesensitive on` or `/casesensitive off`", parse_mode=ParseMode.MARKDOWN)
        return

    arg = context.args[0].lower()
    if arg not in ("on", "off", "true", "false", "1", "0"):
        await update.message.reply_text("Please use `on` or `off`.", parse_mode=ParseMode.MARKDOWN)
        return

    value = arg in ("on", "true", "1")
    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        await set_case_sensitive(session, chat.id, value)
        await session.commit()

    state = "ON (case-sensitive)" if value else "OFF (case-insensitive)"
    await update.message.reply_text(f"✅ Case sensitivity set to *{state}*.", parse_mode=ParseMode.MARKDOWN)


async def matchmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/matchmode contains` or `/matchmode word`\n\n"
            "• `contains` – substring match (default)\n"
            "• `word` – whole-word match",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    mode = context.args[0].lower()
    if mode not in ("contains", "word"):
        await update.message.reply_text("Mode must be `contains` or `word`.", parse_mode=ParseMode.MARKDOWN)
        return

    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        await set_match_mode(session, chat.id, mode)
        await session.commit()

    await update.message.reply_text(f"✅ Match mode set to `{mode}`.", parse_mode=ParseMode.MARKDOWN)


async def addkeyword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return

    parsed = parse_keyword_args(update.message.text or "")
    if not parsed:
        await update.message.reply_text(
            "Usage:\n`/addkeyword OLDKEYWORD | NEWKEYWORD`\n\n"
            "Example:\n`/addkeyword OLDNAME | @NewChannel`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    old, new = parsed
    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        await get_or_create_chat(session, chat.id, chat.title)
        rule = await add_keyword_rule(session, chat.id, old, new)
        await session.commit()

    await update.message.reply_text(
        f"✅ Keyword added successfully.\n\n{format_rule_line(old, new)}",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info("Rule added in chat %s: %s → %s", chat.id, old, new)


async def deletekeyword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/deletekeyword OLDKEYWORD`", parse_mode=ParseMode.MARKDOWN
        )
        return

    old = " ".join(context.args).strip()
    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        deleted = await delete_keyword_rule(session, chat.id, old)
        await session.commit()

    if deleted:
        await update.message.reply_text(f"✅ Keyword removed: `{old}`", parse_mode=ParseMode.MARKDOWN)
        logger.info("Rule deleted in chat %s: %s", chat.id, old)
    else:
        await update.message.reply_text(f"⚠️ No rule found for `{old}`.", parse_mode=ParseMode.MARKDOWN)


async def listkeywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return

    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        rules = await list_keyword_rules(session, chat.id, only_enabled=False)

    if not rules:
        await update.message.reply_text("📭 No keyword rules configured for this chat.")
        return

    lines = [f"📋 *Keyword rules* ({len(rules)}):\n"]
    for i, r in enumerate(rules, 1):
        status = "✅" if r.enabled else "⏸"
        lines.append(f"{i}. {status}\n{format_rule_line(r.old_keyword, r.new_keyword)}\n")

    text = "\n".join(lines)
    # Telegram message length limit
    if len(text) > 4000:
        text = text[:3900] + "\n\n… (truncated)"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def clearkeywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return

    chat = update.effective_chat
    factory = get_session_factory()
    async with factory() as session:
        count = await clear_keyword_rules(session, chat.id)
        await session.commit()

    await update.message.reply_text(f"🧹 Cleared {count} keyword rule(s).")
    logger.info("Cleared %s rules in chat %s", count, chat.id)


async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_config(update, context):
        return
    await update.message.reply_text(
        "⚙️ *Admin Panel*\nChoose an action:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_panel_keyboard(),
    )


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if not await can_configure(update, context):
        await query.edit_message_text("⛔ You are not authorized to configure this bot.")
        return

    data = query.data or ""
    action = data.split(":", 1)[-1] if ":" in data else ""

    if action == "status":
        # Re-use status logic by faking a message reply
        await query.edit_message_text("Use /status command for full status.")
    elif action == "list":
        await query.edit_message_text("Use /listkeywords to see all rules.")
    elif action == "enable":
        chat = update.effective_chat
        factory = get_session_factory()
        async with factory() as session:
            await set_chat_enabled(session, chat.id, True)
            await session.commit()
        await query.edit_message_text("✅ Enabled.")
    elif action == "disable":
        chat = update.effective_chat
        factory = get_session_factory()
        async with factory() as session:
            await set_chat_enabled(session, chat.id, False)
            await session.commit()
        await query.edit_message_text("🔴 Disabled.")
    elif action == "help":
        await query.edit_message_text("Send /help for the full command list.")
    elif action == "cancel":
        await query.edit_message_text("Cancelled.")
    else:
        await query.edit_message_text(
            f"Action `{action}` – please use the corresponding command "
            "(`/addkeyword`, `/deletekeyword`, etc.) for full control.",
            parse_mode=ParseMode.MARKDOWN,
        )


# -------------------- Message processing --------------------

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Core automatic replacement logic.
    Handles both new messages and edited messages.
    """
    message = update.effective_message
    if message is None:
        return

    # Ignore private chats for automatic processing (optional – can be enabled later)
    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        return

    # Ignore bot's own messages
    if is_bot_message(message, context.bot.id):
        return

    text, field = extract_text_or_caption(message)
    if text is None or text == "":
        return

    factory = get_session_factory()
    async with factory() as session:
        enabled, case_sensitive, match_mode, rules = await get_enabled_rules_for_chat(
            session, chat.id
        )

    if not enabled or not rules:
        return

    new_text, changed = apply_replacements(
        text, rules, case_sensitive=case_sensitive, match_mode=match_mode
    )

    if not changed:
        return

    # Perform the edit
    try:
        if field == "text":
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=message.message_id,
                text=new_text,
                # Keep original entities if possible – simple version keeps plain text
                # For full entity preservation a more complex solution is needed.
            )
        else:  # caption
            await context.bot.edit_message_caption(
                chat_id=chat.id,
                message_id=message.message_id,
                caption=new_text,
            )
        logger.debug(
            "Edited message %s in chat %s (%s → changed)",
            message.message_id,
            chat.id,
            field,
        )
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err or "message to edit not found" in err:
            # Harmless – already correct or gone
            return
        if "message can't be edited" in err or "not enough rights" in err:
            logger.warning(
                "Cannot edit message %s in chat %s: %s", message.message_id, chat.id, e
            )
            return
        logger.warning("BadRequest while editing: %s", e)
    except RetryAfter as e:
        logger.warning("Flood control: retry after %s seconds", e.retry_after)
        # python-telegram-bot will handle retry if configured; we just log
    except Forbidden as e:
        logger.warning("Forbidden while editing in chat %s: %s", chat.id, e)
    except NetworkError as e:
        logger.warning("Network error while editing: %s", e)
    except TelegramError as e:
        logger.error("Telegram error while editing: %s", e)
    except Exception as e:
        logger.exception("Unexpected error while processing message: %s", e)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log when the bot is added/removed or its permissions change."""
    result = update.my_chat_member
    if not result:
        return

    chat = result.chat
    new_status = result.new_chat_member.status
    logger.info(
        "Bot membership changed in chat %s (%s): new status = %s",
        chat.id,
        chat.title,
        new_status,
    )


# -------------------- Internal helpers --------------------

async def _guard_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the user is allowed to configure; otherwise reply and return False."""
    if not update.message:
        return False
    if not await can_configure(update, context):
        await update.message.reply_text(
            "⛔ Only the bot owner or authorized admins can change settings."
        )
        return False
    return True