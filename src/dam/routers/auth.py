from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from dam import auth, mail
from dam.config import get_settings
from dam.deps import Session, current_user_id
from dam.models import Firm, Membership, User
from dam.schemas import MagicLinkRequest, MembershipOut, MeOut

router = APIRouter(tags=["auth"])


@router.post("/auth/magic-link", status_code=202)
async def request_magic_link(body: MagicLinkRequest, session: Session) -> dict:
    """Always 202, whether or not the address is known, to avoid account enumeration."""
    user = (await session.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is not None:
        token = await auth.create_magic_link(session, body.email)
        await session.commit()
        await mail.send_mail(
            body.email,
            "Your sign-in link",
            f"Sign in to Design Asset Manager:\n\n{auth.magic_link_url(token)}\n\n"
            "This link works once and expires in 15 minutes.",
        )
    return {"status": "sent"}


@router.get("/auth/verify", include_in_schema=False)
async def verify(token: str, session: Session):
    result = await auth.redeem_magic_link(session, token)
    if result is None:
        raise HTTPException(status_code=400, detail="link is invalid or expired")
    user, link = result
    # An invite link carries firm and project. Membership and access were created when the
    # invite was issued; nothing else to do here beyond signing the user in.
    await session.commit()
    settings = get_settings()
    target = settings.web_origin
    if link.project_id:
        target = f"{settings.web_origin}/projects/{link.project_id}"
    response = RedirectResponse(target, status_code=303)
    _set_cookie(response, user.id)
    return response


@router.post("/auth/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(auth.SESSION_COOKIE)


def _set_cookie(response: Response, user_id: uuid.UUID) -> None:
    settings = get_settings()
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.issue_session(user_id),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.env in ("staging", "prod"),
        samesite="lax",
    )


@router.get("/me", response_model=MeOut)
async def me(session: Session, user_id: Annotated[uuid.UUID, Depends(current_user_id)]) -> MeOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="unknown user")
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
