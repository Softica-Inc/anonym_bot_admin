# admin_bot/utils.py
import aiohttp
from typing import Optional
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from aiolimiter import AsyncLimiter

import models

rate_limit = AsyncLimiter(30, 1)

async def validate_telegram_token(token: str) -> Optional[dict]:
    async with rate_limit:
        url = f"https://api.telegram.org/bot{token}/getMe"
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(url) as resp:
                    j = await resp.json()
            except Exception:
                return None
        if not j.get('ok'):
            return None
        return j['result']


async def register_token_to_backend(backend_url: str, token: str, mode: str, owner_tg_id: int) -> dict:
    """POST /admin/register_bot на бекенд. Повертає JSON від бекенду або піднімає Exception."""
    payload = {"token": token, "mode": mode, "owner_tg_ids": [owner_tg_id]}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{str(backend_url).rstrip('/')}/admin/register_bot", json=payload) as resp:
            text = await resp.text()
            try:
                j = await resp.json()
            except Exception:
                raise RuntimeError(f"Backend returned non-json: {resp.status} {text}")
            if resp.status >= 400:
                raise RuntimeError(j.get('detail') or j)
            return j


def escape_markdown(text: str) -> str:
    """
    Екранує спецсимволи для MarkdownV2.
    """
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join("\\" + c if c in escape_chars else c for c in text)


async def safe_edit_message(message, text, reply_markup=None, parse_mode=None):
    try:
        return await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


def format_chat_history(chat_history, db, limit: int = 40) -> str:
    """
    Formats chat history as MarkdownV2 code block with spacing.
    Shows last `limit` messages. If more exist, adds a footer.
    """
    lines = []
    count = len(chat_history)
    display_messages = chat_history[-limit:]  # last N messages

    for msg in display_messages:
        sender = db.query(models.Participant).filter_by(id=msg.sender_participant_id).first()
        pseudonym = sender.pseudonym if sender else "Unknown"
        # add spacing between messages
        lines.append(f"{pseudonym}: {msg.text}\n")

    formatted = "\n".join(lines)

    if count > limit:
        formatted += f"\n...more messages in history"

    return f"```\n{formatted}\n```"

# Приклад значення (локально):
# mysql+pymysql://anon:anonpass@127.0.0.1:3306/anon
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:root@127.0.0.1:3306/anon")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
