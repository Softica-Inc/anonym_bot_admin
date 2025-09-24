# app/schemas.py
from pydantic import BaseModel
from typing import Optional, List

class BotRegisterRequest(BaseModel):
    token: str
    mode: str = "single"  # Default to single-bot mode
    owner_tg_ids: List[int] = []  # List of Telegram user IDs who own the bot

class BotResponse(BaseModel):
    id: int
    tg_bot_id: int
    username: str
    mode: str
    owners: Optional[List[int]]
    created_at: Optional[str]