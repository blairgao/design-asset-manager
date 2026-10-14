from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dam import storage
from dam.models import Asset, AssetKind, AssetStatus, AssetTag, Favorite, TagSource
from dam.schemas import AssetOut, DerivedOut, TagOut
from dam.viewer import Viewer

IMAGE_MIMES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/webp": "webp",
    "image/tiff": "tiff",
}
VIDEO_MIMES = {"video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm"}


def kind_for_mime(mime: str) -> AssetKind | None:
    if mime in IMAGE_MIMES:
        return AssetKind.image
    if mime in VIDEO_MIMES:
        return AssetKind.video
    return None


async def get_asset(session: AsyncSession, viewer: Viewer, asset_id: uuid.UUID) -> Asset | None:
    stmt = viewer.scope_assets(select(Asset).where(Asset.id == asset_id))
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_assets(
    session: AsyncSession, viewer: Viewer, asset_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Asset]:
    if not asset_ids:
        return {}
    stmt = viewer.scope_assets(select(Asset).where(Asset.id.in_(asset_ids)))
    return {a.id: a for a in (await session.execute(stmt)).scalars().all()}


async def find_duplicate(session: AsyncSession, viewer: Viewer, sha256: str) -> Asset | None:
    stmt = (
        select(Asset)
        .where(
            Asset.firm_id == viewer.firm_id,
            Asset.sha256 == sha256,
            Asset.status == AssetStatus.ready,
            Asset.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def encode_cursor(created_at: datetime, asset_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": str(asset_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["id"])
    except (ValueError, KeyError, TypeError):
        return None


async def list_assets(
    session: AsyncSession,
    viewer: Viewer,
    *,
    project_id: uuid.UUID | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[Asset], str | None]:
    stmt = viewer.scope_assets(select(Asset))
    if project_id is not None:
        stmt = stmt.where(Asset.project_id == project_id)
    after = decode_cursor(cursor)
    if after:
        t, aid = after
        stmt = stmt.where((Asset.created_at < t) | ((Asset.created_at == t) & (Asset.id < aid)))
    stmt = stmt.order_by(Asset.created_at.desc(), Asset.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).scalars().all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
    return list(rows), next_cursor


async def favorites_for(session: AsyncSession, viewer: Viewer, asset_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not asset_ids:
        return set()
    stmt = select(Favorite.asset_id).where(
        Favorite.user_id == viewer.user_id, Favorite.asset_id.in_(asset_ids)
    )
    return set((await session.execute(stmt)).scalars().all())


async def project_asset_counts(
    session: AsyncSession, viewer: Viewer, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not project_ids:
        return {}
    stmt = viewer.scope_assets(
        select(Asset.project_id, func.count(Asset.id)).where(Asset.project_id.in_(project_ids))
    ).group_by(Asset.project_id)
    return {pid: n for pid, n in (await session.execute(stmt)).all()}


def _visible_tags(asset: Asset) -> list[AssetTag]:
    return [t for t in asset.tags if not t.suppressed]


def to_out(asset: Asset, *, favorited: bool = False) -> AssetOut:
    derived = [
        DerivedOut(
            variant=d.variant,
            url=storage.derived_url(d.storage_key),
            width=d.width,
            height=d.height,
            timestamp_s=d.timestamp_s,
        )
        for d in asset.derived
    ]
    by_variant = {d.variant: d.url for d in derived}
    text = asset.text
    return AssetOut(
        id=asset.id,
        project_id=asset.project_id,
        kind=asset.kind,
        status=asset.status,
        filename=asset.filename,
        mime=asset.mime,
        bytes=asset.bytes,
        width=asset.width,
        height=asset.height,
        duration_s=asset.duration_s,
        internal_only=asset.internal_only,
        captured_at=asset.captured_at,
        created_at=asset.created_at,
        uploader_id=asset.uploader_id,
        caption=text.caption if text else None,
        ocr_text=text.ocr_text if text else None,
        colors=text.colors if text else None,
        tags=[
            TagOut(
                id=t.tag_id,
                namespace=t.tag.namespace,
                value=t.tag.value,
                source=t.source,
                confidence=t.confidence,
            )
            for t in sorted(_visible_tags(asset), key=lambda t: (t.tag.namespace, t.tag.value))
        ],
        thumb_url=by_variant.get("thumb") or by_variant.get("poster"),
        preview_url=by_variant.get("preview"),
        derived=derived,
        failure_reason=asset.failure_reason,
        favorited=favorited,
    )


async def soft_delete(session: AsyncSession, asset: Asset) -> None:
    asset.deleted_at = datetime.now(UTC)
    await session.flush()


def manual_tag_count(asset: Asset) -> int:
    return sum(1 for t in asset.tags if t.source == TagSource.manual and not t.suppressed)


async def clone_enrichment(session: AsyncSession, src: Asset, dst: Asset) -> None:
    """Copy derived files, text, auto tags, and embeddings from a duplicate asset.

    Storage objects are shared, not copied; only rows are duplicated.
    """
    from dam.models import AssetDerived, AssetEmbedding, AssetText

    dst.width, dst.height, dst.duration_s = src.width, src.height, src.duration_s
    dst.captured_at, dst.exif, dst.pipeline_version = (
        src.captured_at,
        src.exif,
        src.pipeline_version,
    )
    for d in src.derived:
        session.add(
            AssetDerived(
                asset_id=dst.id,
                variant=d.variant,
                storage_key=d.storage_key,
                mime=d.mime,
                width=d.width,
                height=d.height,
                timestamp_s=d.timestamp_s,
            )
        )
    if src.text:
        t = src.text
        session.add(
            AssetText(
                asset_id=dst.id,
                caption=t.caption,
                ocr_text=t.ocr_text,
                colors=t.colors,
                objects=t.objects,
                keyframes=t.keyframes,
                model_version=t.model_version,
                prompt_hash=t.prompt_hash,
            )
        )
    for t in src.tags:
        if t.source == TagSource.auto:
            session.add(
                AssetTag(
                    asset_id=dst.id,
                    tag_id=t.tag_id,
                    firm_id=dst.firm_id,
                    source=TagSource.auto,
                    confidence=t.confidence,
                )
            )
    rows = (
        (await session.execute(select(AssetEmbedding).where(AssetEmbedding.asset_id == src.id)))
        .scalars()
        .all()
    )
    for e in rows:
        session.add(
            AssetEmbedding(
                asset_id=dst.id,
                model=e.model,
                frame=e.frame,
                firm_id=dst.firm_id,
                project_id=dst.project_id,
                timestamp_s=e.timestamp_s,
                vector=e.vector,
            )
        )
    await session.flush()
