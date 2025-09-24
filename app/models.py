# models.py
from sqlalchemy import Column, BigInteger, String, Text, JSON, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from .database import Base

class AdminUser(Base):
    __tablename__ = "admin_user"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tg_user_id = Column(BigInteger, unique=True, nullable=False)
    email = Column(String(512), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class Bot(Base):
    __tablename__ = "bot"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tg_bot_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), nullable=False)
    token_encrypted = Column(Text, nullable=False)
    mode = Column(String(50), default='single')
    owners = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class ChatRoom(Base):
    __tablename__ = "chat_room"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bot_id = Column(BigInteger, ForeignKey("bot.id"), nullable=True)
    title = Column(String(255), nullable=True)
    settings = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class InviteLink(Base):
    __tablename__ = "invite_link"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    room_id = Column(BigInteger, ForeignKey("chat_room.id"), nullable=False)
    code = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    pseudonym = Column(String(255), nullable=True)
    tag = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class Participant(Base):
    __tablename__ = "participant"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    room_id = Column(BigInteger, ForeignKey("chat_room.id"), nullable=False)
    tg_user_id = Column(BigInteger, nullable=False)
    pseudonym = Column(String(255), nullable=False)
    tag = Column(String(255), nullable=True)
    joined_at = Column(DateTime, server_default=func.now())
    left_at = Column(DateTime, nullable=True)

class Message(Base):
    __tablename__ = "message"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    room_id = Column(BigInteger, ForeignKey("chat_room.id"), nullable=False)
    sender_participant_id = Column(BigInteger, ForeignKey("participant.id"), nullable=True)
    text = Column(Text, nullable=True)
    content_type = Column(String(50), default='text')
    media_key = Column(String(1024), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    edited_at = Column(DateTime, nullable=True)
    deleted = Column(Boolean, default=False)

class MessageCopy(Base):
    __tablename__ = "message_copy"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(BigInteger, ForeignKey("message.id"), nullable=False)
    recipient_participant_id = Column(BigInteger, ForeignKey("participant.id"), nullable=False)
    recipient_tg_message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bot_id = Column(BigInteger, nullable=True)
    actor_tg_id = Column(BigInteger, nullable=True)
    action = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
