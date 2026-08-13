"""HMAC lookup digests and authenticated encryption for imported identity."""

from __future__ import annotations

import hashlib
import hmac
import os
import unicodedata

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = b"PII1"
_NONCE_BYTES = 12


def normalize_participant_reference(value: str) -> str:
    """Apply the documented deterministic reference normalization."""

    return unicodedata.normalize("NFKC", value).strip()


def normalize_email_for_lookup(value: str) -> str:
    """Normalize an email only for protected equality lookup."""

    return unicodedata.normalize("NFKC", value).strip().casefold()


class AesGcmIdentityProtector:
    """Use domain-separated HMAC-SHA256 and AES-256-GCM."""

    def __init__(self, *, hmac_secret: str, encryption_secret: str) -> None:
        self._hmac_key = _derive_key(hmac_secret, b"participant-import-hmac")
        self._encryption_key = _derive_key(
            encryption_secret, b"participant-identity-aesgcm"
        )

    def participant_reference_digest(self, normalized_reference: str) -> str:
        return self._digest(b"participant-reference\x00", normalized_reference)

    def email_lookup_digest(self, normalized_email: str) -> str:
        return self._digest(b"participant-email\x00", normalized_email)

    def encrypt(self, plaintext: str, *, context: str) -> bytes:
        if not plaintext or not context.strip():
            raise ValueError("Identity plaintext and encryption context are required.")
        nonce = os.urandom(_NONCE_BYTES)
        encrypted = AESGCM(self._encryption_key).encrypt(
            nonce,
            plaintext.encode("utf-8"),
            context.encode("utf-8"),
        )
        return _VERSION + nonce + encrypted

    def decrypt(self, ciphertext: bytes, *, context: str) -> str:
        if not ciphertext.startswith(_VERSION) or len(ciphertext) <= 32:
            raise ValueError("Encrypted identity payload is invalid.")
        nonce_start = len(_VERSION)
        nonce_end = nonce_start + _NONCE_BYTES
        plaintext = AESGCM(self._encryption_key).decrypt(
            ciphertext[nonce_start:nonce_end],
            ciphertext[nonce_end:],
            context.encode("utf-8"),
        )
        return plaintext.decode("utf-8")

    def _digest(self, domain: bytes, value: str) -> str:
        if not value:
            raise ValueError("Normalized lookup value cannot be empty.")
        return hmac.new(
            self._hmac_key,
            domain + value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


def _derive_key(secret: str, domain: bytes) -> bytes:
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("Identity protection secrets require at least 32 bytes.")
    return hmac.new(secret.encode("utf-8"), domain, hashlib.sha256).digest()
