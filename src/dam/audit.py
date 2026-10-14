from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from dam.models import AuditLog
from dam.viewer import Viewer


def record(
    session: AsyncSession,
    viewer: Viewer,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None,
    payload: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            firm_id=viewer.firm_id,
            actor_id=viewer.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
        )
    )
