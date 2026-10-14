"""The resolved caller. Every repository function takes a Viewer and scopes by it (ADR-009)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from dam.models import Asset, FirmRole, Membership, ProjectAccess, ProjectRole


class Forbidden(Exception):
    pass


@dataclass(frozen=True)
class Viewer:
    user_id: uuid.UUID
    firm_id: uuid.UUID
    role: FirmRole
    # Only populated for clients. Staff and admins see every project in the firm.
    project_roles: dict[uuid.UUID, ProjectRole] = field(default_factory=dict)

    @property
    def is_client(self) -> bool:
        return self.role == FirmRole.client

    @property
    def is_admin(self) -> bool:
        return self.role == FirmRole.admin

    def can_read_project(self, project_id: uuid.UUID) -> bool:
        return not self.is_client or project_id in self.project_roles

    def can_edit_project(self, project_id: uuid.UUID) -> bool:
        if not self.is_client:
            return True
        return self.project_roles.get(project_id) == ProjectRole.editor

    def require_read(self, project_id: uuid.UUID) -> None:
        if not self.can_read_project(project_id):
            raise Forbidden("no access to project")

    def require_edit(self, project_id: uuid.UUID) -> None:
        if not self.can_edit_project(project_id):
            raise Forbidden("no edit access to project")

    def require_staff(self) -> None:
        if self.is_client:
            raise Forbidden("staff only")

    def require_admin(self) -> None:
        if not self.is_admin:
            raise Forbidden("admin only")

    def scope_assets(self, stmt: Select) -> Select:
        """Apply tenant and project scoping to any query selecting from Asset."""
        stmt = stmt.where(Asset.firm_id == self.firm_id, Asset.deleted_at.is_(None))
        if self.is_client:
            stmt = stmt.where(Asset.project_id.in_(list(self.project_roles)), Asset.internal_only.is_(False))
        return stmt


async def resolve_viewer(
    session: AsyncSession, user_id: uuid.UUID, firm_id: uuid.UUID | None
) -> Viewer | None:
    memberships = (
        (await session.execute(select(Membership).where(Membership.user_id == user_id))).scalars().all()
    )
    if not memberships:
        return None
    if firm_id is None:
        membership = memberships[0]
    else:
        membership = next((m for m in memberships if m.firm_id == firm_id), None)
        if membership is None:
            return None
    project_roles: dict[uuid.UUID, ProjectRole] = {}
    if membership.role == FirmRole.client:
        from dam.models import Project

        rows = await session.execute(
            select(ProjectAccess.project_id, ProjectAccess.role)
            .join(Project, Project.id == ProjectAccess.project_id)
            .where(ProjectAccess.user_id == user_id, Project.firm_id == membership.firm_id)
        )
        project_roles = {pid: role for pid, role in rows.all()}
    return Viewer(
        user_id=user_id,
        firm_id=membership.firm_id,
        role=membership.role,
        project_roles=project_roles,
    )
