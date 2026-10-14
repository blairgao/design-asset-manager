from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from dam import audit, budget, storage
from dam.config import get_settings
from dam.deps import CurrentViewer, Session
from dam.models import Asset, AssetKind, AssetStatus
from dam.queue import enqueue_enrich
from dam.repositories import assets as asset_repo
from dam.repositories import projects as project_repo
from dam.schemas import UploadComplete, UploadSessionOut, UploadStart

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", response_model=UploadSessionOut, status_code=201)
async def start_upload(body: UploadStart, session: Session, viewer: CurrentViewer):
    settings = get_settings()
    project = await project_repo.get_project(session, viewer, body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    viewer.require_edit(project.id)
    kind = asset_repo.kind_for_mime(body.mime)
    if kind is None:
        raise HTTPException(status_code=415, detail=f"unsupported media type {body.mime}")
    limit = settings.max_video_bytes if kind == AssetKind.video else settings.max_image_bytes
    if body.size > limit:
        raise HTTPException(status_code=413, detail=f"file exceeds {limit} bytes")

    asset = Asset(
        firm_id=viewer.firm_id,
        project_id=project.id,
        uploader_id=viewer.user_id,
        kind=kind,
        status=AssetStatus.uploading,
        filename=body.filename,
        mime=body.mime,
        bytes=body.size,
        sha256=body.sha256,
        storage_key="",
    )
    session.add(asset)
    await session.flush()

    if body.sha256:
        duplicate = await asset_repo.find_duplicate(session, viewer, body.sha256)
        if duplicate is not None:
            # Same bytes already in this firm: reuse the object, copy the enrichment.
            asset.storage_key = duplicate.storage_key
            asset.status = duplicate.status
            await asset_repo.clone_enrichment(session, duplicate, asset)
            audit.record(
                session,
                viewer,
                "asset.dedupe",
                "asset",
                asset.id,
                {"duplicate_of": str(duplicate.id)},
            )
            await session.commit()
            return UploadSessionOut(
                asset_id=asset.id, upload_id=None, part_size=0, part_urls=[], deduplicated=True
            )

    asset.storage_key = storage.original_key(viewer.firm_id, asset.id, body.filename)
    mp = await run_in_threadpool(storage.start_multipart, asset.storage_key, body.mime, body.size)
    asset.upload_id = mp.upload_id
    audit.record(
        session,
        viewer,
        "asset.upload_start",
        "asset",
        asset.id,
        {"filename": body.filename, "bytes": body.size},
    )
    await session.commit()
    return UploadSessionOut(
        asset_id=asset.id, upload_id=mp.upload_id, part_size=mp.part_size, part_urls=mp.part_urls
    )


async def _own_upload(session, viewer, asset_id: uuid.UUID) -> Asset:
    asset = await asset_repo.get_asset(session, viewer, asset_id)
    if asset is None or asset.status != AssetStatus.uploading:
        raise HTTPException(status_code=404, detail="upload not found")
    if asset.uploader_id != viewer.user_id and viewer.is_client:
        raise HTTPException(status_code=403, detail="not your upload")
    return asset


@router.post("/{asset_id}/complete", status_code=202)
async def complete_upload(
    asset_id: uuid.UUID, body: UploadComplete, session: Session, viewer: CurrentViewer
) -> dict:
    asset = await _own_upload(session, viewer, asset_id)
    if asset.upload_id and body.parts:
        await run_in_threadpool(
            storage.complete_multipart,
            asset.storage_key,
            asset.upload_id,
            [p.model_dump() for p in body.parts],
        )
    meta = await run_in_threadpool(storage.head, asset.storage_key)
    if meta is None:
        raise HTTPException(status_code=409, detail="object not found in storage")
    size = int(meta.get("ContentLength", 0))
    if size != asset.bytes:
        raise HTTPException(status_code=409, detail=f"size mismatch: expected {asset.bytes}, stored {size}")
    if body.sha256:
        asset.sha256 = body.sha256
    asset.status = AssetStatus.processing
    asset.upload_id = None
    low = await budget.over_budget(session, viewer.firm_id)
    audit.record(session, viewer, "asset.upload_complete", "asset", asset.id)
    await session.commit()
    await enqueue_enrich(asset.id, asset.kind, priority_low=low)
    return {"status": "processing", "deferred": low}


@router.delete("/{asset_id}", status_code=204)
async def abort_upload(asset_id: uuid.UUID, session: Session, viewer: CurrentViewer) -> None:
    asset = await _own_upload(session, viewer, asset_id)
    if asset.upload_id:
        await run_in_threadpool(storage.abort_multipart, asset.storage_key, asset.upload_id)
    await session.delete(asset)
    await session.commit()
