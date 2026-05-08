"""PII encryption: key handling, round-trip, tamper detection."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from questionnaire.domain import encryption


@pytest.fixture(autouse=True)
def fresh_key(monkeypatch):
    """Each test gets its own ephemeral key so tests are isolated."""
    monkeypatch.setenv("QST_PII_KEY", Fernet.generate_key().decode())
    encryption.reset_key_cache()
    yield
    encryption.reset_key_cache()


def test_round_trip_preserves_plaintext():
    ct = encryption.encrypt("peanuts")
    assert encryption.decrypt(ct) == "peanuts"


def test_unicode_round_trips():
    s = "אלרגיות 🤧"
    assert encryption.decrypt(encryption.encrypt(s)) == s


def test_decrypt_with_wrong_key_raises(monkeypatch):
    ct = encryption.encrypt("secret")
    # Now rotate the key and try to decrypt — must fail.
    monkeypatch.setenv("QST_PII_KEY", Fernet.generate_key().decode())
    encryption.reset_key_cache()
    with pytest.raises(encryption.EncryptionError):
        encryption.decrypt(ct)


def test_invalid_key_value_raises():
    os.environ["QST_PII_KEY"] = "not-a-valid-fernet-key"
    encryption.reset_key_cache()
    with pytest.raises(encryption.EncryptionError):
        encryption.encrypt("x")
