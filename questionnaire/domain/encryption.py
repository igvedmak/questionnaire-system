"""Symmetric encryption for PII answers.

Key resolution order (first match wins):

1. ``QST_PII_KEY`` environment variable — preferred for production /
   container deployments where keys come from secret managers.
2. A persisted file at ``data/.qst_pii.key`` — the dev fallback. The key
   is generated on first use and reused across processes, so writes in
   one shell are readable in the next without any manual setup.
3. Generated and persisted to (2) if neither was present.

The ``data/.qst_pii.key`` file is intentionally not committed (see
.gitignore) and is created with ``chmod 0600``. For real deployments,
set ``QST_PII_KEY`` from a secret manager and don't rely on the file.

Why Fernet rather than rolling our own AES-GCM:
- Audited construction with no nonce-reuse footguns.
- The ``cryptography`` dependency is already required.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


_KEY_ENV = "QST_PII_KEY"
_KEY_FILE = Path("data/.qst_pii.key")


class EncryptionError(Exception):
    pass


def _resolve_key() -> str:
    raw = os.environ.get(_KEY_ENV)
    if raw:
        return raw
    if _KEY_FILE.exists():
        return _KEY_FILE.read_text(encoding="utf-8").strip()
    # First-run dev path: generate, persist with restrictive perms.
    raw = Fernet.generate_key().decode()
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(raw, encoding="utf-8")
    try:
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        # Filesystem may not support chmod (e.g., some Windows mounts);
        # not fatal — the key is still in a gitignored file.
        pass
    return raw


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    try:
        return Fernet(_resolve_key().encode())
    except (ValueError, TypeError) as e:
        raise EncryptionError(
            f"PII key is not a valid Fernet key (44-byte base64-urlsafe). "
            f"Generate one with: python -c 'from cryptography.fernet import Fernet; "
            f"print(Fernet.generate_key().decode())' and set ${_KEY_ENV} or write to {_KEY_FILE}"
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
