# chat_bot/bot.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from config import settings

async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
    dp = Dispatcher(storage=MemoryStorage())

    # Register handlers (to be implemented)
    dp.message.register(cmd_start, CommandStart())

    await bot.set_my_commands([
        BotCommand(command='start', description='Join chat with invite code'),
    ])

    print('Starting chat bot (polling) ...')
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())