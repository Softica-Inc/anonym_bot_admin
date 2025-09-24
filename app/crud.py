# app/crud.py
from sqlalchemy.orm import Session
from . import models
import json
from datetime import datetime

def get_bot_by_id(db: Session, bot_id: int):
    return db.query(models.Bot).filter(models.Bot.id == bot_id).first()

def create_chat_room(db: Session, bot_id: int, title: str, settings: dict = None):
    room = models.ChatRoom(bot_id=bot_id, title=title, settings=json.dumps(settings) if settings else None)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room

def get_chat_room(db: Session, room_id: int):
    return db.query(models.ChatRoom).filter(models.ChatRoom.id == room_id).first()

def create_invite_link(db: Session, room_id: int, code: str, expires_at: datetime, pseudonym: str, tag: str = None):
    invite = models.InviteLink(room_id=room_id, code=code, expires_at=expires_at, pseudonym=pseudonym, tag=tag)
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite

def get_participants(db: Session, room_id: int):
    return db.query(models.Participant).filter(models.Participant.room_id == room_id, models.Participant.left_at.is_(None)).all()

def get_participant(db: Session, participant_id: int):
    return db.query(models.Participant).filter(models.Participant.id == participant_id).first()

def get_participant_by_tg_id(db: Session, tg_user_id: int, room_id: int):
    return db.query(models.Participant).filter(
        models.Participant.tg_user_id == tg_user_id,
        models.Participant.room_id == room_id,
        models.Participant.left_at.is_(None)
    ).first()

def create_participant(db: Session, room_id: int, tg_user_id: int, pseudonym: str, tag: str = None):
    participant = models.Participant(
        room_id=room_id,
        tg_user_id=tg_user_id,
        pseudonym=pseudonym,
        tag=tag
    )
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant

def kick_participant(db: Session, participant_id: int):
    participant = get_participant(db, participant_id)
    if participant:
        participant.left_at = datetime.utcnow()
        db.commit()

def get_message(db: Session, message_id: int):
    return db.query(models.Message).filter(models.Message.id == message_id).first()

def create_message(db: Session, room_id: int, sender_participant_id: int, text: str = None, content_type: str = 'text', media_key: str = None):
    message = models.Message(
        room_id=room_id,
        sender_participant_id=sender_participant_id,
        text=text,
        content_type=content_type,
        media_key=media_key
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

def delete_message(db: Session, message_id: int):
    message = get_message(db, message_id)
    if message:
        message.deleted = True
        db.commit()

def create_message_copy(db: Session, message_id: int, recipient_participant_id: int, recipient_tg_message_id: int):
    copy = models.MessageCopy(
        message_id=message_id,
        recipient_participant_id=recipient_participant_id,
        recipient_tg_message_id=recipient_tg_message_id
    )
    db.add(copy)
    db.commit()

def get_message_copies(db: Session, message_id: int):
    return db.query(models.MessageCopy).filter(models.MessageCopy.message_id == message_id).all()

def create_audit_log(db: Session, bot_id: int = None, actor_tg_id: int = None, action: str = None, payload: dict = None):
    log = models.AuditLog(
        bot_id=bot_id,
        actor_tg_id=actor_tg_id,
        action=action,
        payload=json.dumps(payload) if payload else None
    )
    db.add(log)
    db.commit()