from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from dam.deps import Session, current_user_id
from dam.models import Firm, Membership, User
from dam.schemas import MembershipOut, MeOut

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeOut)
async def me(session: Session, user_id: Annotated[uuid.UUID, Depends(current_user_id)]) -> MeOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="unknown user")
    rows = (
        await session.execute(
            select(Membership.role, Firm)
            .join(Firm, Firm.id == Membership.firm_id)
            .where(Membership.user_id == user_id)
            .order_by(Firm.name)
        )
    ).all()
    memberships = [
        MembershipOut(firm_id=f.id, firm_name=f.name, firm_slug=f.slug, role=role) for role, f in rows
    ]
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        memberships=memberships,
        active_firm_id=memberships[0].firm_id if memberships else None,
    )
