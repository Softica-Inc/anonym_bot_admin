# main.py
import asyncio

from fastapi import FastAPI
from database import Base, engine, get_db
import admin as admin_router
import webhook as webhook_router
from pathlib import Path
from dotenv import load_dotenv
import os

# Explicitly specify the .env file path
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Create tables (for dev)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AnonChat Backend")
app.include_router(admin_router.router)


@app.on_event("startup")
async def startup_event():
    from admin import active_bots

    db = next(get_db())  # Беремо з бази даних
    await admin_router.load_bots(db)  # Завантажуємо ботів
    asyncio.create_task(webhook_router.listen_fanout())  # Слухаємо для повідомлень

    # Запуск polling для всіх ботів
    print("Запускаємо polling для всіх ботів")
    for bot_data in admin_router.bot_dispatchers.values():
        bot = bot_data["bot"]
        dp = bot_data["dp"]
        tg_bot_id = str(bot_data["tg_bot_id"])  # 👈 приводимо до str

        # Перевірка, чи не запускається polling для цього бота
        if tg_bot_id not in active_bots:
            print(f"Starting polling for bot {tg_bot_id}")
            active_bots[tg_bot_id] = True  # Позначаємо бота як активного
            asyncio.create_task(dp.start_polling(bot))  # Стартуємо polling
        else:
            print(f"Bot {tg_bot_id} is already running. Skipping polling.")



# app.include_router(webhook_router.router)