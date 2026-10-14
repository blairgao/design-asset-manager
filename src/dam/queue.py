"""Job queue (ADR-006). Two arq queues so video never starves images."""

from __future__ import annotations

import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from dam.config import get_settings
from dam.models import AssetKind

IMAGE_QUEUE = "dam:images"
VIDEO_QUEUE = "dam:video"

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


def queue_for(kind: AssetKind) -> str:
    return VIDEO_QUEUE if kind == AssetKind.video else IMAGE_QUEUE


async def enqueue_enrich(asset_id: uuid.UUID, kind: AssetKind, *, priority_low: bool = False) -> None:
    pool = await get_pool()
    # arq jobs are idempotent by job_id: a second enqueue for the same asset is a no-op
    # until the first finishes. Low priority jobs are deferred by 10 minutes.
    await pool.enqueue_job(
        "enrich_asset",
        str(asset_id),
        _queue_name=queue_for(kind),
        _job_id=f"enrich:{asset_id}",
        _defer_by=600 if priority_low else None,
    )
