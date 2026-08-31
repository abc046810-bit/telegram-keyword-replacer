"""SK Keywords Replacer — premium UI handlers."""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from io import BytesIO
from typing import Any, Dict, List, Optional

from telegram import InputFile, Update
from telegram.constants import ChatType, ChatMemberStatus, ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from bot.branding import (
    BOT_NAME,
    TAGLINE,
    FORCE_CHANNEL,
    OWNER_USERNAME,
    DEVELOPER_USERNAME,
    DEFAULT_CREDIT,
    SUPPORT_TEXT,
)
from bot.config import OWNER_ID
from bot.database import (
    add_admin,
    add_keyword_pairs,
    clear_keyword_rules,
    count_bot_users,
    delete_keyword_rule,
    get_rules_for_processing,
    get_session_factory,
    get_settings,
    is_authorized,
    list_admins,
    list_broadcast_users,
    list_keyword_rules,
    mark_user_blocked,
    remove_admin,
    scope_for_user,
    set_batch_name,
    set_case_sensitive,
    set_credit_name,
    set_custom_template,
    set_enabled,
    set_match_mode,
    set_rule_scope,
    upsert_bot_user,
)
from bot.keyboards import (
    back_menu_keyboard,
    bulk_keyboard,
    force_join_keyboard,
    links_keyboard,
    main_menu_keyboard,
    settings_keyboard,
)
from bot.permissions import is_owner
from bot.replacer import apply_replacements, parse_multi_keywords
from bot.utils import extract_text_or_caption, format_rule_line, is_bot_message

logger = logging.getLogger(__name__)

# Conversation states
WAIT_KEYWORDS = 1
WAIT_BATCH = 2
WAIT_CREDIT = 3
WAIT_TEMPLATE = 4
WAIT_BROADCAST = 5
WAIT_ADD_ADMIN = 6
WAIT_DEL_ADMIN = 7
WAIT_DEL_KEYWORD = 8

_chat_locks: Dict[int, asyncio.Lock] = {}


def _lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]


async def _auth(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    factory = get_session_factory()
    async with factory() as session:
        return await is_authorized(session, user.id, OWNER_ID)


async def _check_force_join(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Return True if user is member of FORCE_CHANNEL (or check fails open for owner)."""
    if user_id == OWNER_ID:
        return True
    ch = FORCE_CHANNEL
    try:
        member = await context.bot.get_chat_member(chat_id=ch, user_id=user_id)
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.RESTRICTED,
        )
    except Exception as e:
        # Channel ownership mismatch / private channel — don't block forever
        logger.warning("Force-join check failed for %s: %s", ch, e)
        return True


def _welcome_text(role: str) -> str:
    return (
        f"✨ *{BOT_NAME}*\n"
        f"_{TAGLINE}_\n"
        f"{'─' * 18}\n\n"
        f"Welcome, *{role}*!\n\n"
        f"*Modes*\n"
        f"🌐 *Global* — one keyword list for everyone\n"
        f"👤 *My Keywords* — your list, only on your posts\n"
        f"📦 *Bulk* — send many files, then Done → ordered re-upload\n\n"
        f"*Live replace* runs on channel/group posts automatically.\n"
        f"Use buttons below — no need to remember commands.\n\n"
        f"{SUPPORT_TEXT}"
    )


# ─── Start ──────────────────────────────────────────────────

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or not update.message:
        return ConversationHandler.END
    user = update.effective_user
    factory = get_session_factory()
    async with factory() as session:
        await upsert_bot_user(
            session, user.id, username=user.username, first_name=user.first_name
        )
        await session.commit()
        authorized = await is_authorized(session, user.id, OWNER_ID)

    if not authorized:
        await update.message.reply_text(
            f"👋 *{BOT_NAME}*\n_{TAGLINE}_\n\n"
            f"⛔ You are *not authorized*.\n"
            f"Contact the owner for access.\n\n"
            f"👑 Owner: `{OWNER_USERNAME}`\n"
            f"🛠 Dev: `{DEVELOPER_USERNAME}`\n"
            f"🆔 Your ID: `{user.id}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=links_keyboard(),
        )
        return ConversationHandler.END

    if not await _check_force_join(context, user.id):
        await update.message.reply_text(
            f"🔒 *Join required*\n\n"
            f"Please join `{FORCE_CHANNEL}` to use *{BOT_NAME}*.\n"
            f"Then tap *I Joined*.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=force_join_keyboard(),
        )
        return ConversationHandler.END

    role = "Owner" if user.id == OWNER_ID else "Admin"
    await update.message.reply_text(
        _welcome_text(role),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(user.id == OWNER_ID),
    )
    return ConversationHandler.END


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await start_cmd(update, context)


# ─── Callback router ────────────────────────────────────────

async def sk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END
    await query.answer()
    data = query.data or ""
    uid = update.effective_user.id
    action = data.split(":", 1)[-1] if data.startswith("sk:") else data

    if action == "check_join":
        if await _check_force_join(context, uid):
            role = "Owner" if uid == OWNER_ID else "Admin"
            if not await _auth(update):
                await query.edit_message_text("⛔ Not authorized.")
                return ConversationHandler.END
            await query.edit_message_text(
                _welcome_text(role),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(uid == OWNER_ID),
            )
        else:
            await query.edit_message_text(
                f"Still not joined `{FORCE_CHANNEL}`.\nJoin then tap again.",
                reply_markup=force_join_keyboard(),
            )
        return ConversationHandler.END

    if not await _auth(update):
        await query.edit_message_text("⛔ Not authorized.")
        return ConversationHandler.END

    factory = get_session_factory()

    if action == "menu":
        role = "Owner" if uid == OWNER_ID else "Admin"
        await query.edit_message_text(
            _welcome_text(role),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(uid == OWNER_ID),
        )
        return ConversationHandler.END

    if action == "links":
        await query.edit_message_text(
            f"🔗 *Links*\n\n"
            f"📢 Channel: `{FORCE_CHANNEL}`\n"
            f"👑 Owner: `{OWNER_USERNAME}`\n"
            f"🛠 Developer: `{DEVELOPER_USERNAME}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=Inline_back_links(),
        )
        return ConversationHandler.END

    if action == "help":
        await query.edit_message_text(
            f"❓ *Help — {BOT_NAME}*\n\n"
            f"*Add keywords (many at once):*\n"
            f"`Mk&Sk,xyz&SK,1&2`\n"
            f"Means: Mk→Sk, xyz→SK, 1→2\n\n"
            f"*Modes*\n"
            f"• Global = shared list for all posts\n"
            f"• My Keywords = only your posts\n"
            f"• Bulk = send files here, then Done\n\n"
            f"Live channel posts: keywords auto-replaced.\n"
            f"PDF order is preserved (first in → first out).\n\n"
            f"*Custom template placeholders:*\n"
            f"`{{title}}` `{{batch}}` `{{credit}}` `{{n}}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_menu_keyboard(),
        )
        return ConversationHandler.END

    if action == "mode_global":
        async with factory() as session:
            await set_rule_scope(session, "global")
            await session.commit()
        await query.edit_message_text(
            "🌐 *Global Mode ON*\n\n"
            "One keyword list for everyone.\n"
            "All posts use the same rules.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_menu_keyboard(),
        )
        return ConversationHandler.END

    if action == "mode_personal":
        async with factory() as session:
            await set_rule_scope(session, "per_admin")
            await session.commit()
        await query.edit_message_text(
            "👤 *My Keywords Mode ON*\n\n"
            "Each admin has a private list.\n"
            "Rules run only on *your* posts.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_menu_keyboard(),
        )
        return ConversationHandler.END

    if action == "enable":
        async with factory() as session:
            await set_enabled(session, True)
            await session.commit()
        await query.edit_message_text("🟢 Replacement *enabled*.", parse_mode=ParseMode.MARKDOWN, reply_markup=back_menu_keyboard())
        return ConversationHandler.END

    if action == "disable":
        async with factory() as session:
            await set_enabled(session, False)
            await session.commit()
        await query.edit_message_text("🔴 Replacement *disabled*.", parse_mode=ParseMode.MARKDOWN, reply_markup=back_menu_keyboard())
        return ConversationHandler.END

    if action == "status":
        async with factory() as session:
            s = await get_settings(session)
            key = scope_for_user(s.rule_scope, uid)
            rules = await list_keyword_rules(session, key)
            total_u, active_u = await count_bot_users(session)
        scope_label = "Global" if s.rule_scope == "global" else "Per-admin"
        st = "ON" if s.enabled else "OFF"
        extra = f"\n👥 Users: {active_u}/{total_u}" if uid == OWNER_ID else ""
        await query.edit_message_text(
            f"📊 *Status*\n\n"
            f"Live replace: *{st}*\n"
            f"Mode: *{scope_label}*\n"
            f"Your/active rules: *{len(rules)}*\n"
            f"Case: `{'ON' if s.case_sensitive else 'OFF'}`\n"
            f"Match: `{s.match_mode}`\n"
            f"Batch: `{s.batch_name}`\n"
            f"Credit: `{s.credit_name}`{extra}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_menu_keyboard(),
        )
        return ConversationHandler.END

    if action == "list_kw":
        async with factory() as session:
            s = await get_settings(session)
            key = scope_for_user(s.rule_scope, uid)
            rules = await list_keyword_rules(session, key)
        if not rules:
            await query.edit_message_text(
                "📭 No keywords yet.\nTap *Add Keywords*.",
                reply_markup=back_menu_keyboard(),
            )
            return ConversationHandler.END
        lines = [f"📋 *Keywords* ({len(rules)})\n"]
        for i, r in enumerate(rules, 1):
            lines.append(f"{i}. {format_rule_line(r.old_keyword, r.new_keyword)}\n")
        body = "\n".join(lines)
        if len(body) > 3500:
            body = body[:3500] + "\n…"
        await query.edit_message_text(
            body, parse_mode=ParseMode.MARKDOWN, reply_markup=back_menu_keyboard()
        )
        return ConversationHandler.END

    if action == "settings":
        await query.edit_message_text(
            "⚙️ *Settings*\nChoose what to change:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_keyboard(),
        )
        return ConversationHandler.END

    if action == "toggle_case":
        async with factory() as session:
            s = await get_settings(session)
            await set_case_sensitive(session, not s.case_sensitive)
            await session.commit()
            s2 = await get_settings(session)
        await query.edit_message_text(
            f"Case sensitive: *{'ON' if s2.case_sensitive else 'OFF'}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_keyboard(),
        )
        return ConversationHandler.END

    if action == "toggle_match":
        async with factory() as session:
            s = await get_settings(session)
            new = "word" if s.match_mode == "contains" else "contains"
            await set_match_mode(session, new)
            await session.commit()
        await query.edit_message_text(
            f"Match mode: `{new}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_keyboard(),
        )
        return ConversationHandler.END

    if action == "clear_kw":
        async with factory() as session:
            s = await get_settings(session)
            key = scope_for_user(s.rule_scope, uid)
            n = await clear_keyword_rules(session, key)
            await session.commit()
        await query.edit_message_text(
            f"🧹 Cleared *{n}* rule(s).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_menu_keyboard(),
        )
        return ConversationHandler.END

    if action == "bulk":
        context.user_data["bulk"] = []
        context.user_data["bulk_active"] = True
        await query.edit_message_text(
            "📦 *Bulk Recaption*\n\n"
            "Send PDFs / documents / videos *here* (this private chat).\n"
            "Order is kept (first sent = first re-uploaded).\n"
            "Keywords are applied automatically.\n\n"
            "When finished, tap *Done*.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=bulk_keyboard(),
        )
        return ConversationHandler.END

    if action == "bulk_cancel":
        context.user_data["bulk"] = []
        context.user_data["bulk_active"] = False
        await query.edit_message_text("❌ Bulk cancelled.", reply_markup=back_menu_keyboard())
        return ConversationHandler.END

    if action == "bulk_done":
        return await _bulk_process(query, context)

    if action == "admins":
        if uid != OWNER_ID:
            await query.edit_message_text("⛔ Owner only.")
            return ConversationHandler.END
        async with factory() as session:
            admins = await list_admins(session)
        lines = [f"👑 Owner: `{OWNER_ID}`\n*Admins:*\n"]
        if admins:
            for a in admins:
                lines.append(f"• `{a.user_id}`")
        else:
            lines.append("_None_")
        lines.append("\nSend `/addadmin ID` or use buttons below.")
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup_admin(),
        )
        return ConversationHandler.END

    # Conversation prompts
    prompts = {
        "add_kw": (
            WAIT_KEYWORDS,
            "➕ *Add Keywords*\n\n"
            "Send in this format:\n"
            "`Mk&Sk,xyz&SK,1&2`\n\n"
            "Example: `jaat&@The_Sk08,OLD&NEW`",
        ),
        "set_batch": (WAIT_BATCH, "📚 Send *batch name* now:"),
        "set_credit": (WAIT_CREDIT, "💳 Send *credit* text now:\n(Default is `@The_Sk08`)"),
        "set_template": (
            WAIT_TEMPLATE,
            "📝 *Custom caption template*\n\n"
            "Send template text. Placeholders:\n"
            "`{title}` `{batch}` `{credit}` `{n}`\n\n"
            "Send `OFF` to disable custom template\n"
            "(then only keyword replace is used).",
        ),
        "broadcast": (WAIT_BROADCAST, "📢 Send the broadcast message now:"),
        "add_admin_prompt": (WAIT_ADD_ADMIN, "Send numeric *User ID* to add as admin:"),
        "del_admin_prompt": (WAIT_DEL_ADMIN, "Send numeric *User ID* to remove:"),
        "del_kw_prompt": (WAIT_DEL_KEYWORD, "Send *old keyword* to delete:"),
    }
    # map short actions
    if action == "add_admin":
        action = "add_admin_prompt"
    if action == "del_admin":
        action = "del_admin_prompt"
    if action == "del_kw":
        action = "del_kw_prompt"

    if action in prompts:
        if action in ("broadcast", "add_admin_prompt", "del_admin_prompt") and uid != OWNER_ID:
            await query.edit_message_text("⛔ Owner only.")
            return ConversationHandler.END
        state, text = prompts[action]
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_menu_keyboard()
        )
        return state

    await query.edit_message_text("Unknown action.", reply_markup=back_menu_keyboard())
    return ConversationHandler.END


def Inline_back_links():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(
        [
            *links_keyboard().inline_keyboard,
            [InlineKeyboardButton("◀️ Menu", callback_data="sk:menu")],
        ]
    )


def InlineKeyboardMarkup_admin():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add Admin", callback_data="sk:add_admin"),
                InlineKeyboardButton("➖ Remove", callback_data="sk:del_admin"),
            ],
            [InlineKeyboardButton("◀️ Menu", callback_data="sk:menu")],
        ]
    )


# ─── Text inputs (conversation) ─────────────────────────────

async def on_keywords_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if not await _auth(update):
        return ConversationHandler.END
    pairs = parse_multi_keywords(update.message.text or "")
    if not pairs:
        await update.message.reply_text(
            "Format not understood.\nUse: `Mk&Sk,xyz&SK`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_menu_keyboard(),
        )
        return ConversationHandler.END
    uid = update.effective_user.id
    factory = get_session_factory()
    async with factory() as session:
        s = await get_settings(session)
        key = scope_for_user(s.rule_scope, uid)
        n = await add_keyword_pairs(session, key, pairs)
        await session.commit()
    lines = [f"✅ Added *{n}* rule(s):\n"]
    for o, nw in pairs[:20]:
        lines.append(format_rule_line(o, nw) + "\n")
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=back_menu_keyboard()
    )
    return ConversationHandler.END


async def on_batch_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not await _auth(update):
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    factory = get_session_factory()
    async with factory() as session:
        await set_batch_name(session, name)
        await session.commit()
    await update.message.reply_text(
        f"📚 Batch set to:\n`{name}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_menu_keyboard(),
    )
    return ConversationHandler.END


async def on_credit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not await _auth(update):
        return ConversationHandler.END
    name = (update.message.text or "").strip() or DEFAULT_CREDIT
    factory = get_session_factory()
    async with factory() as session:
        await set_credit_name(session, name)
        await session.commit()
    await update.message.reply_text(
        f"💳 Credit set to:\n`{name}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_menu_keyboard(),
    )
    return ConversationHandler.END


async def on_template_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not await _auth(update):
        return ConversationHandler.END
    raw = (update.message.text or "").strip()
    if raw.upper() == "OFF":
        raw = ""
    factory = get_session_factory()
    async with factory() as session:
        await set_custom_template(session, raw)
        await session.commit()
    await update.message.reply_text(
        "✅ Template saved." if raw else "✅ Custom template OFF (keyword-only).",
        reply_markup=back_menu_keyboard(),
    )
    return ConversationHandler.END


async def on_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ Owner only.")
        return ConversationHandler.END
    msg_text = (update.message.text or "").strip()
    if not msg_text:
        return ConversationHandler.END
    factory = get_session_factory()
    async with factory() as session:
        users = await list_broadcast_users(session)
    status = await update.message.reply_text(f"📢 Sending to {len(users)}…")
    ok = fail = 0
    for u in users:
        try:
            await context.bot.send_message(
                u.user_id,
                f"📢 *{BOT_NAME}*\n{'─' * 12}\n\n{msg_text}",
                parse_mode=ParseMode.MARKDOWN,
            )
            ok += 1
            await asyncio.sleep(0.05)
        except Forbidden:
            fail += 1
            async with factory() as session:
                await mark_user_blocked(session, u.user_id)
                await session.commit()
        except Exception:
            fail += 1
    await status.edit_text(f"✅ Sent: {ok}\n❌ Failed: {fail}")
    return ConversationHandler.END


async def on_add_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    try:
        tid = int((update.message.text or "").strip())
    except ValueError:
        await update.message.reply_text("Need numeric ID.")
        return ConversationHandler.END
    factory = get_session_factory()
    async with factory() as session:
        added = await add_admin(session, tid, OWNER_ID)
        await session.commit()
    await update.message.reply_text(
        f"✅ Admin `{tid}`" if added else f"Already admin `{tid}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_menu_keyboard(),
    )
    return ConversationHandler.END


async def on_del_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    try:
        tid = int((update.message.text or "").strip())
    except ValueError:
        await update.message.reply_text("Need numeric ID.")
        return ConversationHandler.END
    factory = get_session_factory()
    async with factory() as session:
        removed = await remove_admin(session, tid)
        await session.commit()
    await update.message.reply_text(
        f"✅ Removed `{tid}`" if removed else "Not found.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_menu_keyboard(),
    )
    return ConversationHandler.END


async def on_del_kw_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not await _auth(update):
        return ConversationHandler.END
    old = (update.message.text or "").strip()
    uid = update.effective_user.id
    factory = get_session_factory()
    async with factory() as session:
        s = await get_settings(session)
        key = scope_for_user(s.rule_scope, uid)
        ok = await delete_keyword_rule(session, key, old)
        await session.commit()
    await update.message.reply_text(
        f"🗑 Removed `{old}`" if ok else "Not found.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_menu_keyboard(),
    )
    return ConversationHandler.END


# ─── Bulk collect + process ─────────────────────────────────

async def bulk_collect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Collect documents/videos while bulk_active in private chat."""
    if not update.message or not update.effective_user:
        return
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        return
    if not context.user_data.get("bulk_active"):
        return
    if not await _auth(update):
        return

    msg = update.message
    item = None
    if msg.document:
        item = {
            "type": "document",
            "file_id": msg.document.file_id,
            "file_name": msg.document.file_name or "file",
            "caption": msg.caption or "",
        }
    elif msg.video:
        item = {
            "type": "video",
            "file_id": msg.video.file_id,
            "file_name": getattr(msg.video, "file_name", None) or "video.mp4",
            "caption": msg.caption or "",
        }
    elif msg.animation:
        item = {
            "type": "animation",
            "file_id": msg.animation.file_id,
            "file_name": "animation.mp4",
            "caption": msg.caption or "",
        }
    if not item:
        return
    bulk: List[dict] = context.user_data.setdefault("bulk", [])
    bulk.append(item)
    await update.message.reply_text(
        f"📥 Saved *{len(bulk)}* file(s). Send more or tap *Done*.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=bulk_keyboard(),
    )


async def _bulk_process(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    bulk: List[dict] = context.user_data.get("bulk") or []
    context.user_data["bulk_active"] = False
    if not bulk:
        await query.edit_message_text("No files collected.", reply_markup=back_menu_keyboard())
        return ConversationHandler.END

    uid = query.from_user.id
    chat_id = query.message.chat_id
    factory = get_session_factory()
    async with factory() as session:
        s = await get_settings(session)
        enabled, case_sensitive, match_mode, rules = await get_rules_for_processing(
            session, uid
        )
        batch = s.batch_name
        credit = s.credit_name
        template = (s.custom_template or "").strip()

    await query.edit_message_text(f"⏳ Processing *{len(bulk)}* file(s) in order…", parse_mode=ParseMode.MARKDOWN)

    async with _lock(chat_id):
        for i, item in enumerate(bulk, 1):
            try:
                title = item.get("file_name") or "file"
                cap = item.get("caption") or ""
                # keyword replace on title + caption
                if enabled and rules:
                    title, _ = apply_replacements(title, rules, case_sensitive, match_mode)
                    if cap:
                        cap, _ = apply_replacements(cap, rules, case_sensitive, match_mode)
                if template:
                    final_cap = template.format(
                        title=title, batch=batch, credit=credit, n=f"{i:03d}"
                    )
                else:
                    final_cap = cap
                    # always show intended filename when document
                    if item["type"] == "document":
                        name_line = f"📄 {title}"
                        if final_cap and not final_cap.startswith("📄"):
                            final_cap = f"{name_line}\n\n{final_cap}"
                        elif not final_cap:
                            final_cap = name_line
                if len(final_cap) > 1024:
                    final_cap = final_cap[:1020] + "…"

                if item["type"] == "document":
                    # filename change may need download; try file_id first with caption
                    # If title changed from original file_name, download+rename
                    orig = item.get("file_name") or "file"
                    if title != orig:
                        try:
                            tg_file = await context.bot.get_file(item["file_id"])
                            data = await tg_file.download_as_bytearray()
                            bio = BytesIO(bytes(data))
                            await context.bot.send_document(
                                chat_id=chat_id,
                                document=InputFile(bio, filename=unicodedata.normalize("NFC", title)),
                                caption=final_cap or None,
                            )
                        except Exception:
                            await context.bot.send_document(
                                chat_id=chat_id,
                                document=item["file_id"],
                                caption=final_cap or None,
                            )
                    else:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=item["file_id"],
                            caption=final_cap or None,
                        )
                elif item["type"] == "video":
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=item["file_id"],
                        caption=final_cap or None,
                    )
                else:
                    await context.bot.send_animation(
                        chat_id=chat_id,
                        animation=item["file_id"],
                        caption=final_cap or None,
                    )
                await asyncio.sleep(0.15)
            except Exception as e:
                logger.exception("Bulk item %s failed: %s", i, e)

    context.user_data["bulk"] = []
    await context.bot.send_message(
        chat_id,
        f"✅ Bulk done — *{len(bulk)}* file(s) processed in order.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(uid == OWNER_ID),
    )
    return ConversationHandler.END


# ─── Live channel/group processing ──────────────────────────

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        # private: maybe bulk collect
        await bulk_collect(update, context)
        return
    if is_bot_message(message, context.bot.id):
        return

    poster_id = message.from_user.id if message.from_user else None
    factory = get_session_factory()
    async with factory() as session:
        enabled, case_sensitive, match_mode, rules = await get_rules_for_processing(
            session, poster_id
        )
    if not enabled or not rules:
        return

    async with _lock(chat.id):
        await _process_one(context, message, chat, rules, case_sensitive, match_mode)


async def _process_one(context, message, chat, rules, case_sensitive, match_mode) -> None:
    text, field = extract_text_or_caption(message)
    new_text = text or ""
    text_changed = False
    if text:
        new_text, text_changed = apply_replacements(
            text, rules, case_sensitive, match_mode
        )

    doc = message.document
    if doc and doc.file_name:
        original = unicodedata.normalize("NFC", doc.file_name)
        new_name, name_changed = apply_replacements(
            original, rules, case_sensitive, match_mode
        )
        if name_changed:
            new_name = unicodedata.normalize("NFC", new_name)
            await _rename_document(
                context,
                chat.id,
                message,
                new_name,
                new_text if (text_changed or text) else (message.caption or None),
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
        logger.info("Edited %s in %s", message.message_id, chat.id)
    except BadRequest as e:
        err = str(e).lower()
        if "not modified" in err or "not found" in err:
            return
        logger.warning("Edit fail: %s", e)
    except Exception as e:
        logger.warning("Edit error: %s", e)


async def _rename_document(context, chat_id, message, new_filename, new_caption) -> None:
    doc = message.document
    if not doc:
        return
    new_filename = unicodedata.normalize("NFC", new_filename or "file")
    if new_caption:
        new_caption = unicodedata.normalize("NFC", new_caption)
    name_line = f"📄 {new_filename}"
    if new_caption:
        if not new_caption.startswith("📄"):
            final_caption = f"{name_line}\n\n{new_caption}"
        else:
            final_caption = new_caption
    else:
        final_caption = name_line
    if len(final_caption) > 1024:
        final_caption = final_caption[:1020] + "…"
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        data = await tg_file.download_as_bytearray()
        bio = BytesIO(bytes(data))
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(bio, filename=new_filename),
            caption=final_caption,
        )
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception as e:
            logger.warning("Delete failed: %s", e)
        logger.info("Renamed %s → %r", message.message_id, new_filename)
    except Exception as e:
        logger.exception("Rename failed: %s", e)


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Cancelled.", reply_markup=back_menu_keyboard())
    return ConversationHandler.END


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    r = update.my_chat_member
    if r:
        logger.info("Membership %s: %s", r.chat.id, r.new_chat_member.status)
