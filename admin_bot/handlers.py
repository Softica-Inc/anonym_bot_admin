# admin_bot/handlers.py
import asyncio
import datetime
import os
import uuid
import zipfile
import aiohttp
import uuid
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
import aiohttp
import logging
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from aiogram.types import FSInputFile, BufferedInputFile
from cryptography.fernet import Fernet
from aiogram.filters import StateFilter
from aiogram import F

import models
from config import settings
from kb import members_menu_kb, main_menu
from utils import validate_telegram_token, register_token_to_backend, engine, escape_markdown, safe_edit_message, \
    format_chat_history
from aiogram.types import CallbackQuery
from sqlalchemy.orm import sessionmaker
from io import BytesIO

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramBadRequest


router = Router()


logging.basicConfig(level=logging.INFO)

SessionLocal = sessionmaker(bind=engine)

# Налаштування логування
logger = logging.getLogger(__name__)
MEDIA_ROOT = os.getenv(
    "MEDIA_ROOT",
    r"C:\Users\Bohord\IDEshku\PycharmProjects\anonym_bot_backe\media"
)

# -----------------------
# FSM States
# -----------------------
class AuthStates(StatesGroup):
    waiting_password = State()
    waiting_email = State()

class NewBotStates(StatesGroup):
    waiting_token = State()
    waiting_mode = State()
    waiting_chat_details = State()
    waiting_invite_details = State()

class ChatStates(StatesGroup):
    waiting_bot = State()
    waiting_title = State()

class MembersFSM(StatesGroup):
    waiting_add_participant = State()
    waiting_remove_participant = State()

class MemberStates(StatesGroup):
    waiting_add = State()
    waiting_remove = State()
    waiting_edit = State()

class TeamInviteStates(StatesGroup):
    waiting_room = State()
    waiting_pseudonyms = State()
    waiting_count = State()
    waiting_extend = State()

class AdminPushStates(StatesGroup):
    waiting_room = State()
    waiting_text = State()

class LinkGroupStates(StatesGroup):
    waiting_room = State()
    waiting_group_id = State()

# -----------------------
# Main Menu
# -----------------------


async def cmd_auth(message: Message, state: FSMContext):
    await state.set_state(AuthStates.waiting_password)
    await message.answer("Введіть пароль для аутентифікації.")

async def handle_password(message: Message, state: FSMContext):
    password = message.text.strip()
    if password != settings.ADMIN_PASSWORD:
        await message.answer("Невірний пароль.")
        return

    db = SessionLocal()
    try:
        admin = db.query(models.AdminUser).filter_by(tg_user_id=message.from_user.id).first()
        if not admin:
            admin = models.AdminUser(tg_user_id=message.from_user.id)
            db.add(admin)
            db.commit()
    finally:
        db.close()

    await message.answer("Аутентифікація успішна!")
    await state.clear()


# -----------------------
# Start Command
# -----------------------
async def cmd_start(message: Message, state: FSMContext):
    await message.answer("Welcome! Choose an action:", reply_markup=main_menu())

# -----------------------
# Bot Management
# -----------------------
async def cmd_new_bot(message: Message, state: FSMContext):
    await state.set_state(NewBotStates.waiting_token)
    await message.answer("Send your bot token from @BotFather:")

async def handle_token(message: Message, state: FSMContext):
    token = message.text.strip()
    info = await validate_telegram_token(token)
    if not info:
        await message.answer("Invalid token.")
        return
    await state.update_data(token=token, username=info['username'])
    await state.set_state(NewBotStates.waiting_mode)
    await message.answer(
        "Choose bot mode: 'single' or 'multi'\n\n"
        "Single-bot mode: One bot handles multiple chats simultaneously.\n"
        "Multi-bot mode: A separate bot instance is created for each chat or client."
    )
async def handle_mode(message: Message, state: FSMContext):
    mode = message.text.strip().lower()

    if mode not in ["single", "multi"]:
        await message.answer("Incorrect mode. Select ‘single’ or ‘multi’.")
        return
    data = await state.get_data()
    token = data["token"]
    try:
        result = await register_token_to_backend(
            settings.BACKEND_URL,
            token,
            mode=mode,
            owner_tg_id=message.from_user.id
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/start_bot",
                json={"bot_id": result['id'], "owner_tg_id": message.from_user.id}
            ) as resp:
                if resp.status >= 400:
                    j = await resp.json()
                    await message.answer(f"Bot startup error: {j.get('detail', 'Unknown error')}")
                    return
                start_result = await resp.json()
        await message.answer(f"The bot has been successfully registered and launched: {result['username']} (id={result['tg_bot_id']}), mode: {result['mode']}\nLaunch status: {start_result.get('status')}",
)
    except Exception as e:
        logging.error(f"Error in registration or start: {e}")
        await message.answer(f"An error occurred during registration or startup. Please try again later.")
        return
    await state.clear()

async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Operation cancelled.", reply_markup=main_menu())

# -----------------------
# Bot Management
# -----------------------

async def cmd_start_bot(message: Message):
    db = SessionLocal()
    bots = db.query(models.Bot).all()
    db.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[])

    if not bots:
        kb.inline_keyboard.append([InlineKeyboardButton(text="❌ No bots registered", callback_data="none")])
    else:
        for b in bots:
            kb.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"▶️ Start {b.username} (id={b.id})",
                    callback_data=f"start_bot_{b.id}"
                )
            ])

    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")])

    await safe_edit_message(
        message,
        escape_markdown("🤖 Choose a bot to start:"),
        reply_markup=kb
    )


async def handle_start_bot(callback: CallbackQuery):
    import httpx

    parts = callback.data.split("_")
    if len(parts) != 3:
        await safe_edit_message(callback.message, escape_markdown("❌ Invalid callback data"), parse_mode="MarkdownV2")
        return

    bot_id = int(parts[-1])

    await safe_edit_message(
        callback.message,
        escape_markdown(f"▶️ Starting bot #{bot_id}... ⏳"),
        parse_mode="MarkdownV2"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/start_bot",
                json={"bot_id": bot_id}
            )
        if resp.status_code == 200:
            data = resp.json()
            await safe_edit_message(
                callback.message,
                escape_markdown(f"✅ Bot #{bot_id} started: {data.get('status', 'ok')}"),
                parse_mode="MarkdownV2"
            )
        else:
            await safe_edit_message(
                callback.message,
                escape_markdown(f"❌ Failed: {resp.text}"),
                parse_mode="MarkdownV2"
            )
    except Exception as e:
        await safe_edit_message(
            callback.message,
            escape_markdown(f"⚠️ Error contacting backend: {e}"),
            parse_mode="MarkdownV2"
        )

    await callback.answer()



# -----------------------
# Chat Management
# -----------------------

async def cmd_create_chat(message: Message, state: FSMContext):
    db = SessionLocal()
    bots = db.query(models.Bot).all()
    db.close()

    if not bots:
        await safe_edit_message(message, "❌ No bots available.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🤖 {b.username} (id={b.id})",
                              callback_data=f"choose_bot_{b.id}")]
        for b in bots
    ])
    kb.inline_keyboard.append(
        [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
    )

    await state.set_state(ChatStates.waiting_bot)
    await safe_edit_message(
        message,
        "🔹 Select a bot to create a chat room:",
        reply_markup=kb
    )


async def handle_choose_bot(callback: CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split("_")[-1])
    await state.update_data(bot_id=bot_id)

    await state.set_state(ChatStates.waiting_title)
    await safe_edit_message(
        callback.message,
        "✏️ Enter a name for the new chat room:"
    )
    await callback.answer()


async def handle_chat_title(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data.get("bot_id")
    title = message.text.strip()

    if not title:
        await safe_edit_message(
            message,
            "❌ Please enter a name for the chat room."
        )
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/create_chat",
                json={"bot_id": bot_id, "title": title},
                timeout=10
            ) as resp:
                if resp.status >= 400:
                    try:
                        j = await resp.json()
                    except Exception:
                        j = {"detail": "Unknown error"}
                    await safe_edit_message(
                        message,
                        f"⚠️ Failed to create chat room: {j.get('detail')}"
                    )
                    return
                result = await resp.json()
    except Exception as e:
        await safe_edit_message(
            message,
            f"❌ Failed to create chat room: {e}"
        )
        return

    await safe_edit_message(
        message,
        f"✅ Chat room created!\n"
        f"Title: {result['title']}\n"
        f"ID: {result['id']}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
            ]
        )
    )
    await state.clear()


# -----------------------
# Invite Management
# -----------------------

async def cmd_invite(message: Message, state: FSMContext):
    db = SessionLocal()
    try:
        rooms = db.query(models.ChatRoom).all()
        if not rooms:
            await message.answer("❌ No chat rooms found.")
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[])

        for r in rooms:
            participants = db.query(models.Participant).filter_by(room_id=r.id).all()
            if not participants:
                continue

            for p in participants:
                kb.inline_keyboard.append([
                    InlineKeyboardButton(
                        text=f"👤 {p.pseudonym} (room {r.title})",
                        callback_data=f"invite_user_{r.id}_{p.id}"
                    )
                ])

        # додаємо кнопку "Назад"
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")
        ])

        if not kb.inline_keyboard:
            await message.answer("❌ No participants found in any room.")
            return

        await safe_edit_message(message, "Select a participant to generate invite:", reply_markup=kb)

    finally:
        db.close()


async def handle_invite_user(callback: CallbackQuery, state: FSMContext):
    try:
        _, _, room_id, participant_id = callback.data.split("_")
        room_id = int(room_id)
        participant_id = int(participant_id)
    except Exception:
        await safe_edit_message(callback.message, "❌ Invalid user selection.")
        return

    db = SessionLocal()
    try:
        participant = db.query(models.Participant).filter_by(id=participant_id, room_id=room_id).first()
        if not participant:
            await safe_edit_message(callback.message, "❌ Participant not found.")
            return

        pseudonym = participant.pseudonym

        # виклик API для інвайту
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/generate_invite",
                json={"room_id": room_id, "pseudonym": pseudonym},
                timeout=10
            ) as resp:
                if resp.status >= 400:
                    try:
                        j = await resp.json()
                    except Exception:
                        j = {"detail": "Unknown error"}
                    await safe_edit_message(callback.message, f"❌ Error creating invite: {j.get('detail')}")
                    return
                result = await resp.json()

        # знайдемо username бота
        room = db.query(models.ChatRoom).filter_by(id=room_id).first()
        bot = db.query(models.Bot).filter_by(id=room.bot_id).first() if room else None
        if not bot:
            await safe_edit_message(callback.message, "❌ Bot not found for this room.")
            return

        link = f"https://t.me/{bot.username}?start={result['code']}"
        text = (
            f"✅ Invite created for <b>{pseudonym}</b>\n\n"
            f"🔗 <a href='{link}'>{link}</a>\n"
            f"⚠️ Single-use, expires in 1h."
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
        ])

        await safe_edit_message(callback.message, text, reply_markup=kb, parse_mode="HTML")

    finally:
        db.close()



# -----------------------
# Admin Permitions
# -----------------------
async def check_admin_permissions(message: Message):
    # from app.database import SessionLocal
    # from app.models import AdminUser
    #
    # db = SessionLocal()
    # try:
    #     admin = db.query(AdminUser).filter_by(tg_user_id=message.from_user.id).first()
    #     if not admin:
    #         await message.answer("Ви не маєте прав для цієї дії.")
    #         return False
    # finally:
    #     db.close()
    return True

# -----------------------
# Members Management
# -----------------------

async def cmd_members(message: Message, state: FSMContext):
    await render_members_menu(message)

async def handle_members_menu(callback: CallbackQuery, state: FSMContext):
    if callback.data == "members_add":
        await safe_edit_message(
            callback.message,
            "✏️ Enter `chat_id tg_user_id pseudonym [tag]` to add a new member:",
            parse_mode="MarkdownV2"
        )
        await state.set_state(MemberStates.waiting_add)

    elif callback.data == "members_remove":
        await render_members_select(callback.message, action="remove")

    elif callback.data == "members_edit":
        await render_members_select(callback.message, action="edit")

    elif callback.data == "members_back":
        await render_members_menu(callback.message)
        await state.clear()

async def handle_add_member(message: Message, state: FSMContext):
    parts = message.text.strip().split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            escape_markdown("⚠️ Wrong format. Use: `chat_id tg_user_id pseudonym [tag]`"),
            parse_mode="MarkdownV2"
        )
        return

    chat_id, tg_user_id, pseudonym = parts[:3]
    tag = parts[3] if len(parts) > 3 else None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/add_participant",
                json={
                    "room_id": int(chat_id),
                    "tg_user_id": int(tg_user_id),
                    "pseudonym": pseudonym,
                    "tag": tag
                },
                timeout=10
            ) as resp:
                if resp.status >= 400:
                    try:
                        j = await resp.json()
                    except Exception:
                        j = {"detail": "Unknown error"}
                    await message.answer(
                        escape_markdown(f"❌ Failed to add member: {j.get('detail')}"),
                        parse_mode="MarkdownV2"
                    )
                    return

                result = await resp.json()

        # Отримуємо назву чату з локальної БД
        db = SessionLocal()
        room = db.query(models.ChatRoom).filter_by(id=result['room_id']).first()
        room_title = room.title if room else f"ID {result['room_id']}"
        db.close()

        await message.answer(
            escape_markdown(
                f"✅ Member '{result['pseudonym']}' (tg_user_id={result['tg_user_id']}) "
                f"added to chat '{room_title}'"
            ),
            parse_mode="MarkdownV2"
        )

    except aiohttp.ClientConnectionError:
        await message.answer(
            escape_markdown("❌ Cannot connect to backend. Check if it is running."),
            parse_mode="MarkdownV2"
        )
    except asyncio.TimeoutError:
        await message.answer(
            escape_markdown("⏳ Timeout while connecting to backend."),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        logging.exception(f"Unexpected error in handle_add_member: {e}")
        await message.answer(
            escape_markdown("❌ Unexpected error while adding member."),
            parse_mode="MarkdownV2"
        )
    finally:
        await state.clear()

async def handle_member_action(callback: CallbackQuery, state: FSMContext):
    data = callback.data  # members_remove_12 або members_edit_34
    if data.startswith("members_remove_"):
        participant_id = int(data.split("_")[-1])
        db = SessionLocal()
        participant = db.query(models.Participant).filter_by(id=participant_id).first()
        if participant:
            db.delete(participant)
            db.commit()
            await callback.message.answer(f"✅ Member {escape_markdown(participant.pseudonym)} removed.")
        db.close()
        await render_members_menu(callback.message)

    elif data.startswith("members_edit_"):
        participant_id = int(data.split("_")[-1])
        db = SessionLocal()
        participant = db.query(models.Participant).filter_by(id=participant_id).first()
        db.close()
        if participant:
            await safe_edit_message(
                callback.message,
                f"✏️ Enter new pseudonym and optional tag for {escape_markdown(participant.pseudonym)}:\n`new_pseudonym [new_tag]`",
                parse_mode="MarkdownV2"
            )
            # зберігаємо у стані id редагованого учасника
            await state.update_data(edit_participant_id=participant_id)
            await state.set_state(MemberStates.waiting_edit)


async def handle_remove_member(message: Message, state: FSMContext):
    db = SessionLocal()
    try:
        parts = message.text.strip().split(maxsplit=2)
        if len(parts) < 2:
            await message.answer(escape_markdown("⚠️ Wrong format. Use: `chat_id user_id`"), parse_mode="MarkdownV2")
            return

        chat_id, user_id = int(parts[0]), int(parts[1])
        participant = db.query(models.Participant).filter_by(
            room_id=chat_id, tg_user_id=user_id
        ).first()

        if not participant:
            await message.answer(escape_markdown("❌ Member not found."), parse_mode="MarkdownV2")
        else:
            db.delete(participant)
            db.commit()
            await message.answer(
                escape_markdown(f"✅ Member {user_id} removed from chat {chat_id}"),
                parse_mode="MarkdownV2"
            )
    except Exception as e:
        await message.answer(escape_markdown(f"❌ Failed to remove member: {e}"), parse_mode="MarkdownV2")
    finally:
        db.close()
        await state.clear()

async def render_members_select(message_or_cbmsg, action: str):
    """
    action: 'remove' або 'edit'
    """
    db = SessionLocal()
    participants = db.query(models.Participant).all()
    db.close()

    if not participants:
        await safe_edit_message(message_or_cbmsg, "📋 No members in this chat yet.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])

    for p in participants:
        # callback_data формату: members_remove_{participant_id} або members_edit_{participant_id}
        cb_data = f"members_{action}_{p.id}"
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=p.pseudonym, callback_data=cb_data)
        ])

    # Додати кнопку назад
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="members_back")])

    await safe_edit_message(
        message_or_cbmsg,
        f"📋 Select a member to {action}:",
        reply_markup=kb,
        parse_mode="MarkdownV2"
    )

async def render_members_menu(message_or_cbmsg):
    db = SessionLocal()
    participants = db.query(models.Participant).all()

    if not participants:
        text = escape_markdown("📋 No members in this chat yet.")
    else:
        text = "📋 *Members list:*\n\n"
        for p in participants:
            text += (
                f"🆔 *ID:* `{p.id}`\n"
                f"👤 *Pseudonym:* {escape_markdown(p.pseudonym)}\n"
                f"📎 *TG ID:* `{p.tg_user_id}`\n"
            )
            if p.tag:
                text += f"🏷 *Tag:* {escape_markdown(p.tag)}\n"
            text += "━━━━━━━━━━━━━━\n"

    db.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add", callback_data="members_add")],
        [InlineKeyboardButton(text="➖ Remove", callback_data="members_remove")],
        [InlineKeyboardButton(text="✏️ Edit", callback_data="members_edit")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
    ])

    await safe_edit_message(
        message_or_cbmsg,
        text,
        reply_markup=kb,
        parse_mode="MarkdownV2"
    )

async def handle_edit_member(message: Message, state: FSMContext):
    data = await state.get_data()
    participant_id = data.get("edit_participant_id")
    if not participant_id:
        await message.answer("❌ No participant selected to edit.")
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 1:
        await message.answer(
            "⚠️ Wrong format. Use: `new_pseudonym [new_tag]`"
        )
        return

    new_pseudonym = parts[0]
    new_tag = parts[1] if len(parts) > 1 else None

    db = SessionLocal()
    try:
        participant = db.query(models.Participant).filter_by(id=participant_id).first()
        if not participant:
            await message.answer("❌ Member not found.")
        else:
            participant.pseudonym = new_pseudonym
            participant.tag = new_tag
            db.commit()

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Back", callback_data="members_back")]
            ])

            await message.answer(
                f"✅ Member {escape_markdown(new_pseudonym)} updated successfully.",
                reply_markup=kb,
                parse_mode="MarkdownV2"
            )
    finally:
        db.close()
        await state.clear()


# -----------------------
# History
# -----------------------

async def show_chat_rooms(message):
    db = SessionLocal()
    rooms = db.query(models.ChatRoom).all()

    if rooms:
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for room in rooms:
            kb.inline_keyboard.append([InlineKeyboardButton(
                text=f"Room: {room.title} (ID: {room.id})",
                callback_data=f"chat_history_{room.id}"
            )])
        kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")])
        await safe_edit_message(message, "Select a chat room to get the history:", reply_markup=kb)
    else:
        await safe_edit_message(message, "No chat rooms found.")

    db.close()


async def handle_chat_history(callback_query, state):
    room_id = int(callback_query.data.split('_')[-1])
    db = SessionLocal()

    chat_history = db.query(models.Message).filter_by(room_id=room_id).all()
    if not chat_history:
        await safe_edit_message(callback_query.message, "No messages found in this room.")
        db.close()
        return

    # ---- formatted preview (last 40 messages) ----
    preview_md = ""
    for msg in chat_history[-40:]:
        sender = db.query(models.Participant).filter_by(id=msg.sender_participant_id).first()
        name = sender.pseudonym if sender else "Unknown"
        preview_md += f"{name}: {msg.text}\n"
    preview_md = f"```\n{preview_md}\n```"

    # ---- full TXT file ----
    txt = f"Chat history for room {room_id}\n\n"
    for msg in chat_history:
        sender = db.query(models.Participant).filter_by(id=msg.sender_participant_id).first()
        name = sender.pseudonym if sender else "Unknown"
        txt += f"{name}: {msg.text}\n\n"
    txt_bytes = BytesIO(txt.encode("utf-8"))
    txt_file = BufferedInputFile(txt_bytes.getvalue(), filename=f"chat_history_{room_id}.txt")

    # ---- create inline keyboard ----
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ Download TXT", callback_data=f"download_txt_{room_id}")],
        [InlineKeyboardButton(text="⬇️ Download Media Archive", callback_data=f"download_media_{room_id}")]
    ])

    await callback_query.message.answer_document(
        document=txt_file,
        caption=preview_md,
        parse_mode="Markdown",
        reply_markup=kb
    )
    db.close()


async def handle_download_txt(callback_query):
    room_id = int(callback_query.data.split('_')[-1])
    db = SessionLocal()
    msgs = db.query(models.Message).filter_by(room_id=room_id).all()
    txt = f"Chat history for room {room_id}\n\n"
    for m in msgs:
        sender = db.query(models.Participant).filter_by(id=m.sender_participant_id).first()
        name = sender.pseudonym if sender else "Unknown"
        txt += f"{name}: {m.text}\n\n"
    file_bytes = BytesIO(txt.encode("utf-8"))
    await callback_query.message.answer_document(
        document=BufferedInputFile(file_bytes.getvalue(), filename=f"chat_history_{room_id}.txt")
    )
    db.close()


async def handle_download_media(callback_query):
    room_id = int(callback_query.data.split('_')[-1])
    db = SessionLocal()
    msgs = db.query(models.Message).filter_by(room_id=room_id).all()

    if not msgs:
        await callback_query.message.answer("No messages found in this room.")
        db.close()
        return

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for m in msgs:
            if not m.media_key:
                continue

            # 🔑 Розшифровуємо збережене ім'я
            try:
                fernet = Fernet(settings.FERNET_KEY.encode())
                enc_name = os.path.basename(m.media_key)
                raw_name = fernet.decrypt(enc_name.encode()).decode()
            except Exception as e:
                print("Decrypt error:", e)
                continue

            file_path = os.path.join(MEDIA_ROOT, str(room_id), raw_name)
            if not os.path.isfile(file_path):
                continue

            # 👇 беремо ярлик з тексту, щоб збігалося з TXT
            label = None
            if m.text and m.text.startswith("[") and "]" in m.text:
                label = m.text.split()[0]

            if not label:
                label = os.path.splitext(raw_name)[0]

            ext = os.path.splitext(raw_name)[1]
            arcname = f"{label}{ext}"

            zf.write(file_path, arcname=arcname)

    db.close()

    if not zip_buffer.getbuffer().nbytes:
        await callback_query.message.answer("No media files found for this room.")
        return

    zip_buffer.seek(0)
    await callback_query.message.answer_document(
        document=BufferedInputFile(zip_buffer.getvalue(), filename=f"media_{room_id}.zip")
    )

# -----------------------
# Kick / Kick All
# -----------------------
async def cmd_kick(message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Kick participant", callback_data="kick_participant_menu")],
        [InlineKeyboardButton(text="🚨 Kick ALL from room", callback_data="kickall_menu")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
    ])
    await safe_edit_message(message, "🔨 Kick menu:", reply_markup=kb)


async def handle_kick_menu(callback: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    participants = db.query(models.Participant).all()
    if not participants:
        await safe_edit_message(callback.message, "📭 No participants found.")
        db.close()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for p in participants:
        room = db.query(models.ChatRoom).filter_by(id=p.room_id).first()
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{p.pseudonym} ({p.tag or '-'}) in {room.title if room else p.room_id}",
                callback_data=f"kick_participant_{p.id}"
            )
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")])
    db.close()

    await safe_edit_message(callback.message, "Select a participant to kick:", reply_markup=kb)



async def handle_kick_participant(callback: CallbackQuery):
    pid = int(callback.data.split('_')[-1])
    db = SessionLocal()
    p = db.query(models.Participant).filter_by(id=pid).first()
    if not p:
        await callback.message.answer("❌ Participant not found.")
        db.close()
        return
    room = db.query(models.ChatRoom).filter_by(id=p.room_id).first()
    text = f"Are you sure you want to remove '{p.pseudonym}' (tag={p.tag}) from room '{room.title}'?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm", callback_data=f"kick_confirm_{pid}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="back_main")]
    ])
    await safe_edit_message(callback.message, text, reply_markup=kb)
    db.close()


async def handle_kick_confirm(callback: CallbackQuery):
    pid = int(callback.data.split('_')[-1])
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{str(settings.BACKEND_URL).rstrip('/')}/admin/kick_participant/{pid}") as resp:
            if resp.status >= 400:
                j = await resp.json()
                await safe_edit_message(callback.message, f"❌ Error: {j.get('detail')}")
                return
    await safe_edit_message(callback.message, f"✅ Participant {pid} removed.", reply_markup=main_menu())


# Kick All
async def handle_kick_all(callback: CallbackQuery):
    db = SessionLocal()
    rooms = db.query(models.ChatRoom).all()
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for r in rooms:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"Room: {r.title}", callback_data=f"kickall_room_{r.id}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")])
    db.close()
    await safe_edit_message(callback.message, "Select room to kick all members:", reply_markup=kb)

async def handle_kickall_room(callback: CallbackQuery):
    room_id = int(callback.data.split('_')[-1])
    db = SessionLocal()
    room = db.query(models.ChatRoom).filter_by(id=room_id).first()
    db.close()

    if not room:
        await safe_edit_message(callback.message, "❌ Room not found.")
        return

    text = f"Are you sure you want to remove ALL participants from room '{room.title}'?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm", callback_data=f"kickall_confirm_{room_id}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="back_main")]
    ])
    await safe_edit_message(callback.message, text, reply_markup=kb)


async def handle_kickall_confirm(callback: CallbackQuery):
    room_id = int(callback.data.split('_')[-1])
    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/kick_all/{room_id}",
                timeout=15
            ) as resp:
                if resp.status >= 400:
                    try:
                        j = await resp.json()
                    except Exception:
                        j = {"detail": "Unknown error"}
                    await safe_edit_message(callback.message, f"❌ Error: {j.get('detail')}")
                    return
                result = await resp.json()
    except Exception as e:
        await safe_edit_message(callback.message, f"❌ Request failed: {e}")
        return

    await safe_edit_message(callback.message, f"✅ {result['status']}", reply_markup=main_menu())


# -----------------------
# Delete  / Delete All
# -----------------------
async def cmd_delete(message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Delete one message", callback_data="delete_one_menu")],
        [InlineKeyboardButton(text="🚮 Delete ALL from user", callback_data="deleteall_menu")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
    ])
    await safe_edit_message(message, "🗑 Delete menu:", reply_markup=kb)


async def handle_delete_one_menu(callback: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    rooms = db.query(models.ChatRoom).all()
    db.close()

    if not rooms:
        await safe_edit_message(callback.message, "📭 No rooms found.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for r in rooms:
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{r.title} (ID={r.id})",
                callback_data=f"delete_room_{r.id}_page_0"
            )
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="delete")])

    await safe_edit_message(callback.message, "Select a room:", reply_markup=kb)


PAGE_SIZE = 10

async def handle_delete_room(callback: CallbackQuery):
    parts = callback.data.split('_')
    room_id, page = int(parts[2]), int(parts[4])

    db = SessionLocal()
    try:
        # дістаємо кімнату (щоб показати title)
        room = db.query(models.ChatRoom).filter_by(id=room_id).first()
        msgs = (
            db.query(models.Message)
            .filter_by(room_id=room_id)
            .order_by(models.Message.id.desc())
            .all()
        )

        if not msgs:
            await safe_edit_message(callback.message, "📭 No messages in this room.")
            return

        start = page * PAGE_SIZE
        end = start + PAGE_SIZE
        page_msgs = msgs[start:end]

        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for m in page_msgs:
            # замість айді беремо псевдонім
            sender = db.query(models.Participant).filter_by(id=m.sender_participant_id).first()
            pseudonym = sender.pseudonym if sender else "Unknown"

            text_short = (m.text[:30] + "...") if m.text and len(m.text) > 30 else (m.text or "[media]")
            kb.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{pseudonym}: {text_short}",
                    callback_data=f"delete_msg_{m.id}"
                )
            ])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"delete_room_{room_id}_page_{page-1}"))
        if end < len(msgs):
            nav.append(InlineKeyboardButton(text="➡️ Next", callback_data=f"delete_room_{room_id}_page_{page+1}"))
        if nav:
            kb.inline_keyboard.append(nav)

        kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="delete_one_menu")])

        room_title = room.title if room else f"Room {room_id}"
        await safe_edit_message(
            callback.message,
            f"Select message (room *{room_title}*, page {page+1}):",
            reply_markup=kb
        )
    finally:
        db.close()

async def handle_delete_msg(callback: CallbackQuery):
    msg_id = int(callback.data.split('_')[-1])
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{str(settings.BACKEND_URL).rstrip('/')}/admin/delete_message/{msg_id}") as resp:
            if resp.status >= 400:
                j = await resp.json()
                await safe_edit_message(callback.message, f"❌ Error: {j.get('detail')}")
                return
    await safe_edit_message(callback.message, f"✅ Message {msg_id} deleted.", reply_markup=main_menu())


async def handle_deleteall_menu(callback: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    participants = db.query(models.Participant).all()
    if not participants:
        await safe_edit_message(callback.message, "📭 No participants found.")
        db.close()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for p in participants:
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{p.pseudonym} ({p.tg_user_id})",
                callback_data=f"deleteall_user_{p.id}"
            )
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="delete")])
    db.close()

    await safe_edit_message(callback.message, "Select a user to delete ALL their messages:", reply_markup=kb)

async def handle_deleteall_user(callback: CallbackQuery):
    pid = int(callback.data.split('_')[-1])
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{str(settings.BACKEND_URL).rstrip('/')}/admin/delete_all_user/{pid}") as resp:
            if resp.status >= 400:
                j = await resp.json()
                await safe_edit_message(callback.message, f"❌ Error: {j.get('detail')}")
                return
    await safe_edit_message(callback.message, f"✅ All messages from user {pid} deleted.", reply_markup=main_menu())

# -----------------------
# Bots Management
# -----------------------

async def cmd_bot_list(message: Message):
    db = SessionLocal()
    try:
        bots = db.query(models.Bot).all()
        if not bots:
            await safe_edit_message(
                message,
                escape_markdown("📋 Bot list is empty.")
            )
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[])

        for b in bots:
            kb.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"🤖 {b.username} ({b.tg_bot_id})",
                    callback_data=f"bot_detail_{b.id}"
                )
            ])

        kb.inline_keyboard.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")
        ])

        await safe_edit_message(
            message,
            escape_markdown("📋 Bot list:"),
            reply_markup=kb
        )
    finally:
        db.close()


async def handle_bot_detail(callback: CallbackQuery):
    bot_id = int(callback.data.split('_')[-1])
    db = SessionLocal()
    try:
        bot = db.query(models.Bot).filter_by(id=bot_id).first()
        if not bot:
            await safe_edit_message(callback.message, "❌ Bot not found.")
            return

        # HTML formatting
        text = (
            f"🤖 <b>Bot details:</b>\n\n"
            f"ID: <code>{bot.id}</code>\n"
            f"TG Bot ID: <code>{bot.tg_bot_id}</code>\n"
            f"Username: @{bot.username}\n"
            f"Mode: <code>{bot.mode}</code>\n"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Delete", callback_data=f"delete_bot_{bot.id}")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="bot_list")]
        ])

        await safe_edit_message(callback.message, text, reply_markup=kb, parse_mode="HTML")
    finally:
        db.close()

# -----------------------
# Team Invite Management
# -----------------------

async def start_invite_team(message: Message, state: FSMContext):
    db = SessionLocal()
    try:
        rooms = db.query(models.ChatRoom).all()
    finally:
        db.close()

    if not rooms:
        await message.answer("❌ No chat rooms found.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r.title, callback_data=f"invite_room_{r.id}")]
        for r in rooms
    ])
    await state.clear()
    await safe_edit_message(message, "Select a room to generate invites for:", reply_markup=kb)

# @router.callback_query(F.data.startswith("invite_room_"))
async def handle_invite_room(callback: CallbackQuery, state: FSMContext):
    room_id = int(callback.data.split("_")[-1])
    await state.update_data(room_id=room_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Generate randomly", callback_data="invite_team_generate")],
        [InlineKeyboardButton(text="✏️ Enter manually", callback_data="invite_team_manual")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
    ])
    await safe_edit_message(callback.message, "How would you like to create team invites?", reply_markup=kb)


# ---------------- Manual input ----------------
async def handle_invite_team_manual(callback: CallbackQuery, state: FSMContext):
    await safe_edit_message(
        callback.message,
        "✏️ Send pseudonyms separated by commas (example: Alice, Bob, Charlie).\n\n"
        "⚠️ Make sure the number of names matches the expected team size."
    )
    await state.set_state(TeamInviteStates.waiting_pseudonyms)


@router.message(StateFilter(TeamInviteStates.waiting_pseudonyms))
async def on_invite_team_input(message: Message, state: FSMContext):
    text = message.text.strip()
    pseudonyms = [p.strip() for p in text.split(",") if p.strip()]

    if not pseudonyms or len(pseudonyms) < 2:
        await message.answer("❌ Please enter at least 2 pseudonyms separated by commas.")
        return

    await generate_and_send_invites(message, pseudonyms, state)

# ---------------- Random generate ----------------
async def handle_invite_team_generate(callback: CallbackQuery, state: FSMContext):
    await safe_edit_message(
        callback.message,
        "How many random pseudonyms do you need? (enter a number, e.g. 5)"
    )
    await state.set_state(TeamInviteStates.waiting_count)


@router.message(StateFilter(TeamInviteStates.waiting_count))
async def on_invite_team_count(message: Message, state: FSMContext):
    try:
        count = int(message.text.strip())
        if count < 2 or count > 50:
            await message.answer("❌ Please enter a number between 2 and 50.")
            return
    except ValueError:
        await message.answer("❌ Invalid number. Please enter an integer.")
        return

    pseudonyms = []
    url = f"https://randomuser.me/api/?results={count}&nat=us"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for rec in data.get("results", []):
                        name = rec.get("name", {})
                        pseudonyms.append(f"{name.get('first','')} {name.get('last','')}")
    except Exception as e:
        logger.exception(f"Error fetching pseudonyms: {e}")

    if not pseudonyms:
        pseudonyms = [f"User{uuid.uuid4().hex[:6]}" for _ in range(count)]

    await generate_and_send_invites(message, pseudonyms, state)
    # ❌ не чистимо state тут

@router.message(StateFilter(TeamInviteStates.waiting_extend))
async def on_extend_input(message: Message, state: FSMContext):
    try:
        hours = int(message.text.strip())
        if hours <= 0 or hours > 168:
            await message.answer("❌ Please enter a number between 1 and 168.")
            return
    except ValueError:
        await message.answer("❌ Invalid number. Please enter an integer.")
        return

    data = await state.get_data()
    last_invites = data.get("last_invites", [])

    results = []
    errors = []

    async with aiohttp.ClientSession() as session:
        for code in last_invites:
            try:
                async with session.post(
                    f"{str(settings.BACKEND_URL).rstrip('/')}/admin/extend_invite",
                    json={"code": code, "hours": hours},
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        r = await resp.json()
                        results.append(r)
                    else:
                        try:
                            j = await resp.json()
                        except Exception:
                            j = {"detail": "Unknown error"}
                        errors.append(f"❌ Error extending {code}: {j.get('detail')}")
            except Exception as e:
                errors.append(f"⚠️ Error extending invite {code}: {e}")

    if not results and not errors:
        await message.answer("❌ No invites were extended.")
        await state.clear()
        return

    # ---- формуємо текст ----
    lines = []
    for r in results:
        exp = r.get("new_expires_at")
        lines.append(f"🔗 <code>{r['code']}</code> → expires at <b>{exp}</b>")

    text = ""
    if lines:
        text += "✅ Invites extended:\n\n" + "\n".join(lines)
    if errors:
        if text:
            text += "\n\n"
        text += "\n".join(errors)

    # ---- клавіатура ----
    if results:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Regenerate links", callback_data="invite_team_regen")],
            [InlineKeyboardButton(text="⏳ Extend life", callback_data="invite_team_extend")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
        ])

    await message.answer(text, parse_mode="HTML", reply_markup=kb)
    await state.clear()

# ---------------- Generate and send ----------------
async def generate_and_send_invites(
    message: Message,
    pseudonyms: list[str],
    state: FSMContext,
    regenerate: bool = False
):
    data = await state.get_data()
    room_id = data.get("room_id")
    if not room_id:
        await safe_edit_message(message, "❌ Room not selected. Start again.")
        return

    # Якщо регенерація → інвалідимо старі інвайти
    if regenerate:
        async with aiohttp.ClientSession() as session:
            try:
                await session.post(
                    f"{str(settings.BACKEND_URL).rstrip('/')}/admin/invalidate_invites",
                    json={"room_id": room_id, "pseudonyms": pseudonyms},
                    timeout=10
                )
            except Exception as e:
                logger.warning(f"⚠️ Could not invalidate old invites: {e}")

    # Тягнемо bot.username з бекенду
    bot_username = None
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/room/{room_id}",
                timeout=10
            ) as resp:
                if resp.status == 200:
                    room_info = await resp.json()
                    bot_username = room_info.get("bot_username")
        except Exception as e:
            await safe_edit_message(message, f"⚠️ Error fetching room info: {e}")
            return

    if not bot_username:
        await safe_edit_message(message, "❌ Could not fetch bot username for this room.")
        return

    invites_info = []
    errors = []

    async with aiohttp.ClientSession() as session:
        for pseudonym in pseudonyms:
            try:
                async with session.post(
                    f"{str(settings.BACKEND_URL).rstrip('/')}/admin/generate_invite",
                    json={"room_id": room_id, "pseudonym": pseudonym},
                    timeout=10
                ) as resp:
                    if resp.status >= 400:
                        try:
                            j = await resp.json()
                        except Exception:
                            j = {"detail": "Unknown error"}
                        errors.append(f"❌ Error for {pseudonym}: {j.get('detail')}")
                        continue
                    result = await resp.json()
                    link = f"https://t.me/{bot_username}?start={result['code']}"
                    invites_info.append((pseudonym, link))
            except Exception as e:
                errors.append(f"⚠️ Error while generating invite for {pseudonym}: {e}")
                continue

    # Формуємо текст
    if not invites_info:
        text = "❌ No invites were generated."
    else:
        lines = [f"👤 {p}: <a href='{link}'>{link}</a>" for p, link in invites_info]
        text = (
            "📤 <b>Team invites generated:</b>\n\n"
            + "\n".join(lines)
            + "\n\n⚠️ Each link is single-use and expires in 1 hour."
        )

    if errors:
        text += "\n\n" + "\n".join(errors)

    # ---- клавіатура ----
    if invites_info:
        # Зберігаємо останні дані в FSM
        await state.update_data(
            last_pseudonyms=[p for p, _ in invites_info],
            last_invites=[link.split("start=")[-1] for _, link in invites_info],
            room_id=room_id
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Regenerate links", callback_data="invite_team_regen")],
            [InlineKeyboardButton(text="⏳ Extend life", callback_data="invite_team_extend")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
        ])

    await safe_edit_message(message, text, reply_markup=kb, parse_mode="HTML")


async def handle_regenerate(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pseudonyms = data.get("last_pseudonyms", [])
    if not pseudonyms:
        await safe_edit_message(callback.message, "❌ No pseudonyms to regenerate.")
        return

    await generate_and_send_invites(callback.message, pseudonyms, state, regenerate=True)

async def handle_extend(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    last_invites = data.get("last_invites", [])
    if not last_invites:
        await safe_edit_message(callback.message, "❌ No active invites to extend.")
        await callback.answer()
        return

    await safe_edit_message(
        callback.message,
        "⏳ How many hours do you want to extend invites?\n(enter a number, e.g. 2)"
    )
    await state.set_state(TeamInviteStates.waiting_extend)
    await callback.answer()


# -----------------------
# Admin Push
# -----------------------

async def handle_admin_push(callback: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    rooms = db.query(models.ChatRoom).all()
    db.close()

    if not rooms:
        await safe_edit_message(callback.message, "❌ No chat rooms found.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r.title, callback_data=f"push_room_{r.id}")]
        for r in rooms
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")])

    await state.set_state(AdminPushStates.waiting_room)
    await safe_edit_message(callback.message, "📢 Select a room for push:", reply_markup=kb)


async def handle_push_room(callback: CallbackQuery, state: FSMContext):
    room_id = int(callback.data.split("_")[-1])
    await state.update_data(room_id=room_id)

    await state.set_state(AdminPushStates.waiting_text)
    await safe_edit_message(callback.message, "✏️ Enter the text to send as admin push:")
    await callback.answer()


async def handle_push_text(message: Message, state: FSMContext):
    data = await state.get_data()
    room_id = data.get("room_id")
    text = message.text.strip()

    if not text:
        await message.answer("❌ Text cannot be empty.")
        return

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/push_message",
                json={"room_id": room_id, "text": text}
            )
        await message.answer(f"✅ Push sent to room {room_id}")
    except Exception as e:
        await message.answer(f"⚠️ Failed to send push: {e}")

    await state.clear()


# -----------------------
# Link Group
# -----------------------
async def cmd_link_group(message: Message, state: FSMContext):
    db = SessionLocal()
    rooms = db.query(models.ChatRoom).all()
    db.close()

    if not rooms:
        await safe_edit_message(message, "❌ No chat rooms found.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r.title, callback_data=f"linkgroup_room_{r.id}")]
        for r in rooms
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")])

    await state.set_state(LinkGroupStates.waiting_room)
    await safe_edit_message(message, "🔗 Select a room to link the group:", reply_markup=kb)

async def handle_linkgroup_room(callback: CallbackQuery, state: FSMContext):
    room_id = int(callback.data.split("_")[-1])
    await state.update_data(room_id=room_id)
    await state.set_state(LinkGroupStates.waiting_group_id)
    await safe_edit_message(
        callback.message,
        "✏️ Please send the *group_id*."
    )
    await callback.answer()

async def handle_linkgroup_groupid(message: Message, state: FSMContext):
    data = await state.get_data()
    room_id = data.get("room_id")

    try:
        tg_group_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid group id, please enter a number.")
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/link_group",
                json={"room_id": room_id, "tg_group_id": tg_group_id},
                timeout=10
            ) as resp:
                if resp.status >= 400:
                    try:
                        j = await resp.json()
                    except Exception:
                        j = {"detail": "Unknown error"}
                    await message.answer(f"❌ Failed to link group: {j.get('detail')}")
                    return
                result = await resp.json()
    except Exception as e:
        await message.answer(f"⚠️ Error linking group: {e}")
        return

    await message.answer(
        f"✅ Group successfully linked!\nRoom: {result['room_title']}\nGroup ID: {result['tg_group_id']}"
    )
    await state.clear()

# -----------------------
# Router
# -----------------------

async def inline_router(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    logger.info(f"Callback data: {data}")

    # Auth & bot mgmt
    if data == "auth":
        await cmd_auth(callback.message, state)
    elif data == "new_bot":
        await cmd_new_bot(callback.message, state)
    elif data == "start_bot":
        await cmd_start_bot(callback.message)
    elif data.startswith("start_bot_"):
        await handle_start_bot(callback)
    elif data == "bot_list":
        await cmd_bot_list(callback.message)
    elif data.startswith("bot_detail_"):
        await handle_bot_detail(callback)
    elif data == "delete_bot":
        await safe_edit_message(callback.message, escape_markdown("❌ Delete bot (not implemented yet)."))

    # Chat mgmt
    elif data == "create_chat":
        await cmd_create_chat(callback.message, state)
    elif data.startswith("choose_bot_"):
        await handle_choose_bot(callback, state)


    # Single invite
    elif data == "invite":
        await cmd_invite(callback.message, state)
    elif data.startswith("invite_user_"):
        await handle_invite_user(callback, state)


    # Team invite
    elif data == "invite_team":
        await start_invite_team(callback.message, state)
    elif data.startswith("invite_room_"):
        await handle_invite_room(callback, state)
    elif data == "invite_team_manual":
        await handle_invite_team_manual(callback, state)
    elif data == "invite_team_generate":
        await handle_invite_team_generate(callback, state)
    elif data == "invite_team_regen":
        await handle_regenerate(callback, state)
    elif data == "invite_team_extend":
        await handle_extend(callback, state)

    # Members mgmt
    elif data == "members":
        await cmd_members(callback.message, state)
    elif data.startswith("members_"):
        await handle_members_menu(callback, state)
    # Members remove
    elif data.startswith("members_remove_"):
        await render_members_menu(callback.message)




    # Kick
    elif data == "kick":
        await cmd_kick(callback.message, state)
    elif data == "kick_participant_menu":
        await handle_kick_menu(callback, state)
    elif data == "kickall_menu":
        await handle_kick_all(callback)
    elif data == "kickall":
        await handle_kick_all(callback)
    elif data.startswith("kick_participant_"):
        await handle_kick_participant(callback)
    elif data.startswith("kick_confirm_"):
        await handle_kick_confirm(callback)
    elif data.startswith("kickall_room_"):
        await handle_kickall_room(callback)
    elif data.startswith("kickall_confirm_"):
        await handle_kickall_confirm(callback)

    # Chats history
    elif data == "show_chat_rooms":
        await safe_edit_message(callback.message, "Processing show chat rooms...")
        await show_chat_rooms(callback.message)
    elif data.startswith("chat_history_"):
        await safe_edit_message(callback.message, "Fetching chat history...")
        await handle_chat_history(callback, state)
    elif data.startswith("download_txt_"):
        await handle_download_txt(callback)
    elif data.startswith("download_media_"):
        await handle_download_media(callback)

    # Navigation
    elif data == "back_main":
        await safe_edit_message(
            callback.message,
            escape_markdown("🏠 Main menu:"),
            reply_markup=main_menu()
        )
    elif data == "back_kick":
        await handle_kick_menu(callback, state)
    elif data == "back_history":
        await show_chat_rooms(callback.message)
    elif data == "back_members":
        await render_members_menu(callback.message)

    # Deletion
    elif data == "delete_msm":
        await cmd_delete(callback.message, state)
    elif data == "delete_one_menu":
        await handle_delete_one_menu(callback, state)
    elif data.startswith("delete_msg_"):
        await handle_delete_msg(callback)
    elif data == "deleteall_menu":
        await handle_deleteall_menu(callback, state)
    elif data.startswith("deleteall_user_"):
        await handle_deleteall_user(callback)
    elif data.startswith("delete_room_"):
        await handle_delete_room(callback)

    # Link group
    elif data == "link_group":
        await cmd_link_group(callback.message, state)
    elif data.startswith("linkgroup_room_"):
        await handle_linkgroup_room(callback, state)

    await callback.answer()
