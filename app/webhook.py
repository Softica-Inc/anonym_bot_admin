# app/webhook.py
import os

from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.orm import Session
import asyncio
import json
from datetime import datetime
from aiolimiter import AsyncLimiter
import redis.asyncio as redis

from app.database import get_db
from app import crud, models
from app.utils import get_decrypted_token

router = APIRouter(prefix="/webhook", tags=["webhook"])

bot_dispatchers = {}
rate_limit = AsyncLimiter(30, 1)  # 30 msg/sec
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

async def load_bots(db: Session):
    all_bots = db.query(models.Bot).all()
    for bot_model in all_bots:
        token = get_decrypted_token(bot_model.token_encrypted)
        bot = Bot(token=token)
        dp = Dispatcher(storage=MemoryStorage())
        dp.message.register(handle_message)
        dp.message.register(handle_start)
        dp.edited_message.register(handle_edit)
        # dp.callback_query.register(handle_delete)  # Для delete, якщо через inline
        bot_dispatchers[bot_model.tg_bot_id] = {'bot': bot, 'dp': dp, 'mode': bot_model.mode}

@router.on_event("startup")
async def startup():
    db = next(get_db())
    await load_bots(db)
    asyncio.create_task(listen_fanout())

@router.post("/{tg_bot_id}")
async def process_webhook(tg_bot_id: int, request: Request, db: Session = Depends(get_db)):
    update = await request.json()
    bot_data = bot_dispatchers.get(tg_bot_id)
    if not bot_data:
        raise HTTPException(status_code=404, detail="Bot not found")
    bot = bot_data['bot']
    dp = bot_data['dp']
    await dp.feed_update(bot, types.Update(**update))
    return {"ok": True}

# Хендлер /start з deep link
async def handle_start(message: types.Message):
    bot = message.bot
    db = next(get_db())
    code = message.text.split()[-1] if message.text.startswith('/start ') else None
    if not code:
        await message.answer("Вітаю! Почніть з інвайт-лінку.")
        return
    invite = db.query(models.InviteLink).filter(models.InviteLink.code == code).first()
    if not invite or invite.used or invite.expires_at < datetime.utcnow():
        await message.answer("Інвайт недійсний або прострочений.")
        return
    # Збір даних користувача (анонімно, тільки tg_id для відправки)
    participant = crud.create_participant(db, invite.room_id, message.from_user.id, invite.pseudonym, invite.tag)
    invite.used = True
    db.commit()
    # Системне повідомлення
    await redis_client.publish(f"fanout:{invite.room_id}", json.dumps({
        "bot_id": bot.id,
        "room_id": invite.room_id,
        "text": f"[Система] {invite.pseudonym} приєднався.",
        "is_system": True
    }))
    await message.answer(f"Ви приєдналися як {invite.pseudonym}. Почніть спілкування!")

# Хендлер повідомлень
async def handle_message(message: types.Message):
    bot = message.bot
    db = next(get_db())
    participant = crud.get_participant_by_tg_id(db, message.from_user.id, None)  # Знайти room по tg_id
    if not participant:
        await message.answer("Ви не в чаті.")
        return
    content_type = 'text'
    text = message.text
    media_key = None
    # Обробка медіа (заглушка для S3)
    if message.photo:
        content_type = 'photo'
        # Завантажити в S3, media_key = upload_to_s3(message.photo[-1].file_id)
        pass  # Додати boto3
    # Збереження
    msg = crud.create_message(db, participant.room_id, participant.id, text, content_type, media_key)
    # Підпис
    signed_text = f"[{participant.pseudonym}{f' ({participant.tag})' if participant.tag else ''}]: {text}"
    await redis_client.publish(f"fanout:{participant.room_id}", json.dumps({
        "bot_id": bot.id,
        "room_id": participant.room_id,
        "text": signed_text,
        "original_msg_id": msg.id,
        "sender_id": participant.id,
        "content_type": content_type,
        "media_key": media_key
    }))

# Хендлер edit
async def handle_edit(edited_message: types.Message):
    bot = edited_message.bot
    db = next(get_db())
    participant = crud.get_participant_by_tg_id(db, edited_message.from_user.id, None)
    if not participant:
        return
    # Знайти original по tg_message_id (з MessageCopy для sender)
    copies = crud.get_message_copies(db, None)  # Потрібно шукати по tg_id
    # Оновити text з (ред.)
    # Фан-аут edit
    await redis_client.publish(f"fanout:{participant.room_id}", json.dumps({
        "bot_id": bot.id,
        "room_id": participant.room_id,
        "edit": True,
        "original_msg_id": 0,  # Знайти
        "new_text": f"{edited_message.text} (ред.)"
    }))

# Слухач черги для фан-ауту
async def listen_fanout():
    pubsub = redis_client.pubsub()
    await pubsub.psubscribe("fanout:*")
    async for msg in pubsub.listen():
        if msg['type'] == 'pmessage':
            data = json.loads(msg['data'])
            bot_id = data['bot_id']
            bot_data = next((v for k, v in bot_dispatchers.items() if k == bot_id), None)
            if not bot_data:
                continue
            bot = bot_data['bot']
            db = next(get_db())
            participants = crud.get_participants(db, data['room_id'])
            for p in participants:
                if not data.get('is_system') and p.id == data.get('sender_id'):
                    continue
                async with rate_limit:
                    if data.get('edit'):
                        # Edit message у recipient_tg_message_id
                        copies = crud.get_message_copies(db, data['original_msg_id'])
                        for copy in copies:
                            if copy.recipient_participant_id == p.id:
                                await bot.edit_message_text(chat_id=p.tg_user_id, message_id=copy.recipient_tg_message_id, text=data['new_text'])
                    else:
                        sent = await bot.send_message(p.tg_user_id, data['text'])
                        crud.create_message_copy(db, data['original_msg_id'], p.id, sent.message_id)
            db.commit()