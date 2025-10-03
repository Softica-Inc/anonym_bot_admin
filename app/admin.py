# app/admin.py
import asyncio
import os
import httpx
from aiogram.enums import ChatType
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet
from typing import List
import uuid
from datetime import datetime, timedelta
import json
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database import get_db
import crud, schemas, models
from utils import get_decrypted_token
from webhook import handle_message, handle_start, handle_edit, redis_client, handle_reaction, handle_delete_command
from aiogram.filters import CommandStart
from aiogram.filters import Command
from aiogram import types

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.enums.chat_type import ChatType
from aiogram import types

load_dotenv()
# Словник для збереження стану, чи працює polling для бота
active_bots: dict[str, bool] = {}  # 👈 ключі тільки str

router = APIRouter(prefix="/admin", tags=["admin"])
TELEGRAM_API = "https://api.telegram.org"
MAX_BOTS_PER_ADMIN = int(os.getenv("MAX_BOTS_PER_ADMIN", 10))  # Configurable limit

fernet = Fernet(settings.FERNET_KEY.encode())

bot_dispatchers = {}
bots_loaded = False

async def load_bots(db: Session):
    if getattr(load_bots, "_loaded", False):
        print("⚠️ load_bots вже викликано, пропускаємо")
        return
    load_bots._loaded = True

    all_bots = db.query(models.Bot).all()
    for bot_model in all_bots:
        token = get_decrypted_token(bot_model.token_encrypted)
        bot = Bot(token=token)
        dp = Dispatcher(storage=MemoryStorage())

        dp.message.register(handle_start, CommandStart())
        dp.message.register(handle_delete_command, Command("delete"))

        dp.message.register(handle_message)
        dp.edited_message.register(handle_edit)
        dp.message_reaction.register(handle_reaction)
        dp.message.register(handle_group_message, F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

        print(f"✅ Loaded bot with tg_bot_id: {bot_model.tg_bot_id}, mode: {bot_model.mode}")

        tg_bot_id_str = str(bot_model.tg_bot_id)
        bot_dispatchers[tg_bot_id_str] = {
            "bot": bot,
            "dp": dp,
            "mode": bot_model.mode,
            "tg_bot_id": tg_bot_id_str,
        }

async def handle_group_message(message: types.Message):
    db = next(get_db())

    group = db.query(models.Group).filter_by(tg_group_id=message.chat.id).first()
    if not group:
        return  # ця група не прив'язана

    room = crud.get_chat_room(db, group.room_id)
    if not room:
        return

    participant = (
        db.query(models.Participant)
        .filter_by(room_id=room.id, tg_user_id=message.from_user.id, group_id=group.id)
        .first()
    )
    if not participant:
        pseudonym = message.from_user.first_name or str(message.from_user.id)
        participant = models.Participant(
            room_id=room.id,
            tg_user_id=message.from_user.id,
            pseudonym=pseudonym,
            group_id=group.id,
        )
        db.add(participant)
        db.commit()
        db.refresh(participant)

    text = message.text or ""
    signed_text = f"[Group {group.title}][{participant.pseudonym}]: {text}"

    await redis_client.publish(
        f"fanout:{room.id}",
        json.dumps({
            "bot_id": str(room.bot.tg_bot_id),
            "room_id": room.id,
            "text": signed_text,
            "original_msg_id": None,
            "sender_id": participant.id,
            "content_type": "text",
            "is_system": False,
        }),
    )


@router.post("/register_bot", response_model=schemas.BotResponse)
async def register_bot(data: schemas.BotRegisterRequest, db: Session = Depends(get_db)):
    token = data.token.strip()
    owner_tg_ids = data.owner_tg_ids or [0]  # Default to 0 if no owners specified
    mode = data.mode

    # Validate mode
    if mode not in ["single", "multi"]:
        raise HTTPException(status_code=400, detail="Mode must be 'single' or 'multi'")

    # Check bot limit per admin (assuming first owner_tg_id is the creator)
    if owner_tg_ids[0] != 0:
        bot_count = db.query(models.Bot).filter(models.Bot.owners.contains(json.dumps([owner_tg_ids[0]]))).count()
        if bot_count >= MAX_BOTS_PER_ADMIN:
            raise HTTPException(status_code=400, detail="Bot limit reached for this admin")

    # Validate token via Telegram getMe
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{TELEGRAM_API}/bot{token}/getMe")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Telegram API: {exc}")

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Invalid token or Telegram API error")

    j = resp.json()
    if not j.get("ok"):
        raise HTTPException(status_code=400, detail="Invalid token (Telegram returned not ok)")

    tg_bot_id = j["result"]["id"]
    username = j["result"].get("username") or j["result"].get("first_name") or f"bot_{tg_bot_id}"

    # Check existing bot by tg_bot_id
    existing = db.query(models.Bot).filter(models.Bot.tg_bot_id == tg_bot_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bot already exists")

    # Encrypt token
    token_encrypted = fernet.encrypt(token.encode()).decode()

    # Create bot in DB
    bot = models.Bot(
        tg_bot_id=tg_bot_id,
        username=username,
        token_encrypted=token_encrypted,
        mode=mode,
        owners=json.dumps(owner_tg_ids)
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)

    # === ДОДАЄМО БОТА В bot_dispatchers, щоб не чекати reload ===
    try:
        decrypted_token = get_decrypted_token(bot.token_encrypted)
        new_bot = Bot(token=decrypted_token)
        dp = Dispatcher(storage=MemoryStorage())

        # реєструємо хендлери
        dp.message.register(handle_start, CommandStart())
        dp.message.register(handle_delete_command, Command("delete"))
        dp.message.register(handle_message)
        dp.edited_message.register(handle_edit)
        dp.message_reaction.register(handle_reaction)

        bot_dispatchers[str(bot.tg_bot_id)] = {
            "bot": new_bot,
            "dp": dp,
            "mode": bot.mode,
            "tg_bot_id": str(bot.tg_bot_id),
        }

        print(f"✅ New bot initialized in memory: {bot.username} ({bot.tg_bot_id})")
    except Exception as e:
        print(f"⚠️ Failed to initialize dispatcher for new bot {bot.tg_bot_id}: {e}")

    crud.create_audit_log(
        db,
        bot_id=bot.id,
        actor_tg_id=owner_tg_ids[0],
        action="register_bot",
        payload={"mode": mode}
    )

    return schemas.BotResponse(
        id=bot.id,
        tg_bot_id=bot.tg_bot_id,
        username=bot.username,
        mode=bot.mode,
        owners=owner_tg_ids,
        created_at=bot.created_at.isoformat()
    )


@router.post("/start_bot", response_model=dict)
async def start_bot(data: dict, db: Session = Depends(get_db)):
    bot_id = data.get('bot_id')
    if not bot_id:
        raise HTTPException(status_code=400, detail="Missing bot_id")

    bot = crud.get_bot_by_id(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    tg_bot_id_str = str(bot.tg_bot_id)

    # --- Якщо бот вже запущений → стопаємо полінг
    if tg_bot_id_str in active_bots:
        bot_data = bot_dispatchers.get(tg_bot_id_str)
        if bot_data and "task" in bot_data:
            task = bot_data["task"]
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    print(f"🛑 Bot {tg_bot_id_str} polling stopped")
        active_bots.pop(tg_bot_id_str, None)

    # --- Додаємо в active_bots
    active_bots[tg_bot_id_str] = True

    await load_bots(db)
    bot_data = bot_dispatchers.get(tg_bot_id_str)
    if not bot_data:
        raise HTTPException(status_code=500, detail=f"Bot dispatcher not found for {tg_bot_id_str}")

    # --- Стартуємо новий полінг у фоні
    print(f"▶️ Starting polling for bot {tg_bot_id_str} ({bot.username}) ...")
    task = asyncio.create_task(bot_data['dp'].start_polling(bot_data['bot']))
    bot_data["task"] = task  # зберігаємо таску, щоб потім можна було зупинити

    crud.create_audit_log(
        db, bot_id=bot.id,
        actor_tg_id=data.get('owner_tg_id'),
        action="start_bot",
        payload={"mode": "polling"}
    )
    return {"status": f"Bot {bot.username} restarted in polling mode"}


@router.post("/create_chat")
async def create_chat(payload: dict, db: Session = Depends(get_db)):
    bot_id = payload.get("bot_id")
    title = payload.get("title")
    if not bot_id or not title:
        raise HTTPException(status_code=400, detail="Missing bot_id or title")
    bot = crud.get_bot_by_id(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    # Check mode: in multi, limit 1 room per bot
    if bot.mode == "multi":
        existing_rooms = db.query(models.ChatRoom).filter(models.ChatRoom.bot_id == bot_id).count()
        if existing_rooms >= 1:
            raise HTTPException(status_code=400, detail="Multi mode: Only one chat per bot")
    room = crud.create_chat_room(db, bot_id=bot_id, title=title)
    crud.create_audit_log(db, bot_id=bot_id, actor_tg_id=None, action="create_chat", payload={"title": title})
    return {"id": room.id, "title": room.title}

@router.post("/add_participant")
async def add_participant(payload: dict, db: Session = Depends(get_db)):
    room_id = payload.get("room_id")
    tg_user_id = payload.get("tg_user_id")
    pseudonym = payload.get("pseudonym")
    tag = payload.get("tag")

    if not room_id or not tg_user_id or not pseudonym:
        raise HTTPException(status_code=400, detail="Missing required fields: room_id, tg_user_id, pseudonym")

    # Перевіряємо чи існує кімната
    room = crud.get_chat_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Chat room not found")

    # Створюємо учасника
    try:
        participant = models.Participant(
            room_id=room_id,
            tg_user_id=tg_user_id,
            pseudonym=pseudonym,
            tag=tag
        )
        db.add(participant)
        db.commit()
        db.refresh(participant)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to add participant: {e}")

    await redis_client.publish(f"fanout:{room_id}", json.dumps({
        "bot_id": room.bot_id,
        "room_id": room_id,
        "text": f"[Система] {pseudonym} був доданий до чату.",
        "is_system": True
    }))

    crud.create_audit_log(
        db,
        bot_id=room.bot_id,
        actor_tg_id=tg_user_id,
        action="add_participant",
        payload={"room_id": room_id, "pseudonym": pseudonym, "tag": tag}
    )

    return {
        "id": participant.id,
        "room_id": participant.room_id,
        "tg_user_id": participant.tg_user_id,
        "pseudonym": participant.pseudonym,
        "tag": participant.tag,
        "joined_at": participant.joined_at.isoformat() if participant.joined_at else None
    }

@router.post("/invalidate_invites")
async def invalidate_invites(
    payload: dict,
    db: Session = Depends(get_db)
):
    room_id = payload.get("room_id")
    pseudonyms = payload.get("pseudonyms", [])

    if not room_id:
        raise HTTPException(status_code=400, detail="room_id is required")

    q = db.query(models.InviteLink).filter(models.InviteLink.room_id == room_id)

    if pseudonyms:
        q = q.filter(models.InviteLink.pseudonym.in_(pseudonyms))

    now = datetime.utcnow()
    q.update({models.InviteLink.expires_at: now - timedelta(seconds=1)}, synchronize_session=False)
    db.commit()

    return {"status": "ok", "invalidated": q.count()}

@router.post("/extend_invite")
async def extend_invite(payload: dict, db: Session = Depends(get_db)):
    code = payload.get("code")
    hours = payload.get("hours")

    if not code or not hours:
        raise HTTPException(status_code=400, detail="code and hours are required")

    invite = db.query(models.InviteLink).filter(models.InviteLink.code == code).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    try:
        extra = timedelta(hours=int(hours))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid hours")

    if not invite.expires_at:
        invite.expires_at = datetime.utcnow() + extra
    else:
        invite.expires_at += extra

    db.commit()
    db.refresh(invite)

    return {
        "status": "ok",
        "code": invite.code,
        "new_expires_at": invite.expires_at.isoformat()
    }

@router.post("/generate_invite")
async def generate_invite(payload: dict, db: Session = Depends(get_db)):
    room_id = payload.get("room_id")
    pseudonym = payload.get("pseudonym")
    tag = payload.get("tag")

    if not room_id or not pseudonym:
        raise HTTPException(status_code=400, detail="Missing room_id or pseudonym")

    room = crud.get_chat_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Chat room not found")

    bot = crud.get_bot_by_id(db, room.bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # 👉 Додаємо перевірку для multi-mode
    if bot.mode == "multi":
        current_count = db.query(models.Participant).filter_by(room_id=room_id).count()
        if current_count >= 2:
            raise HTTPException(
                status_code=400,
                detail="Multi mode: room already has 2 participants"
            )

    # Створення інвайту
    code = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=1)
    invite = crud.create_invite_link(
        db,
        room_id=room_id,
        code=code,
        expires_at=expires_at,
        pseudonym=pseudonym,
        tag=tag
    )

    crud.create_audit_log(
        db,
        bot_id=room.bot_id,
        actor_tg_id=None,
        action="generate_invite",
        payload={"room_id": room_id, "pseudonym": pseudonym}
    )

    return {
        "id": invite.id,
        "room_id": invite.room_id,
        "code": invite.code,
        "expires_at": invite.expires_at.isoformat(),
        "pseudonym": invite.pseudonym,
        "tag": invite.tag
    }


@router.post("/generate_mass_invites")
async def generate_mass_invites(payload: dict, db: Session = Depends(get_db)):
    room_id = payload.get("room_id")
    pseudonyms = payload.get("pseudonyms", [])
    tags = payload.get("tags", [])

    if not room_id or not pseudonyms:
        raise HTTPException(status_code=400, detail="Missing room_id or pseudonyms")

    room = crud.get_chat_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Chat room not found")

    bot = crud.get_bot_by_id(db, room.bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # 👉 Перевірка для multi-mode
    if bot.mode == "multi":
        current_count = db.query(models.Participant).filter_by(room_id=room_id).count()
        if current_count >= 2:
            raise HTTPException(
                status_code=400,
                detail="Multi mode: room already has 2 participants"
            )
        # Якщо залишилось менше двох місць — обрізаємо список
        available_slots = 2 - current_count
        if available_slots <= 0:
            raise HTTPException(
                status_code=400,
                detail="Multi mode: no slots available"
            )
        pseudonyms = pseudonyms[:available_slots]
        tags = tags[:available_slots]

    if len(tags) != len(pseudonyms):
        tags = [None] * len(pseudonyms)

    invites = []
    for pseudonym, tag in zip(pseudonyms, tags):
        code = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=1)
        invite = crud.create_invite_link(
            db,
            room_id=room_id,
            code=code,
            expires_at=expires_at,
            pseudonym=pseudonym,
            tag=tag
        )
        invites.append({
            "id": invite.id,
            "room_id": invite.room_id,
            "code": invite.code,
            "expires_at": invite.expires_at.isoformat(),
            "pseudonym": invite.pseudonym,
            "tag": invite.tag
        })

    crud.create_audit_log(
        db,
        bot_id=room.bot_id,
        actor_tg_id=None,
        action="generate_mass_invites",
        payload={"room_id": room_id, "pseudonyms": pseudonyms}
    )

    return invites


@router.get("/chat_participants/{room_id}", response_model=List[dict])
async def get_participants(room_id: int, db: Session = Depends(get_db)):
    room = crud.get_chat_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    participants = crud.get_participants(db, room_id)
    return [
        {
            "id": p.id,
            "pseudonym": p.pseudonym,
            "tag": p.tag,
            "joined_at": p.joined_at.isoformat() if p.joined_at else None
        } for p in participants
    ]

@router.get("/room/{room_id}")
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = crud.get_chat_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    bot = crud.get_bot_by_id(db, room.bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    return {
        "id": room.id,
        "title": room.title,
        "bot_id": bot.id,
        "bot_username": bot.username,
    }

@router.delete("/kick_participant/{participant_id}")
async def kick_participant(participant_id: int, db: Session = Depends(get_db)):
    participant = crud.get_participant(db, participant_id)
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    crud.kick_participant(db, participant_id)
    crud.create_audit_log(db, bot_id=None, actor_tg_id=None, action="kick_participant", payload={"participant_id": participant_id})
    return {"status": "Participant kicked"}


@router.delete("/delete_message/{message_id}")
async def delete_message(message_id: int, db: Session = Depends(get_db)):
    message = db.query(models.Message).filter_by(id=message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    room = db.query(models.ChatRoom).filter_by(id=message.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    bot = db.query(models.Bot).filter_by(id=room.bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    token = get_decrypted_token(bot.token_encrypted)
    tg_bot_id_str = str(bot.tg_bot_id)

    bot_data = bot_dispatchers.get(tg_bot_id_str)
    if not bot_data:
        raise HTTPException(status_code=500, detail="Bot not active")

    bot_instance: Bot = bot_data["bot"]

    # дістаємо всі копії цього повідомлення
    copies = db.query(models.MessageCopy).filter_by(message_id=message.id).all()

    for c in copies:
        participant = db.query(models.Participant).filter_by(id=c.recipient_participant_id).first()
        if not participant:
            continue

        try:
            await bot_instance.delete_message(
                chat_id=participant.tg_user_id,
                message_id=c.recipient_tg_message_id
            )
        except Exception as e:
            print(f"⚠️ Не зміг видалити для {participant.tg_user_id}: {e}")

    # видаляємо і копії, і саме повідомлення
    db.query(models.MessageCopy).filter_by(message_id=message.id).delete()
    db.delete(message)
    db.commit()

    db.add(models.AuditLog(
        bot_id=bot.id,
        actor_tg_id=None,
        action="delete_message",
        payload={"message_id": message_id}
    ))
    db.commit()

    return {"status": "Message deleted from DB and chats"}

@router.delete("/kick_all/{room_id}")
async def kick_all(room_id: int, db: Session = Depends(get_db)):
    room = crud.get_chat_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Chat room not found")

    participants = crud.get_participants(db, room_id)
    if not participants:
        return {"status": "No participants to remove"}

    count = 0
    for p in participants:
        crud.kick_participant(db, p.id)
        count += 1

    crud.create_audit_log(
        db, bot_id=room.bot_id,
        actor_tg_id=None,
        action="kick_all",
        payload={"room_id": room_id, "removed": count}
    )
    return {"status": f"Removed {count} participants from room {room.title}"}

@router.post("/push_message")
async def push_message(payload: dict, db: Session = Depends(get_db)):
    room_id = payload.get("room_id")
    text = payload.get("text")

    if not room_id or not text:
        raise HTTPException(status_code=400, detail="Missing room_id or text")

    room = crud.get_chat_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    bot = crud.get_bot_by_id(db, room.bot_id)
    await redis_client.publish(
        f"fanout:{room_id}",
        json.dumps({
            "bot_id": str(bot.tg_bot_id),  # ✅ тепер публікуємо tg_bot_id
            "room_id": room_id,
            "text": f"[ADMIN PUSH]: {text}",
            "is_system": True
        })
    )

    return {"status": "ok", "room_id": room_id, "text": text}

from pydantic import BaseModel

class LinkGroupRequest(BaseModel):
    room_id: int
    tg_group_id: int


@router.post("/link_group")
async def link_group(payload: LinkGroupRequest, db: Session = Depends(get_db)):
    room_id = payload.room_id
    tg_group_id = payload.tg_group_id

    # Перевіряємо чи є така кімната
    room = db.query(models.ChatRoom).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Перевіряємо чи група вже лінкнута
    existing = (
        db.query(models.Group)
        .filter_by(room_id=room_id, tg_group_id=tg_group_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="This group is already linked to the room")

    # Дістаємо бота, який прив’язаний до кімнати
    bot = crud.get_bot_by_id(db, room.bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    from aiogram import Bot as TgBot
    token = get_decrypted_token(bot.token_encrypted)
    tg_bot = TgBot(token=token)

    # Пробуємо отримати справжню назву групи з Telegram
    try:
        chat = await tg_bot.get_chat(tg_group_id)
        group_title = chat.title or room.title
    except Exception as e:
        print(f"⚠️ Failed to fetch group title from Telegram: {e}")
        group_title = room.title  # fallback

    # Створюємо запис про групу в БД
    group = models.Group(
        room_id=room_id,
        tg_group_id=tg_group_id,
        title=group_title
    )
    db.add(group)
    db.commit()
    db.refresh(group)

    return {
        "status": "ok",
        "room_id": room.id,
        "room_title": room.title,
        "tg_group_id": tg_group_id,
        "group_id": group.id,
        "group_title": group.title,
    }
