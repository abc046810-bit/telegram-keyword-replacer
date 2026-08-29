"""Premium inline keyboards."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add Rule", callback_data="panel:add"),
                InlineKeyboardButton("📋 My Rules", callback_data="panel:list"),
            ],
            [
                InlineKeyboardButton("🟢 Enable", callback_data="panel:enable"),
                InlineKeyboardButton("🔴 Disable", callback_data="panel:disable"),
            ],
            [
                InlineKeyboardButton("📊 Status", callback_data="panel:status"),
                InlineKeyboardButton("🧹 Clear Rules", callback_data="panel:clear"),
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="panel:help"),
            ],
        ]
    )


def owner_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add Rule", callback_data="panel:add"),
                InlineKeyboardButton("📋 My Rules", callback_data="panel:list"),
            ],
            [
                InlineKeyboardButton("🟢 Enable", callback_data="panel:enable"),
                InlineKeyboardButton("🔴 Disable", callback_data="panel:disable"),
            ],
            [
                InlineKeyboardButton("📊 Status", callback_data="panel:status"),
                InlineKeyboardButton("👥 Admins", callback_data="panel:admins"),
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="panel:broadcast"),
                InlineKeyboardButton("🧹 Clear Rules", callback_data="panel:clear"),
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="panel:help"),
            ],
        ]
    )
