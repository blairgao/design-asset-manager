from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dam.config import get_settings
from dam.db import get_session
from dam.models import Firm, FirmRole, Membership, User
from dam.viewer import Viewer, resolve_viewer

Session = Annotated[AsyncSession, Depends(get_session)]


async def ensure_local_user(session: AsyncSession) -> User:
    """Return the single local user, creating it and a default firm on first use.

    There is no sign-in yet: every request runs as this user, who is an admin of
    DAM_LOCAL_FIRM_SLUG. Replace this with real authentication later.
    """
    settings = get_settings()
    email = settings.local_user_email.lower().strip()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(email=email, name=settings.local_user_name)
        session.add(user)
        await session.flush()
    firm = (
        await session.execute(select(Firm).where(Firm.slug == settings.local_firm_slug))
    ).scalar_one_or_none()
    if firm is None:
        firm = Firm(name=settings.local_firm_name, slug=settings.local_firm_slug)
        session.add(firm)
        await session.flush()
    if await session.get(Membership, (user.id, firm.id)) is None:
        session.add(Membership(user_id=user.id, firm_id=firm.id, role=FirmRole.admin))
        await session.flush()
    await session.commit()
    return user


async def current_user_id(session: Session) -> uuid.UUID:
    return (await ensure_local_user(session)).id


async def current_viewer(
    session: Session,
    user_id: Annotated[uuid.UUID, Depends(current_user_id)],
    x_firm_id: Annotated[str | None, Header()] = None,
) -> Viewer:
    firm_id = None
    if x_firm_id:
        try:
            firm_id = uuid.UUID(x_firm_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid X-Firm-Id") from e
    viewer = await resolve_viewer(session, user_id, firm_id)
    if viewer is None:
        raise HTTPException(status_code=403, detail="no firm membership")
    return viewer


CurrentViewer = Annotated[Viewer, Depends(current_viewer)]
