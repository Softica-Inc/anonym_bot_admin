# app/utils.py
import os
from cryptography.fernet import Fernet
from config import settings

MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media")
# 🔑 використовуємо об’єкт Fernet, а не рядок
fernet = Fernet(settings.FERNET_KEY.encode())

def get_decrypted_token(encrypted: str) -> str:
    fernet = Fernet(settings.FERNET_KEY.encode())
    return fernet.decrypt(encrypted.encode()).decode()

def decrypt_name(enc: str) -> str:
    fernet = Fernet(settings.FERNET_KEY.encode())
    return fernet.decrypt(enc.encode()).decode()


def decrypt_media_path(enc: str) -> str:
    if "/" in enc:
        room_id, token = enc.split("/", 1)
    else:
        raise ValueError("Invalid media_key format")

    raw_name = fernet.decrypt(token.encode()).decode()

    safe_path = os.path.normpath(raw_name)
    if safe_path.startswith(".."):
        raise ValueError("Invalid media path")

    return os.path.join(MEDIA_ROOT, room_id, safe_path)
