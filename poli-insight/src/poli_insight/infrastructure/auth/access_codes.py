"""Scrypt hashing for human-chosen participant access codes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N = 2**14
_R = 8
_P = 1
_KEY_LENGTH = 32
_MIN_LENGTH = 6
_MAX_LENGTH = 128


class AccessCodeError(ValueError):
    pass


def hash_access_code(code: str) -> str:
    normalized = _validate(code)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        normalized.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_LENGTH
    )
    return "scrypt${}${}${}${}${}".format(
        _N,
        _R,
        _P,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def verify_access_code(code: object, encoded: object) -> bool:
    try:
        if not isinstance(code, str) or not isinstance(encoded, str):
            return False
        normalized = _validate(code)
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$")
        if algorithm != "scrypt":
            return False
        salt = _decode(salt_text)
        expected = _decode(digest_text)
        candidate = hashlib.scrypt(
            normalized.encode(),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(candidate, expected)
    except (AccessCodeError, ValueError, TypeError):
        return False


def _validate(code: str) -> str:
    normalized = code.strip()
    if normalized != code or not _MIN_LENGTH <= len(code) <= _MAX_LENGTH:
        raise AccessCodeError(
            f"Access codes must contain {_MIN_LENGTH} to {_MAX_LENGTH} "
            "characters without surrounding whitespace."
        )
    return normalized


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
