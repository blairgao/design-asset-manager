from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from dam.auth import SESSION_COOKIE, read_session
from dam.db import get_session
from dam.viewer import Viewer, resolve_viewer

Session = Annotated[AsyncSession, Depends(get_session)]


async def current_user_id(request: Request) -> uuid.UUID:
    user_id = read_session(request.cookies.get(SESSION_COOKIE))
    if user_id is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user_id


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
