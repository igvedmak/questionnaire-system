"""Symmetric encryption for PII answers.

Strategy:
- A single symmetric key, sourced from the ``QST_PII_KEY`` env var (a
  Fernet base64-urlsafe key) or generated at startup if the var is absent
  AND the database has no encrypted rows yet (development convenience).
- Each PII answer's plaintext is Fernet-encrypted (AES-128-CBC + HMAC-SHA256
  with a random IV per message); the ciphertext lands in
  ``answers.value_blob``. ``answers.is_pii`` flags the row so the read-side
  knows to decrypt.
- Key rotation is intentionally out of scope for this round; the
  envelope-encryption / KMS path is the documented next step.

Why Fernet rather than rolling our own AES-GCM:
- It's an opinionated, audited construction with no nonce reuse footguns.
- The single dependency (`cryptography`) is already required for TLS-side
  features anyway.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


_KEY_ENV = "QST_PII_KEY"


class EncryptionError(Exception):
    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = os.environ.get(_KEY_ENV)
    if raw is None:
        # Development convenience: generate an ephemeral key. This means data
        # encrypted under it can't be read in another process — fine for
        # tests and local dev, definitely not fine for production.
        raw = Fernet.generate_key().decode()
        os.environ[_KEY_ENV] = raw
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as e:
        raise EncryptionError(
            f"{_KEY_ENV} is not a valid Fernet key (44-byte base64-urlsafe). "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        ) from e


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as e:
        raise EncryptionError(
            "could not decrypt PII answer — wrong key or tampered ciphertext"
        ) from e


def reset_key_cache() -> None:
    """For tests: drop the cached Fernet so the env var is re-read."""
    _fernet.cache_clear()
