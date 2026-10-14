from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from dam import audit, budget, storage
from dam.config import get_settings
from dam.deps import CurrentViewer, Session
from dam.models import AssetStatus, AssetText, Comment, Favorite, User
from dam.queue import enqueue_enrich
from dam.repositories import assets as asset_repo
from dam.repositories import projects as project_repo
from dam.repositories import tags as tag_repo
from dam.schemas import (
    AssetDownloadOut,
    AssetOut,
    AssetUpdate,
    CommentCreate,
    CommentOut,
    Page,
    TagAdd,
    TagOut,
)

router = APIRouter(prefix="/assets", tags=["assets"])


async def _load(session, viewer, asset_id: uuid.UUID):
    asset = await asset_repo.get_asset(session, viewer, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


@router.get("", response_model=Page[AssetOut])
async def list_assets(
    session: Session,
    viewer: CurrentViewer,
    project_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
):
    if project_id is not None and not viewer.can_read_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    rows, next_cursor = await asset_repo.list_assets(
        session, viewer, project_id=project_id, limit=limit, cursor=cursor
    )
    favs = await asset_repo.favorites_for(session, viewer, [a.id for a in rows])
    return Page(items=[asset_repo.to_out(a, favorited=a.id in favs) for a in rows], next_cursor=next_cursor)


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: uuid.UUID, session: Session, viewer: CurrentViewer):
    asset = await _load(session, viewer, asset_id)
    favs = await asset_repo.favorites_for(session, viewer, [asset.id])
    return asset_repo.to_out(asset, favorited=asset.id in favs)


@router.patch("/{asset_id}", response_model=AssetOut)
async def update_asset(asset_id: uuid.UUID, body: AssetUpdate, session: Session, viewer: CurrentViewer):
    asset = await _load(session, viewer, asset_id)
    viewer.require_edit(asset.project_id)
    changes = body.model_dump(exclude_unset=True)
    if "internal_only" in changes:
        viewer.require_staff()
    if "project_id" in changes and changes["project_id"] is not None:
        target = await project_repo.get_project(session, viewer, changes["project_id"])
        if target is None:
            raise HTTPException(status_code=404, detail="target project not found")
        viewer.require_edit(target.id)
        asset.project_id = target.id
        from dam.models import AssetEmbedding

        for e in (
            await session.execute(select(AssetEmbedding).where(AssetEmbedding.asset_id == asset.id))
        ).scalars():
            e.project_id = target.id
    if "caption" in changes:
        if asset.text is None:
            asset.text = AssetText(asset_id=asset.id)
        asset.text.caption = changes["caption"]
    for key in ("internal_only", "captured_at"):
        if key in changes:
            setattr(asset, key, changes[key])
    audit.record(
        session,
        viewer,
        "asset.update",
        "asset",
        asset.id,
        {k: (str(v) if v is not None else None) for k, v in changes.items()},
    )
    await session.commit()
    return asset_repo.to_out(asset)


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(asset_id: uuid.UUID, session: Session, viewer: CurrentViewer) -> None:
    asset = await _load(session, viewer, asset_id)
    viewer.require_edit(asset.project_id)
    if viewer.is_client and asset.uploader_id != viewer.user_id:
        raise HTTPException(status_code=403, detail="clients can only delete their own uploads")
    await asset_repo.soft_delete(session, asset)
    audit.record(session, viewer, "asset.delete", "asset", asset.id)
    await session.commit()


@router.get("/{asset_id}/download", response_model=AssetDownloadOut)
async def download(asset_id: uuid.UUID, session: Session, viewer: CurrentViewer):
    asset = await _load(session, viewer, asset_id)
    if viewer.is_client and asset.kind.value == "image":
        # Clients get the EXIF-stripped preview rather than the raw original (privacy).
        preview = next((d for d in asset.derived if d.variant == "preview"), None)
        if preview is not None:
            url = await run_in_threadpool(storage.presigned_get, preview.storage_key, filename=asset.filename)
            return AssetDownloadOut(url=url, expires_in=get_settings().presign_ttl_seconds)
    url = await run_in_threadpool(storage.presigned_get, asset.storage_key, filename=asset.filename)
    audit.record(session, viewer, "asset.download", "asset", asset.id)
    await session.commit()
    return AssetDownloadOut(url=url, expires_in=get_settings().presign_ttl_seconds)


@router.post("/{asset_id}/tags", response_model=TagOut, status_code=201)
async def add_tag(asset_id: uuid.UUID, body: TagAdd, session: Session, viewer: CurrentViewer):
    asset = await _load(session, viewer, asset_id)
    viewer.require_edit(asset.project_id)
    row = await tag_repo.add_manual_tag(session, viewer, asset, body.namespace, body.value)
    audit.record(
        session,
        viewer,
        "asset.tag_add",
        "asset",
        asset.id,
        {"namespace": body.namespace, "value": body.value},
    )
    await session.commit()
    await session.refresh(row)
    return TagOut(
        id=row.tag_id,
        namespace=row.tag.namespace,
        value=row.tag.value,
        source=row.source,
        confidence=row.confidence,
    )


@router.delete("/{asset_id}/tags/{tag_id}", status_code=204)
async def remove_tag(asset_id: uuid.UUID, tag_id: uuid.UUID, session: Session, viewer: CurrentViewer) -> None:
    asset = await _load(session, viewer, asset_id)
    viewer.require_edit(asset.project_id)
    if not await tag_repo.remove_tag(session, viewer, asset, tag_id):
        raise HTTPException(status_code=404, detail="tag not on asset")
    audit.record(session, viewer, "asset.tag_remove", "asset", asset.id, {"tag_id": str(tag_id)})
    await session.commit()


@router.post("/{asset_id}/reprocess", status_code=202)
async def reprocess(asset_id: uuid.UUID, session: Session, viewer: CurrentViewer) -> dict:
    asset = await _load(session, viewer, asset_id)
    viewer.require_staff()
    if asset.status == AssetStatus.uploading:
        raise HTTPException(status_code=409, detail="upload not complete")
    asset.status = AssetStatus.processing
    asset.failure_reason = None
    low = await budget.over_budget(session, viewer.firm_id)
    audit.record(session, viewer, "asset.reprocess", "asset", asset.id)
    await session.commit()
    await enqueue_enrich(asset.id, asset.kind, priority_low=low)
    return {"status": "processing", "deferred": low}


@router.put("/{asset_id}/favorite", status_code=204)
async def favorite(asset_id: uuid.UUID, session: Session, viewer: CurrentViewer) -> None:
    asset = await _load(session, viewer, asset_id)
    if await session.get(Favorite, (asset.id, viewer.user_id)) is None:
        session.add(Favorite(asset_id=asset.id, user_id=viewer.user_id))
        await session.commit()


@router.delete("/{asset_id}/favorite", status_code=204)
async def unfavorite(asset_id: uuid.UUID, session: Session, viewer: CurrentViewer) -> None:
    asset = await _load(session, viewer, asset_id)
    fav = await session.get(Favorite, (asset.id, viewer.user_id))
    if fav is not None:
        await session.delete(fav)
        await session.commit()


@router.get("/{asset_id}/comments", response_model=list[CommentOut])
async def list_comments(asset_id: uuid.UUID, session: Session, viewer: CurrentViewer):
    asset = await _load(session, viewer, asset_id)
    rows = (
        await session.execute(
            select(Comment, User.name, User.email)
            .outerjoin(User, User.id == Comment.author_id)
            .where(Comment.asset_id == asset.id)
            .order_by(Comment.created_at)
        )
    ).all()
    return [
        CommentOut(
            id=c.id,
            asset_id=c.asset_id,
            author_id=c.author_id,
            author_name=name or email,
            body=c.body,
            created_at=c.created_at,
        )
        for c, name, email in rows
    ]


@router.post("/{asset_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(asset_id: uuid.UUID, body: CommentCreate, session: Session, viewer: CurrentViewer):
    asset = await _load(session, viewer, asset_id)
    comment = Comment(firm_id=viewer.firm_id, asset_id=asset.id, author_id=viewer.user_id, body=body.body)
    session.add(comment)
    await session.flush()
    await session.commit()
    user = await session.get(User, viewer.user_id)
    return CommentOut(
        id=comment.id,
        asset_id=asset.id,
        author_id=viewer.user_id,
        author_name=(user.name or user.email) if user else None,
        body=comment.body,
        created_at=comment.created_at,
    )
