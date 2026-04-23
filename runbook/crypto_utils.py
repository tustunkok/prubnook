import base64
import os
from cryptography.fernet import Fernet
from django.conf import settings


def get_fernet():
    key = settings.PLATFORM_ENCRYPTION_KEY
    if not key:
        key = base64.urlsafe_b64encode(b'0' * 32)
    else:
        key = key.encode() if isinstance(key, str) else key
    return Fernet(key)


def encrypt_text(plain_text: str) -> str:
    f = get_fernet()
    return f.encrypt(plain_text.encode()).decode()


def decrypt_text(cipher_text: str) -> str:
    f = get_fernet()
    return f.decrypt(cipher_text.encode()).decode()
