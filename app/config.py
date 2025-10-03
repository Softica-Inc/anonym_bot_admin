# config.py
from pydantic.v1 import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str  # Твій URL Redis не є валідним HTTP URL, тому AnyHttpUrl не підійде
    FERNET_KEY: str
    MAX_BOTS_PER_ADMIN: int = 10
    WEBHOOK_BASE_URL: Optional[str] = None

    class Config:
        env_file = ".env"

settings = Settings()

print(f"DATABASE_URL: {settings.DATABASE_URL}")
print(f"REDIS_URL: {settings.REDIS_URL}")
print(f"FERNET_KEY: {settings.FERNET_KEY}")
print(f"MAX_BOTS_PER_ADMIN: {settings.MAX_BOTS_PER_ADMIN}")
print(f"WEBHOOK_BASE_URL: {settings.WEBHOOK_BASE_URL}")
