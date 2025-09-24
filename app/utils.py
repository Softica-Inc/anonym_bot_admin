# app/utils.py
import os
from cryptography.fernet import Fernet

def get_decrypted_token(encrypted: str) -> str:
    fernet = Fernet(os.getenv("FERNET_KEY").encode())
    return fernet.decrypt(encrypted.encode()).decode()