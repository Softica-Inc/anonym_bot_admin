# app/admin.py
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet
from typing import List
import uuid
from datetime import datetime, timedelta
import json

from app.database import get_db
from app import crud, schemas, models
from app.utils import get_decrypted_token
from app.webhook import load_bots

router = APIRouter(prefix="/admin", tags=["admin"])
TELEGRAM_API = "https://api.telegram.org"
FERNET_KEY = os.getenv("FERNET_KEY")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")  # Set in .env
MAX_BOTS_PER_ADMIN = int(os.getenv("MAX_BOTS_PER_ADMIN", 10))  # Configurable limit

if not FERNET_KEY:
    raise RuntimeError("FERNET_KEY env var not set (generate with Fernet.generate_key()).")

fernet = Fernet(FERNET_KEY.encode())

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
        resp = await httpx.AsyncClient().get(f"{TELEGRAM_API}/bot{token}/getMe", timeout=10.0)
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

    crud.create_audit_log(db, bot_id=bot.id, actor_tg_id=owner_tg_ids[0], action="register_bot", payload={"mode": mode})

    return schemas.BotResponse(
        id=bot.id,
        tg_bot_id=bot.tg_bot_id,
        username=bot.username,
        mode=bot.mode,
        owners=owner_tg_ids,
        created_at=bot.created_at.isoformat()
    )

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

    token = get_decrypted_token(bot.token_encrypted)
    webhook_url = f"{WEBHOOK_BASE_URL.rstrip('/')}/webhook/{bot.tg_bot_id}"

    async with httpx.AsyncClient(timeout=10) as client:
        # безпечне отримання webhookInfo
        try:
            r = await client.get(f"{TELEGRAM_API}/bot{token}/getWebhookInfo")
            try:
                data = r.json()
            except Exception:
                data = {}
        except httpx.HTTPError as exc:
            data = {}
        need_start = (not data.get("ok")) or (data.get("result", {}).get("url") != webhook_url)

        if need_start:
            # Якщо URL не https, повідомляємо що треба публічний HTTPS (ngrok)
            if not webhook_url.startswith("https://"):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Webhook URL `{webhook_url}` не HTTPS або недоступний. "
                        "Telegram вимагає публічний HTTPS. Для локальної розробки скористайтесь ngrok і встановіть "
                        "WEBHOOK_BASE_URL у .env на ngrok HTTPS URL."
                    )
                )

            # спробувати стартувати бот (локально на вашому бекендi)
            start = await client.post(f"{WEBHOOK_BASE_URL.rstrip('/')}/admin/start_bot", json={"bot_id": bot.id})
            if start.status_code >= 400:
                try:
                    err = start.json()
                except Exception:
                    err = start.text
                raise HTTPException(status_code=400, detail=f"Bot was not running and could not be started: {err}")

    # 4️⃣  Створюємо інвайт (як було)
    code = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=1)
    invite = crud.create_invite_link(
        db,
        room_id=room_id,
        code=code,
        expires_at=expires_at,
        pseudonym=pseudonym,
        tag=tag,
    )
    crud.create_audit_log(db,
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
    if len(tags) != len(pseudonyms):
        tags = [None] * len(pseudonyms)
    invites = []
    for pseudonym, tag in zip(pseudonyms, tags):
        code = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=1)
        invite = crud.create_invite_link(db, room_id=room_id, code=code, expires_at=expires_at, pseudonym=pseudonym, tag=tag)
        invites.append({
            "id": invite.id,
            "room_id": invite.room_id,
            "code": invite.code,
            "expires_at": invite.expires_at.isoformat(),
            "pseudonym": invite.pseudonym,
            "tag": invite.tag
        })
    crud.create_audit_log(db, bot_id=room.bot_id, actor_tg_id=None, action="generate_mass_invites", payload={"room_id": room_id, "pseudonyms": pseudonyms})
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
    message = crud.get_message(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    crud.delete_message(db, message_id)
    crud.create_audit_log(db, bot_id=None, actor_tg_id=None, action="delete_message", payload={"message_id": message_id})
    return {"status": "Message deleted"}

@router.post("/start_bot", response_model=dict)
async def start_bot(data: dict, db: Session = Depends(get_db)):
    bot_id = data.get('bot_id')
    if not bot_id:
        raise HTTPException(status_code=400, detail="Missing bot_id")
    bot = crud.get_bot_by_id(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    token = get_decrypted_token(bot.token_encrypted)
    webhook_url = f"{WEBHOOK_BASE_URL.rstrip('/')}/webhook/{bot.tg_bot_id}"

    # Якщо webhook URL не https — явно пояснюємо, чому не можна повністю автоматично поставити webhook.
    if not webhook_url.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"WEBHOOK_BASE_URL повинен бути HTTPS та публічно доступний. "
                f"Поточний webhook_url: {webhook_url}. Використайте ngrok / public HTTPS."
            )
        )

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(f"{TELEGRAM_API}/bot{token}/setWebhook", data={"url": webhook_url})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to call Telegram API: {exc}")

        # безпечна перевірка JSON-відповіді
        try:
            j = resp.json()
        except Exception:
            raise HTTPException(status_code=502, detail=f"Telegram returned non-JSON response: {resp.text}")

        if not j.get("ok"):
            # повертаємо деталі від Telegram (error_code / description) — корисно для дебагу
            raise HTTPException(status_code=400, detail=f"Failed to set webhook: {j}")

    # Перезавантажити диспетчери
    try:
        await load_bots(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Webhook set but failed to load bots: {exc}")

    crud.create_audit_log(db, bot_id=bot.id, actor_tg_id=data.get('owner_tg_id'), action="start_bot", payload={})
    return {"status": "Bot started"}
