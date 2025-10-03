import os
import traceback

from fastapi import APIRouter, Request, HTTPException, Depends, FastAPI
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.orm import Session
import asyncio
import json
from datetime import datetime
from aiolimiter import AsyncLimiter
import redis.asyncio as redis

from config import settings
from database import get_db
import crud, models
from utils import get_decrypted_token, decrypt_media_path, MEDIA_ROOT
import admin as admin_router
import asyncio
import os
import uuid
from cryptography.fernet import Fernet
from aiogram import types

rate_limit = AsyncLimiter(30, 1)
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
fanout_running = False

fernet = Fernet(settings.FERNET_KEY.encode())

# Коментуємо весь код по вебхукам
# @router.post("/{tg_bot_id}")
# async def process_webhook(tg_bot_id: int, request: Request, db: Session = Depends(get_db)):
#     update = await request.json()
#     bot_data = bot_dispatchers.get(tg_bot_id)
#     if not bot_data:
#         raise HTTPException(status_code=404, detail="Bot not found")
#     bot = bot_data['bot']
#     dp = bot_data['dp']
#     await dp.feed_update(bot, types.Update(**update))
#     return {"ok": True}

async def save_file_for_room(bot: Bot, tg_file_id: str, ext: str, room_id: int) -> str:
    file = await bot.get_file(tg_file_id)
    raw_name = f"{uuid.uuid4().hex}{ext}"
    enc_name = fernet.encrypt(raw_name.encode()).decode()  # шифруем имя
    room_dir = os.path.join(MEDIA_ROOT, str(room_id))
    os.makedirs(room_dir, exist_ok=True)
    local_path = os.path.join(room_dir, raw_name)
    await bot.download_file(file.file_path, destination=local_path)
    print("DEBUG media_key:", os.path.join(str(room_id), enc_name))
    # повертаємо зашифрований шлях відносно MEDIA_ROOT, з forward slashes
    return os.path.join(str(room_id), enc_name).replace("\\", "/")



# Хендлер /start з deep link
async def handle_start(message: types.Message):
    bot = message.bot
    db = next(get_db())
    code = message.text.split()[-1] if message.text.startswith('/start ') else None

    if code:
        invite = db.query(models.InviteLink).filter(models.InviteLink.code == code).first()
        if not invite or invite.expires_at < datetime.utcnow():
            await message.answer("❌ This invitation link is invalid or has expired.")
            return
        if invite.used:
            await message.answer("❌ This invitation link has already been used.")
            return

        participant = db.query(models.Participant).filter_by(
            room_id=invite.room_id,
            tg_user_id=message.from_user.id
        ).first()

        if not participant:
            participant = crud.create_participant(
                db, invite.room_id, message.from_user.id, invite.pseudonym, invite.tag
            )
            invite.used = True
            db.commit()

            await redis_client.publish(f"fanout:{invite.room_id}", json.dumps({
                "bot_id": bot.id,
                "room_id": invite.room_id,
                "text": f"[System] {invite.pseudonym} has joined the chat.",
                "is_system": True
            }))
            await message.answer(f"✅ You have joined as <b>{participant.pseudonym}</b>.", parse_mode="HTML")
        else:
            await message.answer(f"ℹ️ You are already in this chat as <b>{participant.pseudonym}</b>.", parse_mode="HTML")
    else:
        await message.answer("👋 Welcome! Please use a valid invite link to join a chat.")

# Хендлер повідомлень
async def handle_message(message: types.Message):

    bot = message.bot
    db = next(get_db())

    print(f"Received message from user: {message.from_user.id} in chat {message.chat.id}")

    # Игнорируем /start
    if message.text and (message.text.startswith("/start") or message.text.startswith("/delete")):
        return

    if message.chat.type in ("group", "supergroup"):
        group = db.query(models.Group).filter_by(tg_group_id=message.chat.id).first()
        if not group:
            print(f"⚠️ Group {message.chat.id} not linked to any room")
            return

        room = crud.get_chat_room(db, group.room_id)
        if not room:
            print(f"⚠️ Room {group.room_id} not found")
            return

        alias = group.group_aliases.get(str(message.from_user.id)) if group.group_aliases else None
        if not alias:
            alias = message.from_user.full_name or message.from_user.username or f"user_{message.from_user.id}"
            crud.set_group_alias(db, group.id, message.from_user.id, alias)

        # === Фікс для стікерів і GIF ===
        label = None
        content_type = "text"
        media_key = None

        if message.sticker:
            label = "[Sticker]"
            content_type = "sticker"
            # визначаємо розширення
            file_ext = ".webp"
            if message.sticker.is_animated:
                file_ext = ".tgs"
            elif message.sticker.is_video:
                file_ext = ".webm"
            try:
                media_key = await save_file_for_room(bot, message.sticker.file_id, file_ext, group.room_id)
            except Exception as e:
                print(f"⚠️ Failed to save group sticker: {e}")

        elif message.animation:
            label = "[GIF]"
            content_type = "animation"
            file_ext = os.path.splitext(message.animation.file_name or "")[1] or ".mp4"
            media_key = await save_file_for_room(bot, message.animation.file_id, file_ext, group.room_id)

        elif message.photo:
            # photo array similar to private path: берем max
            label = "[Photo]"
            content_type = "photo"
            largest = message.photo[-1]
            try:
                media_key = await save_file_for_room(bot, largest.file_id, ".jpg", group.room_id)
            except Exception as e:
                print(f"⚠️ Failed to save group photo: {e}")

        elif message.document:
            label = "[Document]"
            content_type = "document"
            file_ext = os.path.splitext(message.document.file_name or "")[1] or ".dat"
            try:
                media_key = await save_file_for_room(bot, message.document.file_id, file_ext, group.room_id)
            except Exception as e:
                print(f"⚠️ Failed to save group document: {e}")

        # текст/підпис для підготовки підписаного рядка
        if label:
            signed_text = f"[Group {group.title}][{alias}]: {label} {message.caption or ''}"
        else:
            signed_text = f"[Group {group.title}][{alias}]: {message.text or ''}"

        # === ЗБЕРЕЖЕННЯ в БД ===
        msg = crud.create_message(
            db, group.room_id, group.id, signed_text, content_type, media_key
        )
        crud.create_message_copy(
            db,
            msg.id,
            group.id,                   # recipient = сама група
            message.message_id,         # recipient_tg_message_id
            senders_tg_message_id=message.message_id
        )

        await redis_client.publish(
            f"fanout:{group.room_id}",
            json.dumps({
                "bot_id": str(bot.id),
                "room_id": group.room_id,
                "text": signed_text,
                "original_msg_id": msg.id,   # 👈 тепер є
                "sender_id": group.id,
                "is_system": False,
                "content_type": content_type,
                "media_key": media_key
            }),
        )

        return

    # Перевірка доступу
    participant = db.query(models.Participant).filter(
        models.Participant.tg_user_id == message.from_user.id,
        models.Participant.left_at.is_(None)
    ).first()
    if not participant:
        await message.answer("You don't have access. Please join via a valid invite link.")
        return

    room = crud.get_chat_room(db, participant.room_id)
    if not room:
        await message.answer("You don't have access. Please join via a valid invite link.")
        return
    room_bot = crud.get_bot_by_id(db, room.bot_id)
    if not room_bot or str(room_bot.tg_bot_id) != str(bot.id):
        await message.answer("You don't have access. Please join via a valid invite link.")
        return


    # ---- Функция для сохранения файла ----
    async def save_file(tg_file_id: str, ext: str) -> str:
        file = await bot.get_file(tg_file_id)
        raw_name = f"{uuid.uuid4().hex}{ext}"
        enc_name = fernet.encrypt(raw_name.encode()).decode()  # шифруем имя
        room_dir = os.path.join(MEDIA_ROOT, str(participant.room_id))
        os.makedirs(room_dir, exist_ok=True)
        local_path = os.path.join(room_dir, raw_name)
        await bot.download_file(file.file_path, destination=local_path)
        print("DEBUG media_key:", os.path.join(str(participant.room_id), enc_name))

        return os.path.join(str(participant.room_id), enc_name).replace("\\", "/")

    # === Определяем тип контента ===
    content_type = "text"
    media_key = None
    text = None

    # --- PHOTO ---
    if message.photo:
        content_type = "photo"
        largest_photo = message.photo[-1]
        media_key = await save_file(largest_photo.file_id, ".jpg")
        media_count = db.query(models.Message).filter_by(
            room_id=participant.room_id,
            content_type=content_type
        ).count() + 1
        text = f"[Photo{media_count}] {message.caption or ''}"

    # --- STICKER ---
    elif message.sticker:
        content_type = "sticker"
        file_ext = ".tgs" if message.sticker.is_animated else ".webm" if message.sticker.is_video else ".webp"
        media_key = await save_file(message.sticker.file_id, file_ext)
        media_count = db.query(models.Message).filter_by(
            room_id=participant.room_id,
            content_type=content_type
        ).count() + 1
        text = f"[Sticker{media_count}]"

    # --- ANIMATION / GIF ---
    elif message.animation or (message.document and message.document.mime_type.startswith("video/")):
        content_type = "animation"
        file_id = message.animation.file_id if message.animation else message.document.file_id
        file_ext = \
        os.path.splitext(getattr(message.animation, "file_name", "") or getattr(message.document, "file_name", ""))[
            1] or ".mp4"
        media_key = await save_file(file_id, file_ext)
        media_count = db.query(models.Message).filter_by(
            room_id=participant.room_id,
            content_type=content_type
        ).count() + 1
        text = f"[GIF{media_count}] {getattr(message, 'caption', '') or ''}"

    # --- DOCUMENT ---
    elif message.document:
        content_type = "document"
        file_ext = os.path.splitext(message.document.file_name or "")[1] or ".dat"
        media_key = await save_file(message.document.file_id, file_ext)
        media_count = db.query(models.Message).filter_by(
            room_id=participant.room_id,
            content_type=content_type
        ).count() + 1
        text = f"[Document{media_count}] {message.caption or ''}"

    # --- AUDIO / VOICE / VIDEO ---
    elif message.voice:
        content_type = "voice"
        media_key = await save_file(message.voice.file_id, ".ogg")
        text = f"[Voice] {message.caption or ''}"

    elif message.audio:
        content_type = "audio"
        file_ext = os.path.splitext(message.audio.file_name or "")[1] or ".mp3"
        media_key = await save_file(message.audio.file_id, file_ext)
        text = f"[Audio] {message.caption or ''}"

    elif message.video:
        content_type = "video"
        file_ext = os.path.splitext(message.video.file_name or "")[1] or ".mp4"
        media_key = await save_file(message.video.file_id, file_ext)
        text = f"[Video] {message.caption or ''}"

    # --- TEXT (повинно бути в кінці!) ---
    if message.text:
        content_type = "text"
        text = message.text

    # --- Якщо ні тексту, ні медіа ---
    if not text and not media_key:
        return




    # === Сохраняем запись в БД ===
    msg = crud.create_message(
        db, participant.room_id, participant.id, text, content_type, media_key
    )

    signed_text = f"[{participant.pseudonym}{f' ({participant.tag})' if participant.tag else ''}]:\n{text}"
    print(f"Published message: {signed_text}")
    senders_tg_message_id = message.message_id  # оригінальний id, який є у відправника

    await redis_client.publish(
        f"fanout:{participant.room_id}",
        json.dumps({
            "bot_id": str(bot.id),
            "room_id": participant.room_id,
            "text": signed_text,
            "original_msg_id": msg.id,
            "sender_id": participant.id,
            "content_type": content_type,
            "media_key": media_key,
            "senders_tg_message_id": senders_tg_message_id  # 👈 тепер беремо з message, без дубля
        }),
    )

# Хендлер edit
async def handle_edit(edited_message: types.Message):
    bot = edited_message.bot
    db = next(get_db())

    # === GROUP EDIT ===
    if edited_message.chat.type in ("group", "supergroup"):
        copy = db.query(models.MessageCopy).filter_by(
            recipient_tg_message_id=edited_message.message_id
        ).first()
        if not copy:
            print(f"⚠️ No copy found for group edit msg_id={edited_message.message_id}")
            return

        original_msg = db.query(models.Message).filter_by(id=copy.message_id).first()
        if not original_msg:
            return

        old_text = original_msg.text
        new_text = edited_message.text or edited_message.caption or ""

        # оновимо в БД
        original_msg.text = new_text
        db.commit()

        await redis_client.publish(f"fanout:{original_msg.room_id}", json.dumps({
            "bot_id": bot.id,
            "room_id": original_msg.room_id,
            "edit": True,
            "original_msg_id": original_msg.id,
            "old_text": old_text,
            "new_text": new_text,
            "sender_id": copy.recipient_participant_id,
            "is_system": True
        }))
        return

    # === PRIVATE EDIT ===
    participant = crud.get_participant_by_tg_id(db, edited_message.from_user.id, None)
    if not participant:
        return

    # шукаємо копію по message_id
    copy = db.query(models.MessageCopy).filter_by(
        recipient_tg_message_id=edited_message.message_id
    ).first()
    if not copy:
        return

    original_msg = db.query(models.Message).filter_by(id=copy.message_id).first()
    if not original_msg:
        return

    old_text = original_msg.text
    new_text = edited_message.text

    # фан-аут edit
    await redis_client.publish(f"fanout:{participant.room_id}", json.dumps({
        "bot_id": bot.id,
        "room_id": participant.room_id,
        "edit": True,
        "original_msg_id": original_msg.id,
        "old_text": old_text,
        "new_text": new_text,
        "sender_id": participant.id,
        "is_system": True
    }))


# === Обробник реакцій ===
async def handle_reaction(update: types.MessageReactionUpdated):
    bot = update.bot
    db = next(get_db())

    # === GROUP REACTION ===
    if update.chat and update.chat.type in ("group", "supergroup"):
        copy = db.query(models.MessageCopy).filter_by(
            recipient_tg_message_id=update.message_id
        ).first()
        if not copy:
            print(f"⚠️ Group reaction: no copy found for tg_message_id={update.message_id}")
            return

        original_msg = db.query(models.Message).filter_by(id=copy.message_id).first()
        if not original_msg:
            return

        emoji = None
        if update.new_reaction:
            r = update.new_reaction[0]
            emoji = getattr(r, "emoji", str(r))
            action_text = f"[System] reacted {emoji} to message #{original_msg.id}"
        elif update.old_reaction:
            r = update.old_reaction[0]
            emoji = getattr(r, "emoji", str(r))
            action_text = f"[System] removed reaction {emoji} from message #{original_msg.id}"
        else:
            return

        await redis_client.publish(
            f"fanout:{original_msg.room_id}",
            json.dumps({
                "bot_id": str(bot.id),
                "room_id": original_msg.room_id,
                "text": action_text,
                "is_system": True,
                "reaction": True,
                "original_msg_id": original_msg.id,
                "sender_id": copy.recipient_participant_id,
                "senders_tg_message_id": copy.senders_tg_message_id
            })
        )
        print(f"handle_reaction: published group reaction for msg {original_msg.id}")
        return

    user = update.user
    if not user:
        print("handle_reaction: no user in update")
        return

    # === PRIVATE REACTION (старий код) ===

    participant = db.query(models.Participant).filter_by(
        tg_user_id=user.id,
        left_at=None
    ).first()
    if not participant:
        print(f"handle_reaction: participant not found for tg_user_id={user.id}")
        return

    # ВАЖЛИВО: знаходимо original_msg_id через MessageCopy.recipient_tg_message_id = update.message_id
    # (не прив'язуючись до participant.id) — це дає правильний original_msg для повідомлення, на яке реагували
    copy_any = db.query(models.MessageCopy).filter_by(
        recipient_tg_message_id=update.message_id
    ).first()
    if not copy_any:
        print(f"handle_reaction: no MessageCopy mapping for tg_message_id={update.message_id}")
        return

    original_msg = db.query(models.Message).filter_by(id=copy_any.message_id).first()
    if not original_msg:
        print(f"handle_reaction: original Message not found id={copy_any.message_id}")
        return

    # --- визначаємо дію ---
    action_text = None

    if update.new_reaction and not update.old_reaction:
        r = update.new_reaction[0]
        emoji = getattr(r, "emoji", str(r))
        action_text = f"[System] {participant.pseudonym} reacted {emoji} to message #{original_msg.id}"

    elif not update.new_reaction and update.old_reaction:
        r = update.old_reaction[0]
        emoji = getattr(r, "emoji", str(r))
        action_text = f"[System] {participant.pseudonym} removed reaction {emoji} from message #{original_msg.id}"

    elif update.new_reaction and update.old_reaction:
        r_old = update.old_reaction[0]
        r_new = update.new_reaction[0]
        emoji_old = getattr(r_old, "emoji", str(r_old))
        emoji_new = getattr(r_new, "emoji", str(r_new))
        action_text = (
            f"[System] {participant.pseudonym} changed reaction {emoji_old} → {emoji_new} on message #{original_msg.id}"
        )

    if not action_text:
        # нічого не змінилось, або раптом немає даних
        print("handle_reaction: no action_text (nothing to send)")
        return

    # Публікуємо у fanout, передаємо original_msg_id (власний id з БД) та маркер reply_to_copy
    await redis_client.publish(
        f"fanout:{participant.room_id}",
        json.dumps({
            "bot_id": str(bot.id),
            "room_id": participant.room_id,
            "text": action_text,
            "is_system": True,
            "reaction": True,
            "original_msg_id": original_msg.id,
            "reply_to_copy": True,
            "sender_id": participant.id,
            "senders_tg_message_id": copy_any.senders_tg_message_id  # 👈
        })
    )

    print(f"handle_reaction: published reaction event for room {participant.room_id} msg {original_msg.id}")

def find_fallback_reply_copy(db: Session, participant_id: int, original_msg_id: int):
    """
    Спроба знайти локальну копію повідомлення для participant_id,
    якщо прямої MessageCopy немає.
    Логіка:
      - шукаємо текст оригіналу (msg.text)
      - якщо є маркер типу [PhotoX], [DocumentX], [VoiceX] тощо → шукаємо по ньому
      - інакше шукаємо по перших 30 символах тексту
      - перевіряємо останні 50 MessageCopy користувача
    """
    orig_msg = crud.get_message(db, original_msg_id)
    if not orig_msg or not orig_msg.text:
        return None

    # Маркер для пошуку
    marker = None
    if orig_msg.text.startswith("[Photo") or orig_msg.text.startswith("[Document") \
       or orig_msg.text.startswith("[Voice") or orig_msg.text.startswith("[Video") \
       or orig_msg.text.startswith("[Audio"):
        marker = orig_msg.text.split("]")[0] + "]"
    else:
        marker = orig_msg.text[:30]

    if not marker:
        return None

    last_copies = (
        db.query(models.MessageCopy)
        .filter_by(recipient_participant_id=participant_id)
        .order_by(models.MessageCopy.id.desc())
        .limit(50)
        .all()
    )

    for lc in last_copies:
        candidate = crud.get_message(db, lc.message_id)
        if not candidate or not candidate.text:
            continue
        if candidate.text.startswith(marker):
            print(f"🔎 fallback matched for user {participant_id}: marker='{marker}' → msg {lc.recipient_tg_message_id}")
            return lc

    return None


async def handle_delete_command(message: types.Message):
    bot = message.bot
    db = next(get_db())

    print(f"➡️ /delete received from {message.from_user.id}, chat={message.chat.id}")
    if not message.reply_to_message:
        await message.answer("❌ Please reply to the message you want to delete.")
        return
    copy = db.query(models.MessageCopy).filter(
        (models.MessageCopy.recipient_tg_message_id == message.reply_to_message.message_id) |
        (models.MessageCopy.senders_tg_message_id == message.reply_to_message.message_id)
    ).first()
    if not copy:
        await message.answer("⚠️ Cannot find the original message mapping.")
        return

    original_msg = db.query(models.Message).filter_by(id=copy.message_id).first()

    if not original_msg:
        await message.answer("⚠️ Original message not found.")
        return

    sender_participant = db.query(models.Participant).filter_by(id=original_msg.sender_participant_id).first()

    if not sender_participant or sender_participant.tg_user_id != message.from_user.id:
        await message.answer("❌ You can delete only your own messages.")
        return

    # видаляємо у всіх копії
    copies = db.query(models.MessageCopy).filter_by(message_id=original_msg.id).all()
    for c in copies:
        participant = db.query(models.Participant).filter_by(id=c.recipient_participant_id).first()
        if not participant:
            continue
        try:
            await bot.delete_message(chat_id=participant.tg_user_id, message_id=c.recipient_tg_message_id)
            print(f"✅ Deleted for {participant.tg_user_id}")
        except Exception as e:
            print(f"⚠️ Failed to delete for {participant.tg_user_id}: {e}")

    # видаляємо і команду /delete
    try:
        await bot.delete_message(message.chat.id, message.message_id)
        print("✅ Deleted the /delete command itself")
    except Exception as e:
        print(f"⚠️ Failed to delete the /delete command itself: {e}")

    # db.query(models.MessageCopy).filter_by(message_id=original_msg.id).delete()
    # db.delete(original_msg)
    # db.commit()
    #
    # print("💾 DB cleaned up for original_msg")



async def listen_fanout():
    """
    Listen to Redis fanout:* channels and deliver messages.
    Simpler behavior for reactions:
      - reactor (sender_id) gets a reply to their local copy (as before)
      - other participants get a readable "copied preview" message (no reply),
        with labels like [Photo3], [Document2] or a text preview.
    System messages do not create MessageCopy entries.
    """
    global fanout_running
    if fanout_running:
        print("⚠️ listen_fanout already running, skipping duplicate start")
        return
    fanout_running = True

    print("✅ Starting listen_fanout (Redis fanout listener)")

    pubsub = redis_client.pubsub()
    await pubsub.psubscribe("fanout:*")

    async for msg in pubsub.listen():
        if msg["type"] != "pmessage":
            continue

        try:
            data = json.loads(msg["data"])
        except Exception as e:
            print(f"❌ Failed to parse Redis message: {e}")
            continue

        bot_id = str(data["bot_id"])
        bot_data = admin_router.bot_dispatchers.get(bot_id)
        if not bot_data:
            print(f"⚠️ Bot {bot_id} not found in bot_dispatchers")
            continue

        db = next(get_db())
        room = crud.get_chat_room(db, data["room_id"])
        if not room:
            print(f"⚠️ Room {data['room_id']} not found")
            continue

        room_bot = crud.get_bot_by_id(db, room.bot_id)
        if not room_bot or str(room_bot.tg_bot_id) != bot_id:
            continue

        bot = bot_data["bot"]
        participants = crud.get_participants(db, data["room_id"])

        print(f"📨 Fanout room={data['room_id']} bot={bot_id} text={data.get('text')} participants={len(participants)}")

        # helper: extract a short preview/label from original message
        def _extract_label_and_preview(msg_obj):
            """
            returns (label, preview_text)
            label: like '[Photo3]' or '[Document2]' if present, else None
            preview_text: short text (maybe caption), or None
            """
            if not msg_obj:
                return (None, None)
            txt = (msg_obj.text or "").strip()
            # try bracket marker at start
            if txt.startswith("["):
                # take up to first ']' as label
                close = txt.find("]")
                if close != -1:
                    label = txt[:close+1]
                    rest = txt[close+1:].strip()
                    preview = rest[:200] if rest else None
                    return (label, preview)
            # fallback: for media types produce a generic label
            if getattr(msg_obj, "content_type", None):
                ct = msg_obj.content_type
                if ct == "photo":
                    return ("[Photo]", txt[:200] or None)
                if ct == "document":
                    return ("[Document]", txt[:200] or None)
                if ct == "voice":
                    return ("[Voice]", txt[:200] or None)
                if ct == "video":
                    return ("[Video]", txt[:200] or None)
                if ct == "audio":
                    return ("[Audio]", txt[:200] or None)
            # finally, plain text preview
            return (None, txt[:200] if txt else None)

        seen_users = set()
        for p in participants:
            if p.tg_user_id in seen_users:
                continue
            seen_users.add(p.tg_user_id)

            async with rate_limit:
                try:
                    # === EDIT case ===
                    if data.get("edit"):
                        original_msg_id = data.get("original_msg_id")
                        editor = crud.get_participant(db, data.get("sender_id"))

                        reply_copy = (
                            db.query(models.MessageCopy)
                            .filter_by(message_id=original_msg_id, recipient_participant_id=p.id)
                            .first()
                        )

                        old_text = data.get("old_text") or ""
                        new_text = data.get("new_text") or ""

                        pretty_text = (
                            f"[System] {editor.pseudonym if editor else 'Someone'} edited message #{original_msg_id}:\n"
                            f"before: \"{old_text}\"\n"
                            f"after: \"{new_text}\""
                        )

                        if reply_copy and reply_copy.recipient_tg_message_id:
                            try:
                                sent = await bot.send_message(
                                    p.tg_user_id,
                                    pretty_text,
                                    reply_to_message_id=reply_copy.recipient_tg_message_id
                                )
                            except Exception as e:
                                print(f"⚠️ Reply failed for user {p.id} (edit notice): {e}")
                                sent = await bot.send_message(p.tg_user_id, pretty_text)
                        else:
                            sent = await bot.send_message(p.tg_user_id, pretty_text)

                        continue

                    sent = None
                    ctype = data.get("content_type")
                    media_key = data.get("media_key")

                    # === SENDER: НЕ відправляємо дубль, лише зберігаємо copy ===
                    if (not data.get("is_system")) and data.get("original_msg_id") and p.id == data.get("sender_id"):
                        # Якщо у повідомленні є реальний tg message id від відправника — зберігаємо його
                        if data.get("senders_tg_message_id"):
                            try:
                                crud.create_message_copy(
                                    db,
                                    data["original_msg_id"],
                                    p.id,
                                    data["senders_tg_message_id"],
                                    senders_tg_message_id=data.get("senders_tg_message_id")
                                )
                            except Exception as e:
                                print(f"⚠️ create_message_copy for sender {p.id} failed: {e}")
                        # не шлемо нічого від бота відправнику — уникаємо дубля
                        continue

                    # === MEDIA forwarding for normal messages (for other participants) ===
                    if ctype in {"photo", "document", "voice", "audio", "video", "sticker", "animation"} and media_key:
                        local_path = decrypt_media_path(media_key)
                        from aiogram.types import FSInputFile
                        try:
                            if ctype == "photo":
                                sent = await bot.send_photo(p.tg_user_id, FSInputFile(local_path), caption=data["text"])
                            elif ctype == "document":
                                sent = await bot.send_document(p.tg_user_id, FSInputFile(local_path),
                                                               caption=data["text"])
                            elif ctype == "voice":
                                sent = await bot.send_voice(p.tg_user_id, FSInputFile(local_path), caption=data["text"])
                            elif ctype == "audio":
                                sent = await bot.send_audio(p.tg_user_id, FSInputFile(local_path), caption=data["text"])
                            elif ctype == "sticker":
                                try:
                                    sent = await bot.send_sticker(p.tg_user_id, FSInputFile(local_path))
                                except Exception as e_st:
                                    print(f"⚠️ send_sticker failed, trying send_animation as fallback: {e_st}")
                                    try:
                                        sent = await bot.send_animation(p.tg_user_id, FSInputFile(local_path), caption=data["text"])
                                    except Exception as e2:
                                        print(f"❌ send_animation fallback also failed: {e2}")
                                        raise

                            elif ctype == "animation":
                                sent = await bot.send_animation(p.tg_user_id, FSInputFile(local_path),
                                                                caption=data["text"])
                            elif ctype == "video":
                                sent = await bot.send_video(p.tg_user_id, FSInputFile(local_path), caption=data["text"])
                        except Exception as e:
                            print(f"❌ Failed to send media to {p.tg_user_id}: {e}")
                            traceback.print_exc()
                            continue

                        except Exception as e:
                            print(f"❌ Failed to send media to {p.tg_user_id}: {e}")
                            traceback.print_exc()
                            # не створюємо копію, переходимо далі
                            continue


                    else:
                        # === TEXT / SYSTEM / REACTION handling ===
                        if data.get("reaction"):
                            original_msg_id = data.get("original_msg_id")
                            reactor = crud.get_participant(db, data.get("sender_id"))

                            # Спроба знайти точну локальну копію для цього отримувача
                            reply_copy = (
                                db.query(models.MessageCopy)
                                .filter_by(message_id=original_msg_id, recipient_participant_id=p.id)
                                .first()
                            )
                            # fallback: спробувати знайти за маркером серед останніх 50 копій
                            if not reply_copy:
                                try:
                                    reply_copy = find_fallback_reply_copy(db, p.id, original_msg_id)
                                except Exception:
                                    reply_copy = None

                            # Витягуємо emoji із тексту (якщо можливо)
                            emoji = None
                            try:
                                parts = (data.get("text") or "").split()
                                if "reacted" in parts:
                                    idx = parts.index("reacted")
                                    if idx + 1 < len(parts):
                                        emoji = parts[idx + 1]
                            except Exception:
                                emoji = None

                            pretty_text = f"[System] {reactor.pseudonym if reactor else 'Someone'} reacted {emoji or ''} to message #{original_msg_id}"

                            if reply_copy and getattr(reply_copy, "recipient_tg_message_id", None):
                                target_msg_id = reply_copy.recipient_tg_message_id
                                try:
                                    sent = await bot.send_message(
                                        p.tg_user_id,
                                        pretty_text,
                                        reply_to_message_id=target_msg_id
                                    )
                                except Exception as e:
                                    print(f"⚠️ Reply failed for user {p.id}: {e}")
                                    sent = await bot.send_message(p.tg_user_id, pretty_text)
                            else:
                                # якщо копії нема — просто шлемо красивий прев'ю-текст
                                sent = await bot.send_message(p.tg_user_id, pretty_text)
                        else:
                            try:
                                sent = await bot.send_message(p.tg_user_id, data["text"])
                            except Exception as e_text:
                                print(f"⚠️ Primary send failed for participant {p.id}, trying fallback: {e_text}")
                                # fallback: якщо text в data присутній, шлемо його ще раз
                                text_to_send = data.get("text") or ""
                                if text_to_send:
                                    try:
                                        sent = await bot.send_message(p.tg_user_id, text_to_send)
                                    except Exception as e_fb:
                                        print(f"❌ Fallback send also failed for participant {p.id}: {e_fb}")

                    # === CREATE MESSAGE COPY for non-system original messages ===
                    # Створюємо/оновлюємо запис лише для реальних (non-system) повідомлень
                    if (not data.get("is_system")) and data.get("original_msg_id"):
                        try:
                            # Для отримувача — зберігаємо id щойно надісланого повідомлення
                            # === CREATE MESSAGE COPY ===
                            if sent and getattr(sent, "message_id", None):
                                try:
                                    if data.get("original_msg_id"):
                                        # 👈 для звичайних і reaction/edit
                                        crud.create_message_copy(
                                            db,
                                            data["original_msg_id"],
                                            p.id,
                                            sent.message_id,
                                            senders_tg_message_id=data.get("senders_tg_message_id")
                                        )
                                    else:
                                        # 👈 навіть якщо system-only без original_msg_id (наприклад, join/leave),
                                        # створимо псевдо, щоб завжди було з чим працювати
                                        pseudo_id = f"sys-{uuid.uuid4()}"
                                        crud.create_message_copy(
                                            db,
                                            pseudo_id,
                                            p.id,
                                            sent.message_id
                                        )
                                except Exception as e:
                                    print(f"⚠️ create_message_copy failed for participant {p.id}: {e}")

                        except Exception as e:
                            print(f"⚠️ create_message_copy failed for recipient {p.id}: {e}")

                except Exception as e:
                    print(f"❌ Failed to send message to participant {p.id}: {e}")
                    traceback.print_exc()

        groups = db.query(models.Group).filter_by(room_id=room.id).all()
        for g in groups:
            try:
                # 🚫 якщо відправник — це сама група, не пересилаємо назад
                if data.get("sender_id") == g.id:
                    continue

                if not data.get("content_type") or data.get("content_type") == "text":
                    try:
                        await bot.send_message(g.tg_group_id, data.get("text") or "")
                    except Exception as e:
                        print(f"⚠️ Failed to send text to group {g.tg_group_id}: {e}")
                    continue  # 👈 щоб не падало далі у медіа-логіку

                if data.get("content_type") in {"photo", "document", "voice", "audio", "video", "sticker",
                                                "animation"} and data.get("media_key"):
                    local_path = decrypt_media_path(data["media_key"])
                    from aiogram.types import FSInputFile

                    # 👉 якщо стікер або гіф — спочатку шлемо підпис зверху
                    if data["content_type"] in {"sticker", "animation"}:
                        try:
                            await bot.send_message(g.tg_group_id, f"{data.get('text', '')}")  # підпис зверху
                        except Exception as e:
                            print(f"⚠️ Failed to send sticker caption to group {g.tg_group_id}: {e}")

                    try:
                        if data["content_type"] == "photo":
                            await bot.send_photo(g.tg_group_id, FSInputFile(local_path), caption=data.get("text"))
                        elif data["content_type"] == "document":
                            await bot.send_document(g.tg_group_id, FSInputFile(local_path), caption=data.get("text"))
                        elif data["content_type"] == "voice":
                            await bot.send_voice(g.tg_group_id, FSInputFile(local_path), caption=data.get("text"))
                        elif data["content_type"] == "audio":
                            await bot.send_audio(g.tg_group_id, FSInputFile(local_path), caption=data.get("text"))
                        elif data["content_type"] == "sticker":
                            await bot.send_sticker(g.tg_group_id, FSInputFile(local_path))
                        elif data["content_type"] == "animation":  # 👈 GIF
                            await bot.send_animation(g.tg_group_id, FSInputFile(local_path))
                        else:
                            await bot.send_video(g.tg_group_id, FSInputFile(local_path), caption=data.get("text"))
                    except Exception as e:
                        print(f"⚠️ Failed to send to group {g.tg_group_id}: {e}")

            except Exception as e:
                print(f"⚠️ Failed to send to group {g.tg_group_id}: {e}")

        try:
            db.commit()
        except Exception as e:
            print(f"❌ DB commit failed in listen_fanout: {e}")
            db.rollback()