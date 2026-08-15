"""Optional inline keyboards for admin panel."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("➕ Add Keyword", callback_data="panel:add"),
            InlineKeyboardButton("➖ Delete Keyword", callback_data="panel:delete"),
        ],
        [
            InlineKeyboardButton("📋 List Keywords", callback_data="panel:list"),
            InlineKeyboardButton("🧹 Clear All", callback_data="panel:clear"),
        ],
        [
            InlineKeyboardButton("🟢 Enable", callback_data="panel:enable"),
            InlineKeyboardButton("🔴 Disable", callback_data="panel:disable"),
        ],
        [
            InlineKeyboardButton("⚙️ Case Sensitive", callback_data="panel:case"),
            InlineKeyboardButton("📊 Status", callback_data="panel:status"),
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="panel:help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data="panel:cancel")]]
    )