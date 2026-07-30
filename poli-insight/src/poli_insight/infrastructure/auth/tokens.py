"""Generate and digest high-entropy bearer tokens safely.

Invitation and participant access-grant tokens are random bearer credentials.
Only their SHA-256 digest and a short display hint should be persisted; the
plaintext is returned once to the caller for delivery.

These helpers must not be used for passwords or human-chosen access codes.
Low-entropy secrets require a salted, deliberately expensive password-hashing
algorithm such as Argon2id, scrypt, or bcrypt.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass

from poli_insight.domain.content_hash import sha256_digest


DEFAULT_TOKEN_BYTES = 32
MINIMUM_TOKEN_BYTES = 32
MAXIMUM_TOKEN_BYTES = 512
DEFAULT_HINT_CHARACTERS = 6
MAXIMUM_HINT_CHARACTERS = 12
MAXIMUM_TOKEN_CHARACTERS = 1_024
_SHA256_HEX_LENGTH = 64
_DUMMY_DIGEST = "0" * _SHA256_HEX_LENGTH


class TokenError(ValueError):
    """Raised when secure token input or configuration is invalid."""


@dataclass(frozen=True, slots=True, repr=False)
class IssuedToken:
    """One-time plaintext token and the values safe to persist.

    The custom representation redacts both the plaintext and digest to reduce
    accidental disclosure through logs and exception diagnostics. Callers must
    access ``plaintext`` explicitly when delivering the credential.
    """

    plaintext: str
    token_digest: str
    token_hint: str

    def __post_init__(self) -> None:
        _validate_plaintext(self.plaintext)
        if not _is_sha256_digest(self.token_digest):
            raise TokenError(
                "token_digest must be a lowercase hexadecimal SHA-256 digest."
            )
        expected_digest = digest_token(self.plaintext)
        if not hmac.compare_digest(expected_digest, self.token_digest):
            raise TokenError("token_digest does not match plaintext.")
        if not self.token_hint.startswith("…"):
            raise TokenError("token_hint must use the redacted hint format.")
        visible_hint = self.token_hint.removeprefix("…")
        if (
            not visible_hint
            or len(visible_hint) > MAXIMUM_HINT_CHARACTERS
            or len(visible_hint) >= len(self.plaintext)
            or not self.plaintext.endswith(visible_hint)
        ):
            raise TokenError("token_hint does not match plaintext.")

    def __repr__(self) -> str:
        return (
            "IssuedToken(plaintext=<redacted>, token_digest=<redacted>, "
            f"token_hint={self.token_hint!r})"
        )

    def __str__(self) -> str:
        return repr(self)


def generate_token(
    *,
    byte_count: int = DEFAULT_TOKEN_BYTES,
    hint_characters: int = DEFAULT_HINT_CHARACTERS,
) -> IssuedToken:
    """Generate a URL-safe token with at least 256 bits of entropy.

    ``secrets.token_urlsafe`` encodes operating-system randomness without
    padding, making the plaintext suitable for links and secure cookies.
    """

    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or not MINIMUM_TOKEN_BYTES <= byte_count <= MAXIMUM_TOKEN_BYTES
    ):
        raise TokenError(
            "byte_count must be an integer between "
            f"{MINIMUM_TOKEN_BYTES} and {MAXIMUM_TOKEN_BYTES}."
        )

    plaintext = secrets.token_urlsafe(byte_count)
    return IssuedToken(
        plaintext=plaintext,
        token_digest=digest_token(plaintext),
        token_hint=make_token_hint(
            plaintext,
            visible_characters=hint_characters,
        ),
    )


def digest_token(plaintext: str) -> str:
    """Return the persistence-safe SHA-256 digest of an opaque token."""

    _validate_plaintext(plaintext)
    return sha256_digest(plaintext.encode("utf-8"))


def verify_token(plaintext: object, expected_digest: object) -> bool:
    """Verify an opaque token using constant-time digest comparison.

    Malformed untrusted input returns ``False`` rather than exposing validation
    distinctions to an authentication caller. A fixed dummy digest keeps the
    final comparison present even when the stored digest is malformed.
    """

    plaintext_is_valid = _is_valid_plaintext(plaintext)
    digest_is_valid = _is_sha256_digest(expected_digest)

    candidate_digest = (
        sha256_digest(plaintext.encode("utf-8"))
        if plaintext_is_valid and isinstance(plaintext, str)
        else _DUMMY_DIGEST
    )
    comparison_digest = (
        expected_digest
        if digest_is_valid and isinstance(expected_digest, str)
        else _DUMMY_DIGEST
    )
    matches = hmac.compare_digest(candidate_digest, comparison_digest)
    return plaintext_is_valid and digest_is_valid and matches


def make_token_hint(
    plaintext: str,
    *,
    visible_characters: int = DEFAULT_HINT_CHARACTERS,
) -> str:
    """Return a noncredential suffix suitable for identifying a token."""

    _validate_plaintext(plaintext)
    if (
        isinstance(visible_characters, bool)
        or not isinstance(visible_characters, int)
        or not 1 <= visible_characters <= MAXIMUM_HINT_CHARACTERS
    ):
        raise TokenError(
            "visible_characters must be an integer between 1 and "
            f"{MAXIMUM_HINT_CHARACTERS}."
        )
    if visible_characters >= len(plaintext):
        raise TokenError("Token hint cannot reveal the complete token.")
    return f"…{plaintext[-visible_characters:]}"


def _validate_plaintext(plaintext: object) -> None:
    if not _is_valid_plaintext(plaintext):
        raise TokenError(
            "Token must be a nonempty string without whitespace and no more "
            f"than {MAXIMUM_TOKEN_CHARACTERS} characters."
        )


def _is_valid_plaintext(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAXIMUM_TOKEN_CHARACTERS
        and not any(character.isspace() for character in value)
    )


def _is_sha256_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_HEX_LENGTH
        and all(
            character in "0123456789abcdef"
            for character in value
        )
    )
