"""Premium inline keyboards — SK Keywords Replacer."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.branding import (
    FORCE_CHANNEL,
    OWNER_USERNAME,
    DEVELOPER_USERNAME,
)


def force_join_keyboard() -> InlineKeyboardMarkup:
    ch = FORCE_CHANNEL.lstrip("@")
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{ch}")],
            [InlineKeyboardButton("✅ I Joined — Continue", callback_data="sk:check_join")],
        ]
    )


def links_keyboard() -> InlineKeyboardMarkup:
    ch = FORCE_CHANNEL.lstrip("@")
    own = OWNER_USERNAME.lstrip("@")
    dev = DEVELOPER_USERNAME.lstrip("@")
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Channel", url=f"https://t.me/{ch}")],
            [
                InlineKeyboardButton("👑 Owner", url=f"https://t.me/{own}"),
                InlineKeyboardButton("🛠 Developer", url=f"https://t.me/{dev}"),
            ],
        ]
    )


def main_menu_keyboard(is_owner: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🌐 Global Mode", callback_data="sk:mode_global"),
            InlineKeyboardButton("👤 My Keywords", callback_data="sk:mode_personal"),
        ],
        [InlineKeyboardButton("📦 Bulk Recaption", callback_data="sk:bulk")],
        [
            InlineKeyboardButton("➕ Add Keywords", callback_data="sk:add_kw"),
            InlineKeyboardButton("📋 List Keywords", callback_data="sk:list_kw"),
        ],
        [
            InlineKeyboardButton("🟢 Enable", callback_data="sk:enable"),
            InlineKeyboardButton("🔴 Disable", callback_data="sk:disable"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="sk:status"),
            InlineKeyboardButton("⚙️ Settings", callback_data="sk:settings"),
        ],
        [
            InlineKeyboardButton("🔗 Links", callback_data="sk:links"),
            InlineKeyboardButton("❓ Help", callback_data="sk:help"),
        ],
    ]
    if is_owner:
        rows.append(
            [
                InlineKeyboardButton("👥 Admins", callback_data="sk:admins"),
                InlineKeyboardButton("📢 Broadcast", callback_data="sk:broadcast"),
            ]
        )
    return InlineKeyboardMarkup(rows)


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📚 Set Batch", callback_data="sk:set_batch"),
                InlineKeyboardButton("💳 Set Credit", callback_data="sk:set_credit"),
            ],
            [InlineKeyboardButton("📝 Custom Template", callback_data="sk:set_template")],
            [
                InlineKeyboardButton("Case: ON/OFF", callback_data="sk:toggle_case"),
                InlineKeyboardButton("Match mode", callback_data="sk:toggle_match"),
            ],
            [InlineKeyboardButton("🗑 Clear My/Global Rules", callback_data="sk:clear_kw")],
            [InlineKeyboardButton("◀️ Back", callback_data="sk:menu")],
        ]
    )


def bulk_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Done — Process All", callback_data="sk:bulk_done")],
            [InlineKeyboardButton("❌ Cancel Bulk", callback_data="sk:bulk_cancel")],
            [InlineKeyboardButton("◀️ Menu", callback_data="sk:menu")],
        ]
    )


def back_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Main Menu", callback_data="sk:menu")]]
    )
