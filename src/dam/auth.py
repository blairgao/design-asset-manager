"""Magic-link login and cookie sessions (ADR-011)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dam.config import get_settings
from dam.models import MagicLink, User

SESSION_COOKIE = "dam_session"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="session")


def issue_session(user_id: uuid.UUID) -> str:
    return _serializer().dumps(str(user_id))


def read_session(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        raw = _serializer().loads(value, max_age=get_settings().session_ttl_seconds)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_magic_link(
    session: AsyncSession,
    email: str,
    *,
    firm_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    invite_role: str | None = None,
) -> str:
    """Create a single-use token and return the raw token. Only the hash is stored."""
    token = secrets.token_urlsafe(32)
    link = MagicLink(
        token_hash=_hash(token),
        email=email.lower().strip(),
        firm_id=firm_id,
        project_id=project_id,
        invite_role=invite_role,
        expires_at=datetime.now(UTC) + timedelta(seconds=get_settings().magic_link_ttl_seconds),
    )
    session.add(link)
    await session.flush()
    return token


async def redeem_magic_link(session: AsyncSession, token: str) -> tuple[User, MagicLink] | None:
    link = await session.get(MagicLink, _hash(token))
    now = datetime.now(UTC)
    if link is None or link.used_at is not None or link.expires_at < now:
        return None
    link.used_at = now
    user = (await session.execute(select(User).where(User.email == link.email))).scalar_one_or_none()
    if user is None:
        user = User(email=link.email)
        session.add(user)
        await session.flush()
    return user, link


def magic_link_url(token: str) -> str:
    return f"{get_settings().base_url}/auth/verify?token={token}"
