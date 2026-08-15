"""Telegram command and message handlers.

Configuration is GLOBAL and done in PRIVATE chat with the bot.
Rules apply to every Channel/Group where the bot is admin.
"""

from __future__ import annotations

import logging

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
    get_active_config,
    get_session_factory,
    get_settings,
    list_keyword_rules,
    set_case_sensitive,
    set_enabled,
    set_match_mode,
)
from bot.keyboards import admin_panel_keyboard
from bot.permissions import is_owner
from bot.replacer import apply_replacements
from bot.utils import (
    chat_type_label,
    extract_text_or_caption,
    format_rule_line,
    is_bot_message,
    parse_keyword_args,
)

logger = logging.getLogger(__name__)


def _is_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)


async def _owner_only(update: Update) -> bool:
    """Only owner can configure. Prefer private chat."""
    if not update.effective_user or not update.message:
        return False
    if not await is_owner(update.effective_user):
        await update.message.reply_text("⛔ Only the bot owner can use this command.")
        return False
    return True


# -------------------- Commands (work best in private chat) --------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    if await is_owner(user):
        text = (
            "👋 *Welcome, Owner!*\n\n"
            "Keywords are *GLOBAL* — add once, applies everywhere the bot is admin.\n\n"
            "⭐ Configure here in *private chat* (recommended).\n"
            "Then add the bot as admin to your Channels.\n\n"
            "Commands:\n"
            "`/addkeyword OLD | NEW`\n"
            "`/listkeywords`  `/enable`  `/disable`  `/status`\n"
            "`/help` for full list."
        )
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_panel_keyboard()
        )
    else:
        await update.message.reply_text(
            "👋 Hello! I am a Keyword Replacer bot.\n"
            "Only the owner can configure me.\n"
            f"Your ID: `{user.id}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "📖 *Keyword Replacer – Help*\n\n"
        "*Rules are GLOBAL*\n"
        "Add keywords once (in private chat). They apply to all channels/groups "
        "where the bot is admin until you change them.\n\n"
        "*Owner commands* (use in private chat with bot):\n"
        "`/addkeyword OLD | NEW` – Add/update rule\n"
        "`/deletekeyword OLD` – Remove rule\n"
        "`/listkeywords` – List all rules\n"
        "`/clearkeywords` – Delete all rules\n"
        "`/enable` – Turn replacement ON\n"
        "`/disable` – Turn replacement OFF\n"
        "`/casesensitive on|off`\n"
        "`/matchmode contains|word`\n"
        "`/status` – Show global status\n\n"
        "*How to use*\n"
        "1. Talk to the bot in private → add keywords → `/enable`\n"
        "2. Add bot as *admin* to your Channel\n"
        "3. Post in the channel — keywords are auto-replaced\n\n"
        "⚠️ Groups: Telegram often blocks bots from editing others' messages.\n"
        "✅ Channels: supported."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    await update.message.reply_text(
        f"🆔 Your ID: `{update.effective_user.id}`\nOwner ID must match this.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat = update.effective_chat
    await update.message.reply_text(
        f"Chat ID: `{chat.id}`\nType: {chat_type_label(chat.type)}\nTitle: {chat.title or 'N/A'}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def permissions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "🔐 *Channel setup*\n\n"
        "1. Add bot as Channel *administrator*\n"
        "2. Allow: Post messages / Edit messages (if shown)\n"
        "3. Configure keywords in *private chat* with the bot\n"
        "4. Post in channel — bot edits matching text/captions\n\n"
        "📄 PDF filenames cannot be changed (Telegram limit). Only captions."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        settings = await get_settings(session)
        rules = await list_keyword_rules(session, only_enabled=False)
        enabled_count = sum(1 for r in rules if r.enabled)

    status = "🟢 ON" if settings.enabled else "🔴 OFF"
    case = "ON" if settings.case_sensitive else "OFF"
    text = (
        f"📊 *Global Status*\n\n"
        f"Replacement: {status}\n"
        f"Rules: {enabled_count} active / {len(rules)} total\n"
        f"Case sensitive: {case}\n"
        f"Match mode: `{settings.match_mode}`\n\n"
        f"_Rules apply to all chats where bot is admin._"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def enable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        await set_enabled(session, True)
        await session.commit()
    await update.message.reply_text(
        "✅ Keyword replacement *enabled globally*.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def disable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        await set_enabled(session, False)
        await session.commit()
    await update.message.reply_text(
        "🔴 Keyword replacement *disabled globally*.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def casesensitive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/casesensitive on` or `/casesensitive off`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    arg = context.args[0].lower()
    value = arg in ("on", "true", "1")
    factory = get_session_factory()
    async with factory() as session:
        await set_case_sensitive(session, value)
        await session.commit()
    state = "ON" if value else "OFF"
    await update.message.reply_text(
        f"✅ Case sensitivity: *{state}*", parse_mode=ParseMode.MARKDOWN
    )


async def matchmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    if not context.args or context.args[0].lower() not in ("contains", "word"):
        await update.message.reply_text(
            "Usage: `/matchmode contains` or `/matchmode word`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    mode = context.args[0].lower()
    factory = get_session_factory()
    async with factory() as session:
        await set_match_mode(session, mode)
        await session.commit()
    await update.message.reply_text(
        f"✅ Match mode: `{mode}`", parse_mode=ParseMode.MARKDOWN
    )


async def addkeyword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    parsed = parse_keyword_args(update.message.text or "")
    if not parsed:
        await update.message.reply_text(
            "Usage:\n`/addkeyword OLD | NEW`\n\nExample:\n`/addkeyword OLDNAME | @NewChannel`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    old, new = parsed
    factory = get_session_factory()
    async with factory() as session:
        await add_keyword_rule(session, old, new)
        await session.commit()
    await update.message.reply_text(
        f"✅ Global rule added.\n\n{format_rule_line(old, new)}\n\n"
        f"_Applies to all channels where bot is admin._",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info("Global rule added: %s → %s", old, new)


async def deletekeyword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/deletekeyword OLDKEYWORD`", parse_mode=ParseMode.MARKDOWN
        )
        return
    old = " ".join(context.args).strip()
    factory = get_session_factory()
    async with factory() as session:
        deleted = await delete_keyword_rule(session, old)
        await session.commit()
    if deleted:
        await update.message.reply_text(
            f"✅ Removed global rule: `{old}`", parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"⚠️ No rule found for `{old}`.", parse_mode=ParseMode.MARKDOWN
        )


async def listkeywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        rules = await list_keyword_rules(session, only_enabled=False)
    if not rules:
        await update.message.reply_text("📭 No global keyword rules yet.")
        return
    lines = [f"📋 *Global keyword rules* ({len(rules)}):\n"]
    for i, r in enumerate(rules, 1):
        status = "✅" if r.enabled else "⏸"
        lines.append(f"{i}. {status}\n{format_rule_line(r.old_keyword, r.new_keyword)}\n")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n\n… (truncated)"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def clearkeywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        count = await clear_keyword_rules(session)
        await session.commit()
    await update.message.reply_text(f"🧹 Cleared {count} global rule(s).")


async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    await update.message.reply_text(
        "⚙️ *Admin Panel* (global settings)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_panel_keyboard(),
    )


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    if not update.effective_user or not await is_owner(update.effective_user):
        await query.edit_message_text("⛔ Owner only.")
        return
    action = (query.data or "").split(":")[-1]
    if action == "enable":
        factory = get_session_factory()
        async with factory() as session:
            await set_enabled(session, True)
            await session.commit()
        await query.edit_message_text("✅ Enabled globally.")
    elif action == "disable":
        factory = get_session_factory()
        async with factory() as session:
            await set_enabled(session, False)
            await session.commit()
        await query.edit_message_text("🔴 Disabled globally.")
    elif action == "list":
        await query.edit_message_text("Send /listkeywords")
    elif action == "status":
        await query.edit_message_text("Send /status")
    elif action == "help":
        await query.edit_message_text("Send /help")
    else:
        await query.edit_message_text("Use the text commands for full control.")


# -------------------- Auto processing (channels + groups) --------------------

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        return

    if is_bot_message(message, context.bot.id):
        return

    text, field = extract_text_or_caption(message)
    if not text:
        return

    factory = get_session_factory()
    async with factory() as session:
        enabled, case_sensitive, match_mode, rules = await get_active_config(session)

    if not enabled or not rules:
        return

    new_text, changed = apply_replacements(
        text, rules, case_sensitive=case_sensitive, match_mode=match_mode
    )
    if not changed:
        return

    try:
        if field == "text":
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=message.message_id,
                text=new_text,
            )
        else:
            await context.bot.edit_message_caption(
                chat_id=chat.id,
                message_id=message.message_id,
                caption=new_text,
            )
        logger.info(
            "Edited %s msg %s in %s (%s)",
            field,
            message.message_id,
            chat.id,
            chat.type,
        )
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err or "message to edit not found" in err:
            return
        if "message can't be edited" in err or "not enough rights" in err:
            logger.warning(
                "Cannot edit msg %s in %s (%s): %s",
                message.message_id,
                chat.id,
                chat.type,
                e,
            )
            return
        logger.warning("BadRequest: %s", e)
    except RetryAfter as e:
        logger.warning("Flood control: retry after %s s", e.retry_after)
    except Forbidden as e:
        logger.warning("Forbidden in %s: %s", chat.id, e)
    except NetworkError as e:
        logger.warning("Network error: %s", e)
    except TelegramError as e:
        logger.error("Telegram error: %s", e)
    except Exception as e:
        logger.exception("Unexpected error: %s", e)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    logger.info(
        "Bot membership changed in %s (%s): %s",
        chat.id,
        chat.title,
        result.new_chat_member.status,
    )
