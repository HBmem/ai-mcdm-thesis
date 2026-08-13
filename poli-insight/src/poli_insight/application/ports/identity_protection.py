"""Secret-handling boundary for imported participant identifiers and PII."""

from __future__ import annotations

from typing import Protocol


class IdentityProtector(Protocol):
    """Protect low-entropy lookup values and identity plaintext."""

    def participant_reference_digest(self, normalized_reference: str) -> str: ...

    def email_lookup_digest(self, normalized_email: str) -> str: ...

    def encrypt(self, plaintext: str, *, context: str) -> bytes: ...

    def decrypt(self, ciphertext: bytes, *, context: str) -> str: ...
