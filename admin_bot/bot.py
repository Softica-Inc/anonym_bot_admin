# admin_bot/bot.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from config import settings
from handlers import cmd_start, cmd_new_bot, handle_token, handle_mode, cmd_cancel, NewBotStates, cmd_create_chat, \
    handle_chat_details, cmd_invite, handle_invite_details, cmd_auth, handle_password, AuthStates, inline_router


async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
    dp = Dispatcher(storage=MemoryStorage())

    # Register handlers
    dp.message.register(cmd_start, Command(commands=['start']))
    dp.message.register(cmd_new_bot, Command(commands=['new_bot']))
    dp.message.register(cmd_cancel, Command(commands=['cancel']))
    dp.message.register(handle_token, NewBotStates.waiting_token)
    dp.message.register(handle_mode, NewBotStates.waiting_mode)
    dp.message.register(cmd_create_chat, Command(commands=['create_chat']))
    dp.message.register(handle_chat_details, NewBotStates.waiting_chat_details)
    dp.message.register(cmd_invite, Command(commands=['invite']))
    dp.message.register(handle_invite_details, NewBotStates.waiting_invite_details)
    dp.message.register(cmd_auth, Command(commands=['auth']))
    dp.message.register(handle_password, AuthStates.waiting_password)
    dp.callback_query.register(inline_router)

    await bot.set_my_commands([
        BotCommand(command='start', description='Start admin bot'),
        BotCommand(command='new_bot', description='Register new bot token'),
        BotCommand(command='create_chat', description='Create a new chat room'),
        BotCommand(command='invite', description='Generate invite link'),
        BotCommand(command='cancel', description='Cancel operation'),
        BotCommand(command='auth', description='Authenticate as admin'),
    ])

    # menu = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    #     [KeyboardButton(text="/new_bot"), KeyboardButton(text="/create_chat")],
    #     [KeyboardButton(text="/invite"), KeyboardButton(text="/cancel")]
    # ])
    # await bot.set_chat_menu_button(menu_button=menu)

    print('Starting admin bot (polling) ...')
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())