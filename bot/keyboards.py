from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bot.config import FORCE_CHANNEL, OWNER_USERNAME, DEVELOPER_USERNAME


def main_kb(is_owner: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("➕ Add Keywords", callback_data="m:add"),
            InlineKeyboardButton("📋 List", callback_data="m:list"),
        ],
        [
            InlineKeyboardButton("🟢 Enable", callback_data="m:on"),
            InlineKeyboardButton("🔴 Disable", callback_data="m:off"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="m:status"),
            InlineKeyboardButton("🧹 Clear All", callback_data="m:clear"),
        ],
        [InlineKeyboardButton("❓ Help", callback_data="m:help")],
    ]
    if is_owner:
        rows.append(
            [
                InlineKeyboardButton("👥 Admins", callback_data="m:admins"),
            ]
        )
    ch = FORCE_CHANNEL.lstrip("@")
    own = OWNER_USERNAME.lstrip("@")
    dev = DEVELOPER_USERNAME.lstrip("@")
    rows.append(
        [
            InlineKeyboardButton("📢 Channel", url=f"https://t.me/{ch}"),
            InlineKeyboardButton("👑 Owner", url=f"https://t.me/{own}"),
            InlineKeyboardButton("🛠 Dev", url=f"https://t.me/{dev}"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Done — Save Keywords", callback_data="m:done_add")],
            [InlineKeyboardButton("❌ Cancel", callback_data="m:cancel")],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Menu", callback_data="m:menu")]]
    )
