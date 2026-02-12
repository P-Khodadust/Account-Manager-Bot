"""
Symmetric encryption for sensitive data (2FA passwords).

Derives a Fernet key from the BOT_TOKEN so that each bot instance has
a unique encryption key with no extra configuration required.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from bot.config import BOT_TOKEN

logger = logging.getLogger(__name__)

_key = base64.urlsafe_b64encode(
    hashlib.sha256(BOT_TOKEN.encode()).digest()
)
_fernet = Fernet(_key)


def encrypt_password(password: str) -> str:
    """Encrypt a plaintext password and return a URL-safe token string."""
    return _fernet.encrypt(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """Decrypt an encrypted password token back to plaintext.

    Raises ``ValueError`` if the token is invalid or tampered with.
    """
    try:
        return _fernet.decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        logger.error("Failed to decrypt 2FA password — invalid token.")
        raise ValueError("Could not decrypt password.") from exc
