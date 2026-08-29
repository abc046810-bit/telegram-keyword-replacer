"""Handlers – per-admin keywords, rename, broadcast, premium UX."""

from __future__ import annotations

import asyncio
import logging
import os
import unicodedata
from io import BytesIO

from telegram import InputFile, Update
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
    add_admin,
    add_keyword_rule,
    clear_keyword_rules,
    count_bot_users,
    delete_keyword_rule,
    get_active_config_for_user,
    get_session_factory,
    get_settings,
    is_authorized,
    list_admins,
    list_broadcast_users,
    list_keyword_rules,
    mark_user_blocked,
    remove_admin,
    set_case_sensitive,
    set_enabled,
    set_match_mode,
    upsert_bot_user,
)
from bot.keyboards import admin_panel_keyboard, owner_panel_keyboard
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

_chat_locks: dict[int, asyncio.Lock] = {}


def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]


async def _can_configure(update: Update) -> bool:
    if not update.effective_user or not update.message:
        return False
    uid = update.effective_user.id
    factory = get_session_factory()
    async with factory() as session:
        ok = await is_authorized(session, uid, OWNER_ID)
    if not ok:
        await update.message.reply_text(
            "⛔ *Access denied*\n\n"
            "You are not authorized to configure this bot.\n"
            f"Contact the owner: `{OWNER_ID}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return False
    return True


async def _owner_only(update: Update) -> bool:
    if not update.effective_user or not update.message:
        return False
    if not await is_owner(update.effective_user):
        await update.message.reply_text(
            "⛔ *Owner only*\n\nThis command is reserved for the bot owner.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return False
    return True


# ───────────────────────── Start / Help ─────────────────────────

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    factory = get_session_factory()
    async with factory() as session:
        await upsert_bot_user(
            session,
            user.id,
            username=user.username,
            first_name=user.first_name,
        )
        await session.commit()
        authorized = await is_authorized(session, user.id, OWNER_ID)

    if authorized:
        role = "Owner" if user.id == OWNER_ID else "Admin"
        text = (
            f"✨ *Welcome, {role}*\n"
            f"{'─' * 18}\n\n"
            "🔹 Each admin has *private* keyword rules\n"
            "🔹 Rules run only on *your* posts\n"
            "🔹 Captions + PDF filenames supported\n"
            "🔹 Best used in *Channels*\n\n"
            "*Quick commands*\n"
            "• `/addkeyword OLD | NEW`\n"
            "• `/listkeywords` · `/status`\n"
            "• `/enable` · `/disable`\n"
            "• `/help` — full guide\n"
        )
        if user.id == OWNER_ID:
            text += (
                "\n*Owner tools*\n"
                "• `/addadmin ID` · `/removeadmin ID`\n"
                "• `/listadmins` · `/users`\n"
                "• `/broadcast your message`\n"
            )
            kb = owner_panel_keyboard()
        else:
            kb = admin_panel_keyboard()
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb
        )
    else:
        await update.message.reply_text(
            "👋 *Keyword Replacer Bot*\n"
            f"{'─' * 18}\n\n"
            "This bot auto-replaces keywords in channel posts "
            "(text, captions & PDF names).\n\n"
            "⛔ You are *not authorized* to configure it.\n"
            "Please contact the owner for access.\n\n"
            f"👤 Owner ID: `{OWNER_ID}`\n"
            f"🆔 Your ID: `{user.id}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "📖 *Command Guide*\n"
        f"{'─' * 18}\n\n"
        "*Keywords (your rules only)*\n"
        "`/addkeyword OLD | NEW`\n"
        "`/deletekeyword OLD`\n"
        "`/listkeywords`\n"
        "`/clearkeywords`\n\n"
        "*Control*\n"
        "`/enable` · `/disable`\n"
        "`/casesensitive on|off`\n"
        "`/matchmode contains|word`\n"
        "`/status` · `/panel`\n\n"
        "*Info*\n"
        "`/myid` · `/chatid` · `/permissions`\n\n"
        "*Owner only*\n"
        "`/addadmin USER_ID`\n"
        "`/removeadmin USER_ID`\n"
        "`/listadmins` · `/users`\n"
        "`/broadcast message…`\n\n"
        "💡 Configure in *private chat*. "
        "Post as yourself in the channel so your rules apply."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    await update.message.reply_text(
        f"🆔 *Your Telegram ID*\n`{update.effective_user.id}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat = update.effective_chat
    await update.message.reply_text(
        f"💬 *Chat info*\n"
        f"ID: `{chat.id}`\n"
        f"Type: {chat_type_label(chat.type)}\n"
        f"Title: {chat.title or '—'}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def permissions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "🔐 *Channel setup*\n"
        f"{'─' * 18}\n\n"
        "1. Add bot as *Channel admin*\n"
        "2. Allow post + delete messages\n"
        "3. Set keywords in *private chat*\n"
        "4. Post in channel as *yourself*\n\n"
        "📄 PDF *filename* rename = delete + re-upload\n"
        "📝 Caption / text = in-place edit when possible",
        parse_mode=ParseMode.MARKDOWN,
    )


# ───────────────────────── Status / Enable ─────────────────────────

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    uid = update.effective_user.id
    factory = get_session_factory()
    async with factory() as session:
        settings = await get_settings(session)
        rules = await list_keyword_rules(session, uid, only_enabled=False)
        enabled_count = sum(1 for r in rules if r.enabled)
        total_u, active_u = await count_bot_users(session)

    st = "🟢 *ON*" if settings.enabled else "🔴 *OFF*"
    case = "ON" if settings.case_sensitive else "OFF"
    extra = ""
    if uid == OWNER_ID:
        extra = f"\n👥 Bot users: *{active_u}* active / {total_u} total"

    await update.message.reply_text(
        f"📊 *Dashboard*\n"
        f"{'─' * 18}\n\n"
        f"Replacement: {st}\n"
        f"Your rules: *{enabled_count}* active · {len(rules)} total\n"
        f"Case sensitive: `{case}`\n"
        f"Match mode: `{settings.match_mode}`"
        f"{extra}\n\n"
        f"_Your keywords apply only when you post._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def enable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        await set_enabled(session, True)
        await session.commit()
    await update.message.reply_text(
        "🟢 *Replacement enabled*\nBot will process matching posts.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def disable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        await set_enabled(session, False)
        await session.commit()
    await update.message.reply_text(
        "🔴 *Replacement disabled*\nNo automatic edits until re-enabled.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def casesensitive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/casesensitive on` or `off`", parse_mode=ParseMode.MARKDOWN
        )
        return
    value = context.args[0].lower() in ("on", "true", "1")
    factory = get_session_factory()
    async with factory() as session:
        await set_case_sensitive(session, value)
        await session.commit()
    await update.message.reply_text(
        f"✅ Case sensitivity: *{'ON' if value else 'OFF'}*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def matchmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    if not context.args or context.args[0].lower() not in ("contains", "word"):
        await update.message.reply_text(
            "Usage: `/matchmode contains` or `word`", parse_mode=ParseMode.MARKDOWN
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


# ───────────────────────── Keywords ─────────────────────────

async def addkeyword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    parsed = parse_keyword_args(update.message.text or "")
    if not parsed:
        await update.message.reply_text(
            "➕ *Add keyword*\n\n"
            "`/addkeyword OLD | NEW`\n\n"
            "Example:\n`/addkeyword ZX | SK08`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    old, new = parsed
    uid = update.effective_user.id
    factory = get_session_factory()
    async with factory() as session:
        await add_keyword_rule(session, uid, old, new)
        await session.commit()
    await update.message.reply_text(
        f"✅ *Rule saved for you*\n\n{format_rule_line(old, new)}\n\n"
        f"_Only applies when you post._",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info("Rule user=%s %s → %s", uid, old, new)


async def deletekeyword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/deletekeyword OLD`", parse_mode=ParseMode.MARKDOWN
        )
        return
    old = " ".join(context.args).strip()
    uid = update.effective_user.id
    factory = get_session_factory()
    async with factory() as session:
        deleted = await delete_keyword_rule(session, uid, old)
        await session.commit()
    if deleted:
        await update.message.reply_text(
            f"🗑️ Removed: `{old}`", parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"⚠️ Not found in your rules: `{old}`", parse_mode=ParseMode.MARKDOWN
        )


async def listkeywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    uid = update.effective_user.id
    factory = get_session_factory()
    async with factory() as session:
        rules = await list_keyword_rules(session, uid, only_enabled=False)
    if not rules:
        await update.message.reply_text(
            "📭 *No rules yet*\n\nAdd one:\n`/addkeyword OLD | NEW`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    lines = [f"📋 *Your rules* · {len(rules)}\n{'─' * 14}\n"]
    for i, r in enumerate(rules, 1):
        mark = "✅" if r.enabled else "⏸"
        lines.append(f"{i}. {mark}\n{format_rule_line(r.old_keyword, r.new_keyword)}\n")
    body = "\n".join(lines)
    if len(body) > 4000:
        body = body[:3900] + "\n\n… truncated"
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


async def clearkeywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    uid = update.effective_user.id
    factory = get_session_factory()
    async with factory() as session:
        count = await clear_keyword_rules(session, uid)
        await session.commit()
    await update.message.reply_text(
        f"🧹 Cleared *{count}* of your rule(s).", parse_mode=ParseMode.MARKDOWN
    )


async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    kb = (
        owner_panel_keyboard()
        if update.effective_user.id == OWNER_ID
        else admin_panel_keyboard()
    )
    await update.message.reply_text(
        "🎛️ *Control Panel*\nChoose an action:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    factory = get_session_factory()
    async with factory() as session:
        ok = await is_authorized(session, update.effective_user.id, OWNER_ID)
    if not ok:
        await query.edit_message_text("⛔ Not authorized.")
        return
    action = (query.data or "").split(":")[-1]
    hints = {
        "add": "Use:\n`/addkeyword OLD | NEW`",
        "list": "Use `/listkeywords`",
        "status": "Use `/status`",
        "clear": "Use `/clearkeywords`",
        "help": "Use `/help`",
        "admins": "Use `/listadmins`",
        "broadcast": "Use:\n`/broadcast your message here`",
    }
    if action == "enable":
        async with factory() as session:
            await set_enabled(session, True)
            await session.commit()
        await query.edit_message_text("🟢 Enabled.")
    elif action == "disable":
        async with factory() as session:
            await set_enabled(session, False)
            await session.commit()
        await query.edit_message_text("🔴 Disabled.")
    else:
        await query.edit_message_text(
            hints.get(action, "Use the matching command."),
            parse_mode=ParseMode.MARKDOWN,
        )


# ───────────────────────── Admins ─────────────────────────

async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/addadmin USER_ID`\n\nThey must send `/myid` first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        target = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("USER_ID must be a number.")
        return
    if target == OWNER_ID:
        await update.message.reply_text("Owner is already fully authorized.")
        return
    factory = get_session_factory()
    async with factory() as session:
        added = await add_admin(session, target, update.effective_user.id)
        await session.commit()
    if added:
        await update.message.reply_text(
            f"✅ Admin added: `{target}`\nThey can manage *their own* keywords.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            f"⚠️ Already admin: `{target}`", parse_mode=ParseMode.MARKDOWN
        )


async def removeadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/removeadmin USER_ID`", parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        target = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("USER_ID must be a number.")
        return
    factory = get_session_factory()
    async with factory() as session:
        removed = await remove_admin(session, target)
        await session.commit()
    if removed:
        await update.message.reply_text(
            f"✅ Removed admin: `{target}`", parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"⚠️ Not an admin: `{target}`", parse_mode=ParseMode.MARKDOWN
        )


async def listadmins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _can_configure(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        admins = await list_admins(session)
    lines = [f"👑 *Owner*\n`{OWNER_ID}`\n"]
    if admins:
        lines.append("*Admins*")
        for a in admins:
            lines.append(f"• `{a.user_id}`")
    else:
        lines.append("_No extra admins._")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ───────────────────────── Broadcast ─────────────────────────

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    factory = get_session_factory()
    async with factory() as session:
        total, active = await count_bot_users(session)
    await update.message.reply_text(
        f"👥 *Bot users*\n"
        f"{'─' * 14}\n"
        f"Total started: *{total}*\n"
        f"Reachable: *{active}*\n\n"
        f"Broadcast with:\n`/broadcast your message`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    if not context.args:
        await update.message.reply_text(
            "📢 *Broadcast*\n\n"
            "`/broadcast Your message here`\n\n"
            "Sends to everyone who pressed /start.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Support plain text after command; also allow reply-to-message broadcast
    payload = update.message.text or ""
    parts = payload.split(maxsplit=1)
    msg_text = parts[1].strip() if len(parts) > 1 else ""
    if not msg_text and update.message.reply_to_message:
        msg_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    if not msg_text:
        await update.message.reply_text("Empty message. Write text after `/broadcast`.")
        return

    factory = get_session_factory()
    async with factory() as session:
        users = await list_broadcast_users(session)

    if not users:
        await update.message.reply_text("📭 No users to broadcast to yet.")
        return

    status = await update.message.reply_text(
        f"📢 Broadcasting to *{len(users)}* users…", parse_mode=ParseMode.MARKDOWN
    )

    ok = 0
    fail = 0
    for u in users:
        try:
            await context.bot.send_message(
                chat_id=u.user_id,
                text=f"📢 *Announcement*\n{'─' * 14}\n\n{msg_text}",
                parse_mode=ParseMode.MARKDOWN,
            )
            ok += 1
            await asyncio.sleep(0.05)  # gentle rate limit
        except Forbidden:
            fail += 1
            async with factory() as session:
                await mark_user_blocked(session, u.user_id)
                await session.commit()
        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
            try:
                await context.bot.send_message(
                    chat_id=u.user_id,
                    text=f"📢 *Announcement*\n{'─' * 14}\n\n{msg_text}",
                    parse_mode=ParseMode.MARKDOWN,
                )
                ok += 1
            except Exception:
                fail += 1
        except Exception as e:
            fail += 1
            logger.warning("Broadcast fail %s: %s", u.user_id, e)

    await status.edit_text(
        f"✅ *Broadcast complete*\n\n"
        f"Sent: *{ok}*\n"
        f"Failed / blocked: *{fail}*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ───────────────────────── Message processing ─────────────────────────

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        return
    if is_bot_message(message, context.bot.id):
        return

    poster = message.from_user
    if poster is None:
        return

    factory = get_session_factory()
    async with factory() as session:
        authorized = await is_authorized(session, poster.id, OWNER_ID)
        if not authorized:
            return
        enabled, case_sensitive, match_mode, rules = await get_active_config_for_user(
            session, poster.id
        )

    if not enabled or not rules:
        return

    lock = _get_chat_lock(chat.id)
    async with lock:
        await _process_one_message(
            context, message, chat, rules, case_sensitive, match_mode
        )


async def _process_one_message(
    context, message, chat, rules, case_sensitive: bool, match_mode: str
) -> None:
    text, field = extract_text_or_caption(message)
    new_text = text or ""
    text_changed = False
    if text:
        new_text, text_changed = apply_replacements(
            text, rules, case_sensitive=case_sensitive, match_mode=match_mode
        )

    doc = message.document
    if doc and doc.file_name:
        original_name = unicodedata.normalize("NFC", doc.file_name)
        new_filename, name_changed = apply_replacements(
            original_name, rules, case_sensitive=case_sensitive, match_mode=match_mode
        )
        if name_changed:
            new_filename = unicodedata.normalize("NFC", new_filename)
            await _rename_document(
                context,
                chat.id,
                message,
                new_filename,
                new_caption=new_text if (text_changed or text) else (message.caption or None),
            )
            return

    if not text_changed:
        return

    try:
        if field == "text":
            await context.bot.edit_message_text(
                chat_id=chat.id, message_id=message.message_id, text=new_text
            )
        else:
            await context.bot.edit_message_caption(
                chat_id=chat.id, message_id=message.message_id, caption=new_text
            )
        logger.info("Edited %s msg %s in %s", field, message.message_id, chat.id)
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err or "message to edit not found" in err:
            return
        if "message can't be edited" in err or "not enough rights" in err:
            logger.warning("Cannot edit msg %s: %s", message.message_id, e)
            return
        logger.warning("BadRequest: %s", e)
    except RetryAfter as e:
        logger.warning("Flood: retry after %s", e.retry_after)
    except Forbidden as e:
        logger.warning("Forbidden: %s", e)
    except NetworkError as e:
        logger.warning("Network: %s", e)
    except TelegramError as e:
        logger.error("Telegram: %s", e)
    except Exception as e:
        logger.exception("Unexpected: %s", e)


async def _rename_document(
    context, chat_id: int, message, new_filename: str, new_caption: str | None
) -> None:
    doc = message.document
    if not doc:
        return
    new_filename = unicodedata.normalize("NFC", new_filename or "file")
    if new_caption:
        new_caption = unicodedata.normalize("NFC", new_caption)
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        data = await tg_file.download_as_bytearray()
        bio = BytesIO(bytes(data))
        bio.name = new_filename
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(bio, filename=new_filename),
            caption=new_caption if new_caption else None,
        )
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception as del_err:
            logger.warning("Uploaded but delete failed %s: %s", message.message_id, del_err)
        logger.info(
            "Renamed msg %s: %r → %r", message.message_id, doc.file_name, new_filename
        )
    except RetryAfter as e:
        logger.warning("Flood rename: %s", e.retry_after)
    except Forbidden as e:
        logger.warning("Forbidden rename: %s", e)
    except TelegramError as e:
        logger.error("Telegram rename: %s", e)
    except Exception as e:
        logger.exception("Rename failed: %s", e)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.my_chat_member
    if not result:
        return
    logger.info(
        "Membership %s (%s): %s",
        result.chat.id,
        result.chat.title,
        result.new_chat_member.status,
    )
