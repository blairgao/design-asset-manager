from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dam.models import FirmRole, Membership, Project, ProjectAccess, ProjectRole, User
from dam.viewer import Viewer


async def list_projects(session: AsyncSession, viewer: Viewer) -> list[Project]:
    stmt = select(Project).where(Project.firm_id == viewer.firm_id).order_by(Project.created_at.desc())
    if viewer.is_client:
        stmt = stmt.where(Project.id.in_(list(viewer.project_roles)))
    return list((await session.execute(stmt)).scalars().all())


async def get_project(session: AsyncSession, viewer: Viewer, project_id: uuid.UUID) -> Project | None:
    if not viewer.can_read_project(project_id):
        return None
    stmt = select(Project).where(Project.id == project_id, Project.firm_id == viewer.firm_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def grant_access(
    session: AsyncSession, viewer: Viewer, project: Project, email: str, role: ProjectRole
) -> tuple[User, bool]:
    """Ensure a user exists, is a client member of the firm, and has access to the project.

    Returns (user, created_user).
    """
    email = email.lower().strip()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    created = user is None
    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()
    membership = await session.get(Membership, (user.id, viewer.firm_id))
    if membership is None:
        session.add(Membership(user_id=user.id, firm_id=viewer.firm_id, role=FirmRole.client))
    access = await session.get(ProjectAccess, (project.id, user.id))
    if access is None:
        session.add(ProjectAccess(project_id=project.id, user_id=user.id, role=role))
    else:
        access.role = role
    await session.flush()
    return user, created


async def list_access(session: AsyncSession, project: Project) -> list[tuple[User, ProjectRole]]:
    stmt = (
        select(User, ProjectAccess.role)
        .join(ProjectAccess, ProjectAccess.user_id == User.id)
        .where(ProjectAccess.project_id == project.id)
        .order_by(User.email)
    )
    return [(u, r) for u, r in (await session.execute(stmt)).all()]
