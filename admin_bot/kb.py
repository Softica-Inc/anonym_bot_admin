from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def members_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Member", callback_data="members_add")],
        [InlineKeyboardButton(text="❌ Remove Member", callback_data="members_remove")],
        [InlineKeyboardButton(text="📋 Members List", callback_data="members_list")],
    ])

# -----------------------
# Main Menu
# -----------------------



from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        # ── Управління ботами ─────────────────────
        [
            InlineKeyboardButton(text="🆕 New Bot", callback_data="new_bot"),
            InlineKeyboardButton(text="▶️ Start Bot", callback_data="start_bot")
        ],
        [
            InlineKeyboardButton(text="📋 Bot List", callback_data="bot_list"),
            InlineKeyboardButton(text="❌ Delete Bot", callback_data="delete_bot")
        ],

        # ── Створення та налаштування чату ────────
        [
            InlineKeyboardButton(text="💬 Create Chat", callback_data="create_chat"),
            InlineKeyboardButton(text="🔗 Link Group", callback_data="link_group")
        ],

        # ── Інвайти та учасники ───────────────────
        [
            InlineKeyboardButton(text="🔗 Invite", callback_data="invite"),
            InlineKeyboardButton(text="📤 Invite Team", callback_data="invite_team")
        ],
        [
            InlineKeyboardButton(text="👥 Members", callback_data="members")
        ],

        # ── Модерація ─────────────────────────────
        [
            InlineKeyboardButton(text="🥷 Kick / Kick All", callback_data="kick"),
            InlineKeyboardButton(text="🗑 Delete / Delete All", callback_data="delete_msm")
        ],

        # ── Аналітика та розсилки ─────────────────
        [InlineKeyboardButton(text="📜 Chat History", callback_data="show_chat_rooms")],
        [InlineKeyboardButton(text="📢 Admin Push", callback_data="admin_push")],

        # ── Адмінське (опціонально) ───────────────
        # [InlineKeyboardButton(text="🔑 Change Pass for Admin", callback_data="change_pass")]
    ])
    return kb



