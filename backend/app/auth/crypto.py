"""Provider secret encryption is separate from hashed application credentials."""

from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(48)


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


class SecretBox:
    def __init__(self, key: str):
        if not key:
            raise ValueError("TOKEN_ENCRYPTION_KEY is not configured")
        self._cipher = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._cipher.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Stored provider secret cannot be decrypted") from exc
