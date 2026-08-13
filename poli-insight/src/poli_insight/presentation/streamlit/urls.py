"""Credential-bearing public URL construction kept out of logging paths."""

from __future__ import annotations

from urllib.parse import urlencode


def private_resume_url(
    public_base_url: str,
    *,
    session_slug: str,
    access_token: str,
) -> str:
    """Build the complete participant URL with encoded opaque query values."""

    return _participation_url(
        public_base_url,
        session_slug=session_slug,
        credential_name="access",
        credential=access_token,
    )


def private_invitation_url(
    public_base_url: str,
    *,
    session_slug: str,
    invitation_token: str,
) -> str:
    """Build a complete private enrollment URL for one invitation token."""

    return _participation_url(
        public_base_url,
        session_slug=session_slug,
        credential_name="invitation",
        credential=invitation_token,
    )


def _participation_url(
    public_base_url: str,
    *,
    session_slug: str,
    credential_name: str,
    credential: str,
) -> str:
    normalized_base = public_base_url.rstrip("/")
    participate_base = (
        normalized_base
        if normalized_base.endswith("/participate")
        else f"{normalized_base}/participate"
    )
    query = urlencode(
        {"session": session_slug, credential_name: credential},
        doseq=False,
        safe="",
    )
    return f"{participate_base}?{query}"
