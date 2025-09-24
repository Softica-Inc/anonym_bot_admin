# config.py
from pydantic_settings import BaseSettings
from pydantic import AnyHttpUrl
from typing import Optional

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    BACKEND_URL: AnyHttpUrl
    WEBHOOK_BASE_URL: Optional[str] = None
    ALLOWLIST_ADMIN_IDS: str = ''
    ADMIN_PASSWORD: str  # Додано для аутентифікації

    class Config:
        env_file = '.env'

settings = Settings()
print(f"TELEGRAM_BOT_TOKEN: {settings.TELEGRAM_BOT_TOKEN}")
print(f"BACKEND_URL: {settings.BACKEND_URL}")
print(f"WEBHOOK_BASE_URL: {settings.WEBHOOK_BASE_URL}")
print(f"ALLOWLIST_ADMIN_IDS: {settings.ALLOWLIST_ADMIN_IDS}")
print(f"ADMIN_PASSWORD: {settings.ADMIN_PASSWORD}")

## 2) `admin_bot/utils.py`
## 3) `admin_bot/handlers.py`
## 4) `admin_bot/bot.py` — точка входу
## 5) `admin_bot/requirements.txt`
## 7) `sql/schema.sql`
