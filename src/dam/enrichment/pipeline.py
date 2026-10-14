"""Enrichment orchestration (DESIGN.md section 7). Each step is idempotent per asset."""

from __future__ import annotations

import logging
import tempfile
import uuid
from datetime import UTC
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from dam import budget, storage
from dam.config import get_settings
from dam.enrichment import PIPELINE_VERSION, images, video, vision
from dam.enrichment.embeddings import get_embedder, mean_pool
from dam.models import (
    Asset,
    AssetDerived,
    AssetEmbedding,
    AssetKind,
    AssetStatus,
    AssetText,
    Project,
)
from dam.repositories import tags as tag_repo

log = logging.getLogger(__name__)


class EnrichmentFailed(Exception):
    def __init__(self, reason: str, *, retryable: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


async def enrich_asset(session: AsyncSession, asset_id: uuid.UUID) -> None:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        log.info("asset %s gone, skipping", asset_id)
        return
    if asset.status == AssetStatus.uploading:
        raise EnrichmentFailed("upload not complete", retryable=False)
    project = await session.get(Project, asset.project_id)
    vocab = await tag_repo.vocabulary(session, asset.firm_id)

    with tempfile.TemporaryDirectory(prefix="dam-enrich-") as tmp:
        workdir = Path(tmp)
        original = workdir / "original"
        storage.download_to(asset.storage_key, str(original))

        if asset.kind == AssetKind.image:
            frames, derived, timestamps = _process_image(asset, original, workdir)
        else:
            frames, derived, timestamps = _process_video(asset, original, workdir)

        # Derived files to S3 (regenerable; the originals are never touched).
        await _replace_derived(session, asset, derived)

        # Understand.
        try:
            result, usage = vision.describe(
                frames,
                vocab=vocab,
                project_name=project.name if project else "",
                project_phase=project.phase if project else None,
                filename=asset.filename,
                video=asset.kind == AssetKind.video,
                frame_timestamps=timestamps if asset.kind == AssetKind.video else None,
            )
        except vision.VisionRefused as e:
            raise EnrichmentFailed(str(e), retryable=False) from e

        # Embed.
        embedder = get_embedder()
        frame_vectors = embedder.embed_images(frames)
        asset_vector = frame_vectors[0] if len(frame_vectors) == 1 else mean_pool(frame_vectors)

    # Persist everything in one transaction.
    text = asset.text or AssetText(asset_id=asset.id)
    text.caption = result.caption
    text.ocr_text = result.ocr_text or None
    text.colors = result.colors
    text.objects = result.objects
    text.keyframes = (
        [
            {"index": m.frame_index, "timestamp_s": timestamps[m.frame_index], "caption": m.caption}
            for m in result.moments
            if m.frame_index < len(timestamps)
        ]
        if asset.kind == AssetKind.video
        else None
    )
    text.model_version = f"{usage.model}/{vision.PROMPT_VERSION}"
    text.prompt_hash = usage.prompt_hash
    text.input_tokens = usage.input_tokens
    text.output_tokens = usage.output_tokens
    asset.text = text

    proposed = [(t.namespace, t.value, t.confidence) for t in result.tags]
    proposed += [("object", o, 0.8) for o in result.objects[:12]]
    proposed += [("color", c, 0.9) for c in result.colors[:3]]
    await tag_repo.apply_auto_tags(session, asset, proposed, asset.firm_id)

    await session.execute(
        delete(AssetEmbedding).where(
            AssetEmbedding.asset_id == asset.id, AssetEmbedding.model == embedder.model
        )
    )
    session.add(
        AssetEmbedding(
            asset_id=asset.id,
            model=embedder.model,
            frame=-1,
            firm_id=asset.firm_id,
            project_id=asset.project_id,
            timestamp_s=None,
            vector=asset_vector,
        )
    )
    if asset.kind == AssetKind.video:
        for i, vec in enumerate(frame_vectors):
            session.add(
                AssetEmbedding(
                    asset_id=asset.id,
                    model=embedder.model,
                    frame=i,
                    firm_id=asset.firm_id,
                    project_id=asset.project_id,
                    timestamp_s=timestamps[i],
                    vector=vec,
                )
            )

    await budget.record_usage(session, asset.firm_id, usage.input_tokens, usage.output_tokens)
    asset.status = AssetStatus.ready
    asset.failure_reason = None
    asset.pipeline_version = PIPELINE_VERSION
    await session.commit()
    log.info(
        "enriched asset %s kind=%s frames=%d tokens=%d/%d cache_read=%d served_by=%s",
        asset.id,
        asset.kind.value,
        len(frames),
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.served_by,
    )


def _process_image(asset: Asset, original: Path, workdir: Path):
    data = original.read_bytes()
    try:
        info = images.probe(data)
        variants = images.derive(data)
    except Exception as e:  # Pillow raises many types for corrupt input
        raise EnrichmentFailed(f"cannot decode image: {e}", retryable=False) from e
    asset.width, asset.height = info.width, info.height
    asset.exif = info.exif or None
    if info.captured_at and asset.captured_at is None:
        asset.captured_at = info.captured_at.replace(tzinfo=UTC)
    derived = []
    for variant, (blob, w, h) in variants.items():
        key = storage.derived_key(asset.firm_id, asset.id, variant, "webp")
        storage.put_bytes(key, blob, "image/webp")
        derived.append(
            AssetDerived(
                asset_id=asset.id,
                variant=variant,
                storage_key=key,
                mime="image/webp",
                width=w,
                height=h,
            )
        )
    preview = variants["preview"][0]
    return [preview], derived, [0.0]


def _process_video(asset: Asset, original: Path, workdir: Path):
    if not video.ffmpeg_available():
        raise EnrichmentFailed("ffmpeg not installed on worker", retryable=True)
    try:
        info = video.probe(original)
    except Exception as e:
        raise EnrichmentFailed(f"cannot probe video: {e}", retryable=False) from e
    asset.width, asset.height, asset.duration_s = info.width, info.height, info.duration_s
    keyframes = video.extract_keyframes(original, workdir, info.duration_s)
    derived: list[AssetDerived] = []
    frames: list[bytes] = []
    timestamps: list[float] = []
    for kf in keyframes:
        webp = images.to_webp(kf.path.read_bytes())
        frames.append(webp)
        timestamps.append(kf.timestamp_s)
        key = storage.derived_key(asset.firm_id, asset.id, f"keyframe_{kf.index:03d}", "webp")
        storage.put_bytes(key, webp, "image/webp")
        derived.append(
            AssetDerived(
                asset_id=asset.id,
                variant=f"keyframe_{kf.index:03d}",
                storage_key=key,
                mime="image/webp",
                timestamp_s=kf.timestamp_s,
            )
        )
    # Poster + thumb from the first keyframe.
    first = keyframes[0].path.read_bytes()
    for variant, px in (("poster", images.PREVIEW_PX), ("thumb", images.THUMB_PX)):
        blob = images.to_webp(first, px)
        key = storage.derived_key(asset.firm_id, asset.id, variant, "webp")
        storage.put_bytes(key, blob, "image/webp")
        derived.append(AssetDerived(asset_id=asset.id, variant=variant, storage_key=key, mime="image/webp"))
    # Browser-playable preview.
    preview_path = workdir / "preview.mp4"
    video.transcode_preview(original, preview_path)
    key = storage.derived_key(asset.firm_id, asset.id, "preview", "mp4")
    storage.put_file(key, str(preview_path), "video/mp4")
    derived.append(AssetDerived(asset_id=asset.id, variant="preview", storage_key=key, mime="video/mp4"))
    return frames, derived, timestamps


async def _replace_derived(session: AsyncSession, asset: Asset, derived: list[AssetDerived]) -> None:
    asset.derived.clear()  # delete-orphan cascade removes the old rows
    await session.flush()
    asset.derived.extend(derived)
    await session.flush()


async def mark_failed(session: AsyncSession, asset_id: uuid.UUID, reason: str) -> None:
    asset = await session.get(Asset, asset_id)
    if asset is not None:
        asset.status = AssetStatus.failed
        asset.failure_reason = reason[:2000]
        await session.commit()


__all__ = ["enrich_asset", "mark_failed", "EnrichmentFailed", "get_settings"]
