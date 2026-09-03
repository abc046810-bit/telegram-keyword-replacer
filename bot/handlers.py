"""Handlers — simple global keyword bot."""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from io import BytesIO

from telegram import InputFile, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from bot.config import (
    BOT_NAME,
    DEVELOPER_USERNAME,
    FORCE_CHANNEL,
    OWNER_ID,
    OWNER_USERNAME,
)
from bot.database import (
    add_admin,
    add_rules,
    clear_rules,
    delete_rule,
    get_active_rules,
    get_session_factory,
    get_settings,
    is_authorized,
    list_admins,
    list_rules,
    remove_admin,
    set_enabled,
)
from bot.keyboards import back_kb, done_kb, main_kb
from bot.replacer import apply_replacements, parse_pairs

logger = logging.getLogger(__name__)

WAIT_ADD = 1
WAIT_ADMIN_ADD = 2
WAIT_ADMIN_DEL = 3
WAIT_DEL_KW = 4

_locks: dict[int, asyncio.Lock] = {}


def _lock(cid: int) -> asyncio.Lock:
    if cid not in _locks:
        _locks[cid] = asyncio.Lock()
    return _locks[cid]


async def _auth(uid: int) -> bool:
    fac = get_session_factory()
    async with fac() as s:
        return await is_authorized(s, uid, OWNER_ID)


def _menu_text(role: str) -> str:
    # backticks protect underscores in usernames for Markdown
    return (
        f"✨ *{BOT_NAME}*\n"
        f"_Global keyword replacer_\n"
        f"{'─' * 16}\n\n"
        f"Role: *{role}*\n\n"
        f"• Channel + groups: auto replace (caption / text / PDF name)\n"
        f"• Private: add keywords, test, manage\n"
        f"• All authorized users share *one global* list\n\n"
        f"Channel: `{FORCE_CHANNEL}`\n"
        f"Owner: `{OWNER_USERNAME}`\n"
        f"Dev: `{DEVELOPER_USERNAME}`"
    )


# ── Start / menu ────────────────────────────────────────────

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or not update.message:
        return ConversationHandler.END
    user = update.effective_user
    if not await _auth(user.id):
        await update.message.reply_text(
            f"👋 *{BOT_NAME}*\n\n"
            f"⛔ Not authorized.\n"
            f"Contact owner: `{OWNER_USERNAME}`\n"
            f"Your ID: `{user.id}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    role = "Owner" if user.id == OWNER_ID else "Admin"
    context.user_data.pop("pending_pairs", None)
    await update.message.reply_text(
        _menu_text(role),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_kb(user.id == OWNER_ID),
    )
    return ConversationHandler.END


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        f"❓ *Help*\n\n"
        f"*Add many keywords:*\n"
        f"`Mk&Sk,xyz&SK,1&2`\n"
        f"or one: `/addkeyword OLD | NEW`\n\n"
        f"*Commands*\n"
        f"/start /menu — panel\n"
        f"/addkeyword /listkeywords /deletekeyword\n"
        f"/enable /disable /status /clear\n"
        f"/addadmin /removeadmin /listadmins (owner)\n"
        f"/myid\n\n"
        f"PDF rename keeps order. Caption keeps style; only keywords change.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_kb(),
    )


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.message:
        await update.message.reply_text(
            f"🆔 `{update.effective_user.id}`", parse_mode=ParseMode.MARKDOWN
        )


# ── Callbacks ───────────────────────────────────────────────

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q or not update.effective_user:
        return ConversationHandler.END
    await q.answer()
    uid = update.effective_user.id
    if not await _auth(uid):
        await q.edit_message_text("⛔ Not authorized.")
        return ConversationHandler.END
    act = (q.data or "").split(":")[-1]
    fac = get_session_factory()

    if act == "menu":
        role = "Owner" if uid == OWNER_ID else "Admin"
        await q.edit_message_text(
            _menu_text(role),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_kb(uid == OWNER_ID),
        )
        return ConversationHandler.END

    if act == "help":
        await q.edit_message_text(
            f"*Add keywords*\n`Mk&Sk,xyz&SK`\n\n"
            f"Channel uses global list.\n"
            f"Private: same list + manage.\n"
            f"/myid for your ID.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    if act == "on":
        async with fac() as s:
            await set_enabled(s, True)
            await s.commit()
        await q.edit_message_text("🟢 Enabled", reply_markup=back_kb())
        return ConversationHandler.END

    if act == "off":
        async with fac() as s:
            await set_enabled(s, False)
            await s.commit()
        await q.edit_message_text("🔴 Disabled", reply_markup=back_kb())
        return ConversationHandler.END

    if act == "status":
        async with fac() as s:
            st = await get_settings(s)
            rules = await list_rules(s)
        await q.edit_message_text(
            f"📊 *Status*\n\n"
            f"Live: *{'ON' if st.enabled else 'OFF'}*\n"
            f"Rules: *{len(rules)}*\n"
            f"Mode: global (channel + groups)\n"
            f"Match: `{st.match_mode}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb(),
        )
        return ConversationHandler.END

    if act == "list":
        async with fac() as s:
            rules = await list_rules(s)
        if not rules:
            await q.edit_message_text("📭 No keywords.", reply_markup=back_kb())
            return ConversationHandler.END
        lines = [f"📋 *{len(rules)} rules*\n"]
        for i, r in enumerate(rules, 1):
            lines.append(f"{i}. `{r.old_keyword}` → `{r.new_keyword}`")
        body = "\n".join(lines)
        if len(body) > 3500:
            body = body[:3500] + "\n…"
        await q.edit_message_text(body, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb())
        return ConversationHandler.END

    if act == "clear":
        async with fac() as s:
            n = await clear_rules(s)
            await s.commit()
        await q.edit_message_text(f"🧹 Cleared {n} rule(s).", reply_markup=back_kb())
        return ConversationHandler.END

    if act == "add":
        context.user_data["pending_pairs"] = []
        await q.edit_message_text(
            "➕ *Add keywords*\n\n"
            "Send one or more lines:\n"
            "`Mk&Sk,xyz&SK,1&2`\n\n"
            "You can send multiple messages.\n"
            "When finished tap *Done*.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=done_kb(),
        )
        return WAIT_ADD

    if act == "done_add":
        pairs = context.user_data.get("pending_pairs") or []
        context.user_data["pending_pairs"] = []
        if not pairs:
            await q.edit_message_text("Nothing to save.", reply_markup=back_kb())
            return ConversationHandler.END
        async with fac() as s:
            n = await add_rules(s, pairs)
            await s.commit()
        lines = [f"✅ Saved *{n}* rule(s)\n"]
        for o, n_ in pairs[:30]:
            lines.append(f"• `{o}` → `{n_}`")
        await q.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb()
        )
        return ConversationHandler.END

    if act == "cancel":
        context.user_data["pending_pairs"] = []
        await q.edit_message_text("Cancelled.", reply_markup=back_kb())
        return ConversationHandler.END

    if act == "admins":
        if uid != OWNER_ID:
            await q.edit_message_text("Owner only.", reply_markup=back_kb())
            return ConversationHandler.END
        async with fac() as s:
            admins = await list_admins(s)
        lines = [f"👑 Owner `{OWNER_ID}`\n"]
        for a in admins:
            lines.append(f"• `{a.user_id}`")
        lines.append("\n`/addadmin ID` · `/removeadmin ID`")
        await q.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb()
        )
        return ConversationHandler.END

    return ConversationHandler.END


async def on_add_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if not await _auth(update.effective_user.id):
        return ConversationHandler.END
    pairs = parse_pairs(update.message.text or "")
    if not pairs:
        await update.message.reply_text(
            "Format: `Mk&Sk,xyz&SK`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=done_kb(),
        )
        return WAIT_ADD
    pending = context.user_data.setdefault("pending_pairs", [])
    pending.extend(pairs)
    await update.message.reply_text(
        f"📥 Queued *{len(pairs)}* (total pending *{len(pending)}*).\n"
        f"Send more or tap *Done*.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=done_kb(),
    )
    return WAIT_ADD


# ── Commands ────────────────────────────────────────────────

async def addkeyword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not await _auth(update.effective_user.id):
        await update.message.reply_text("⛔ Not authorized.")
        return
    pairs = parse_pairs(update.message.text or "")
    if not pairs:
        await update.message.reply_text(
            "Usage:\n`/addkeyword OLD | NEW`\n"
            "or `/addkeyword Mk&Sk,xyz&SK`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    fac = get_session_factory()
    async with fac() as s:
        n = await add_rules(s, pairs)
        await s.commit()
    await update.message.reply_text(
        f"✅ Saved {n} rule(s).", parse_mode=ParseMode.MARKDOWN
    )


async def listkeywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not await _auth(update.effective_user.id):
        return
    fac = get_session_factory()
    async with fac() as s:
        rules = await list_rules(s)
    if not rules:
        await update.message.reply_text("📭 Empty.")
        return
    lines = [f"📋 {len(rules)} rules\n"]
    for r in rules:
        lines.append(f"• `{r.old_keyword}` → `{r.new_keyword}`")
    body = "\n".join(lines)
    if len(body) > 3500:
        body = body[:3500] + "\n…"
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


async def deletekeyword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not await _auth(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/deletekeyword OLD`", parse_mode=ParseMode.MARKDOWN)
        return
    old = " ".join(context.args).strip()
    fac = get_session_factory()
    async with fac() as s:
        ok = await delete_rule(s, old)
        await s.commit()
    await update.message.reply_text("🗑 Removed." if ok else "Not found.")


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not await _auth(update.effective_user.id):
        return
    fac = get_session_factory()
    async with fac() as s:
        n = await clear_rules(s)
        await s.commit()
    await update.message.reply_text(f"🧹 Cleared {n}.")


async def enable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not await _auth(update.effective_user.id):
        return
    fac = get_session_factory()
    async with fac() as s:
        await set_enabled(s, True)
        await s.commit()
    await update.message.reply_text("🟢 Enabled")


async def disable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not await _auth(update.effective_user.id):
        return
    fac = get_session_factory()
    async with fac() as s:
        await set_enabled(s, False)
        await s.commit()
    await update.message.reply_text("🔴 Disabled")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not await _auth(update.effective_user.id):
        return
    fac = get_session_factory()
    async with fac() as s:
        st = await get_settings(s)
        rules = await list_rules(s)
    await update.message.reply_text(
        f"Live: {'ON' if st.enabled else 'OFF'}\nRules: {len(rules)}"
    )


async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/addadmin USER_ID`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Numeric ID required.")
        return
    fac = get_session_factory()
    async with fac() as s:
        ok = await add_admin(s, tid, OWNER_ID)
        await s.commit()
    await update.message.reply_text(f"✅ Admin `{tid}`" if ok else "Already admin.", parse_mode=ParseMode.MARKDOWN)


async def removeadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removeadmin USER_ID`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        return
    fac = get_session_factory()
    async with fac() as s:
        ok = await remove_admin(s, tid)
        await s.commit()
    await update.message.reply_text("Removed." if ok else "Not found.")


async def listadmins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not await _auth(update.effective_user.id):
        return
    fac = get_session_factory()
    async with fac() as s:
        admins = await list_admins(s)
    lines = [f"Owner `{OWNER_ID}`"] + [f"• `{a.user_id}`" for a in admins]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── Live process ────────────────────────────────────────────

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    # private: only process if not a command conversation — skip private auto-edit of user msgs
    # User asked private also works for replace — optional. Usually private is config.
    # Spec: channel + private both. In private, if user sends media with keywords, replace.
    if message.from_user and message.from_user.id == context.bot.id:
        return

    fac = get_session_factory()
    async with fac() as s:
        enabled, case_s, mode, rules = await get_active_rules(s)
    if not enabled or not rules:
        return

    async with _lock(chat.id):
        await _one(context, message, chat, rules, case_s, mode)


async def _one(context, message, chat, rules, case_s, mode) -> None:
    text = message.text if message.text is not None else message.caption
    field = "text" if message.text is not None else ("caption" if message.caption is not None else None)
    new_text = text or ""
    text_changed = False
    if text:
        new_text, text_changed = apply_replacements(text, rules, case_s, mode)

    doc = message.document
    if doc and doc.file_name:
        orig = unicodedata.normalize("NFC", doc.file_name)
        new_name, name_ch = apply_replacements(orig, rules, case_s, mode)
        if name_ch:
            await _rename(
                context,
                chat.id,
                message,
                unicodedata.normalize("NFC", new_name),
                new_text if (text_changed or text) else (message.caption or None),
            )
            return

    if not text_changed or field is None:
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
        logger.info("Edited msg %s in %s", message.message_id, chat.id)
    except BadRequest as e:
        if "not modified" in str(e).lower() or "not found" in str(e).lower():
            return
        logger.warning("Edit: %s", e)
    except Exception as e:
        logger.warning("Edit err: %s", e)


async def _rename(context, chat_id, message, new_filename, new_caption) -> None:
    doc = message.document
    if not doc:
        return
    new_filename = unicodedata.normalize("NFC", new_filename or "file")
    if new_caption:
        new_caption = unicodedata.normalize("NFC", new_caption)
    name_line = f"📄 {new_filename}"
    if new_caption and not new_caption.startswith("📄"):
        final = f"{name_line}\n\n{new_caption}"
    elif new_caption:
        final = new_caption
    else:
        final = name_line
    if len(final) > 1024:
        final = final[:1020] + "…"
    try:
        tg = await context.bot.get_file(doc.file_id)
        data = await tg.download_as_bytearray()
        bio = BytesIO(bytes(data))
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(bio, filename=new_filename),
            caption=final,
        )
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception:
            pass
        logger.info("Renamed %s → %r", message.message_id, new_filename)
    except Exception as e:
        logger.exception("Rename fail: %s", e)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["pending_pairs"] = []
    if update.message:
        await update.message.reply_text("Cancelled.", reply_markup=back_kb())
    return ConversationHandler.END
