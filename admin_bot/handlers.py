# admin_bot/handlers.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiohttp
import logging
from aiogram import Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from config import settings
from utils import validate_telegram_token, register_token_to_backend
from aiogram.types import CallbackQuery
from sqlalchemy.orm import sessionmaker
from app.database import engine
from app import models
from app.database import SessionLocal
from app.models import ChatRoom, Bot

logging.basicConfig(level=logging.INFO)
SessionLocal = sessionmaker(bind=engine)


class NewBotStates(StatesGroup):
    waiting_token = State()
    waiting_mode = State()
    waiting_chat_details = State()
    waiting_invite_details = State()

class AuthStates(StatesGroup):
    waiting_password = State()

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

async def inline_router(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "new_bot":
        await cmd_new_bot(callback.message, state)
    elif data == "create_chat":
        await cmd_create_chat(callback.message, state)
    elif data == "invite":
        await cmd_invite(callback.message, state)
    elif data == "cancel":
        await cmd_cancel(callback.message, state)
    elif data == "auth":
        await cmd_auth(callback.message, state)
    await callback.answer()  # щоб зник індикатор «…»

async def cmd_start(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новий бот", callback_data="new_bot")],
        [InlineKeyboardButton(text="💬 Створити чат", callback_data="create_chat")],
        [InlineKeyboardButton(text="🔗 Запрошення", callback_data="invite")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel")],
        [InlineKeyboardButton(text="🔑 Авторизація", callback_data="auth")]
    ])
    await message.answer(
        "Привіт! Оберіть дію:",
        reply_markup=kb
    )

async def cmd_new_bot(message: Message, state: FSMContext):
    if not await check_admin_permissions(message):
        return
    await state.set_state(NewBotStates.waiting_token)
    await message.answer(
        "Надішліть, будь ласка, токен бота (отриманий від @BotFather).\n"
        "Формат: 123456:ABC-DEF..."
    )

async def handle_token(message: Message, state: FSMContext):
    token = message.text.strip()
    await message.answer("Перевіряю токен...")
    info = await validate_telegram_token(token)
    if not info:
        await message.answer("Токен недійсний або не відповідає Telegram API. Спробуйте ще раз або перевірте токен.")
        return
    await state.update_data(token=token, username=info['username'])
    await state.set_state(NewBotStates.waiting_mode)
    await message.answer("Виберіть режим роботи бота: 'single' (один бот для багатьох чатів) або 'multi' (окремий бот для кожного чату).")

async def handle_mode(message: Message, state: FSMContext):
    mode = message.text.strip().lower()
    if mode not in ["single", "multi"]:
        await message.answer("Невірний режим. Виберіть 'single' або 'multi'.")
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
        # Надіслати команду "запустити" бота на бекенді
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/start_bot",
                json={"bot_id": result['id'], "owner_tg_id": message.from_user.id}
            ) as resp:
                if resp.status >= 400:
                    j = await resp.json()
                    await message.answer(f"Помилка запуску бота: {j.get('detail', 'Unknown error')}")
                    return
                start_result = await resp.json()
        await message.answer(f"Бот успішно зареєстровано та запущено: {result['username']} (id={result['tg_bot_id']}), режим: {result['mode']}\nСтатус запуску: {start_result.get('status')}")
    except Exception as e:
        logging.error(f"Error in registration or start: {e}")
        await message.answer(f"Виникла помилка при реєстрації або запуску. Спробуйте пізніше.")
        return
    await state.clear()

async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операцію скасовано.")

async def cmd_create_chat(message: Message, state: FSMContext):
    if not await check_admin_permissions(message):
        return
    await state.set_state(NewBotStates.waiting_chat_details)
    await message.answer(
        "Введіть ID бота та назву чату (формат: &lt;bot_id&gt; &lt;title&gt;)"
    )


async def handle_chat_details(message: Message, state: FSMContext):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Невірний формат. Введіть: <bot_id> <title>")
        return
    bot_id, title = parts
    try:
        bot_id = int(bot_id)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/create_chat",
                json={"bot_id": bot_id, "title": title}
            ) as resp:
                if resp.status >= 400:
                    j = await resp.json()
                    await message.answer(f"Помилка створення чату: {j.get('detail', 'Unknown error')}")
                    return
                result = await resp.json()
        await message.answer(f"Чат створено: {result['title']} (id={result['id']})")
    except Exception as e:
        logging.error(f"Error creating chat: {e}")
        await message.answer(f"Виникла помилка при створенні чату.")
    await state.clear()

async def cmd_invite(message: Message, state: FSMContext):
    if not await check_admin_permissions(message):
        return
    await state.set_state(NewBotStates.waiting_invite_details)
    await message.answer(
        "Введіть ID чату, псевдонім та тег (формат: &lt;room_id&gt; &lt;pseudonym&gt; [tag])"
    )




async def handle_invite_details(message: Message, state: FSMContext):
    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Невірний формат. Введіть: <room_id> <pseudonym> [tag]")
        return
    room_id, pseudonym = parts[:2]
    tag = parts[2] if len(parts) > 2 else None
    try:
        room_id = int(room_id)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{str(settings.BACKEND_URL).rstrip('/')}/admin/generate_invite",
                json={"room_id": room_id, "pseudonym": pseudonym, "tag": tag}
            ) as resp:
                if resp.status >= 400:
                    j = await resp.json()
                    await message.answer(f"Помилка створення посилання: {j.get('detail', 'Unknown error')}")
                    return
                result = await resp.json()

        # --- ОТРИМУЄМО USERNAME БОТА ЧЕРЕЗ БД ---
        db = SessionLocal()
        try:
            room = db.query(ChatRoom).filter_by(id=room_id).first()
            bot  = db.query(Bot).filter_by(id=room.bot_id).first()
            username = bot.username       # <-- справжній username бота
        finally:
            db.close()

        link = f"https://t.me/{username}?start={result['code']}"
        await message.answer(
            f"Посилання створено: {link}\n"
            f"Псевдонім: {result['pseudonym']}\n"
            f"Тег: {result['tag']}"
        )
    except Exception as e:
        logging.error(f"Error generating invite: {e}")
        await message.answer("Виникла помилка при створенні посилання.")
    await state.clear()


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
