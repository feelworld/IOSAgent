import base64

from cryptography.fernet import Fernet

from server.src.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.aes_key.encode()
        key_b64 = base64.urlsafe_b64encode(key.ljust(32, b"\0")[:32])
        _fernet = Fernet(key_b64)
    return _fernet


def encrypt_aes256(plaintext: str) -> str:
    token = _get_fernet().encrypt(plaintext.encode())
    return base64.urlsafe_b64encode(token).decode()


def decrypt_aes256(ciphertext: str) -> str:
    token = base64.urlsafe_b64decode(ciphertext.encode())
    return _get_fernet().decrypt(token).decode()
