"""arq worker entrypoints (ADR-006). Run one process per queue:

uv run dam-worker images
uv run dam-worker video
"""

from __future__ import annotations

import logging
import sys
import uuid

from arq import func, run_worker

from dam.db import session_factory
from dam.enrichment.pipeline import EnrichmentFailed, enrich_asset, mark_failed
from dam.queue import IMAGE_QUEUE, VIDEO_QUEUE, redis_settings

log = logging.getLogger(__name__)
MAX_TRIES = 5


async def enrich_asset_job(ctx: dict, asset_id: str) -> None:
    aid = uuid.UUID(asset_id)
    attempt = ctx.get("job_try", 1)
    async with session_factory()() as session:
        try:
            await enrich_asset(session, aid)
        except EnrichmentFailed as e:
            await session.rollback()
            if not e.retryable or attempt >= MAX_TRIES:
                log.warning("asset %s failed permanently: %s", aid, e.reason)
                await mark_failed(session, aid, e.reason)
                return
            log.warning("asset %s attempt %d failed, will retry: %s", aid, attempt, e.reason)
            raise
        except Exception as e:  # noqa: BLE001 - last attempt must leave a reason behind
            await session.rollback()
            if attempt >= MAX_TRIES:
                log.exception("asset %s failed after %d attempts", aid, attempt)
                await mark_failed(session, aid, f"{type(e).__name__}: {e}")
                return
            raise


def _settings(queue: str, *, concurrency: int, timeout: int) -> type:
    return type(
        "WorkerSettings",
        (),
        {
            "functions": [func(enrich_asset_job, name="enrich_asset")],
            "queue_name": queue,
            "redis_settings": redis_settings(),
            "max_jobs": concurrency,
            "job_timeout": timeout,
            "max_tries": MAX_TRIES,
            "retry_jobs": True,
        },
    )


ImageWorker = _settings(IMAGE_QUEUE, concurrency=8, timeout=600)
VideoWorker = _settings(VIDEO_QUEUE, concurrency=2, timeout=3600)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    which = sys.argv[1] if len(sys.argv) > 1 else "images"
    settings = {"images": ImageWorker, "video": VideoWorker}.get(which)
    if settings is None:
        sys.exit("usage: dam-worker [images|video]")
    run_worker(settings)  # type: ignore[arg-type]
