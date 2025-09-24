# main.py
from fastapi import FastAPI
from app.database import Base, engine
from app import admin as admin_router
from app import webhook as webhook_router
from pathlib import Path
from dotenv import load_dotenv

# шукаємо .env у тій самій папці, що й main.py
load_dotenv(Path(__file__).resolve().parent / ".env")


# створити таблиці (для dev)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AnonChat Backend")

app.include_router(admin_router.router)
app.include_router(webhook_router.router)