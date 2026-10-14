from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from dam import audit
from dam.deps import CurrentViewer, Session
from dam.models import Project, ProjectAccess
from dam.repositories import assets as asset_repo
from dam.repositories import projects as project_repo
from dam.schemas import (
    ProjectAccessOut,
    ProjectCreate,
    ProjectInvite,
    ProjectOut,
    ProjectUpdate,
)

router = APIRouter(tags=["projects"])


@router.get("/firms/{firm_id}/projects", response_model=list[ProjectOut])
async def list_projects(firm_id: uuid.UUID, session: Session, viewer: CurrentViewer):
    if firm_id != viewer.firm_id:
        raise HTTPException(status_code=404, detail="firm not found")
    projects = await project_repo.list_projects(session, viewer)
    counts = await asset_repo.project_asset_counts(session, viewer, [p.id for p in projects])
    return [_project_out(p, counts.get(p.id, 0)) for p in projects]


@router.post("/firms/{firm_id}/projects", response_model=ProjectOut, status_code=201)
async def create_project(firm_id: uuid.UUID, body: ProjectCreate, session: Session, viewer: CurrentViewer):
    if firm_id != viewer.firm_id:
        raise HTTPException(status_code=404, detail="firm not found")
    viewer.require_staff()
    project = Project(
        firm_id=viewer.firm_id, name=body.name, client_label=body.client_label, phase=body.phase
    )
    session.add(project)
    await session.flush()
    audit.record(session, viewer, "project.create", "project", project.id, {"name": body.name})
    await session.commit()
    return _project_out(project, 0)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, session: Session, viewer: CurrentViewer):
    project = await project_repo.get_project(session, viewer, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    counts = await asset_repo.project_asset_counts(session, viewer, [project.id])
    return _project_out(project, counts.get(project.id, 0))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: uuid.UUID, body: ProjectUpdate, session: Session, viewer: CurrentViewer):
    viewer.require_staff()
    project = await project_repo.get_project(session, viewer, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(project, k, v)
    audit.record(session, viewer, "project.update", "project", project.id, changes)
    await session.commit()
    counts = await asset_repo.project_asset_counts(session, viewer, [project.id])
    return _project_out(project, counts.get(project.id, 0))


@router.get("/projects/{project_id}/access", response_model=list[ProjectAccessOut])
async def list_access(project_id: uuid.UUID, session: Session, viewer: CurrentViewer):
    viewer.require_staff()
    project = await project_repo.get_project(session, viewer, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return [
        ProjectAccessOut(user_id=u.id, email=u.email, name=u.name, role=r)
        for u, r in await project_repo.list_access(session, project)
    ]


@router.post("/projects/{project_id}/access", response_model=ProjectAccessOut, status_code=201)
async def invite(project_id: uuid.UUID, body: ProjectInvite, session: Session, viewer: CurrentViewer):
    """Give a client access to a project, creating the user if needed. No invite email yet."""
    viewer.require_staff()
    project = await project_repo.get_project(session, viewer, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    user, _ = await project_repo.grant_access(session, viewer, project, body.email, body.role)
    audit.record(
        session,
        viewer,
        "project.invite",
        "project",
        project.id,
        {"email": body.email, "role": body.role},
    )
    await session.commit()
    return ProjectAccessOut(user_id=user.id, email=user.email, name=user.name, role=body.role)


@router.delete("/projects/{project_id}/access/{user_id}", status_code=204)
async def revoke(project_id: uuid.UUID, user_id: uuid.UUID, session: Session, viewer: CurrentViewer) -> None:
    viewer.require_staff()
    project = await project_repo.get_project(session, viewer, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    access = await session.get(ProjectAccess, (project.id, user_id))
    if access is not None:
        await session.delete(access)
        audit.record(session, viewer, "project.revoke", "project", project.id, {"user_id": str(user_id)})
        await session.commit()


def _project_out(p: Project, count: int) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        firm_id=p.firm_id,
        name=p.name,
        client_label=p.client_label,
        phase=p.phase,
        status=p.status,
        created_at=p.created_at,
        asset_count=count,
    )
