from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from dam.config import get_settings
from dam.deps import CurrentViewer, Session
from dam.enrichment.embeddings import get_embedder
from dam.models import Asset
from dam.repositories import assets as asset_repo
from dam.repositories import search as search_repo
from dam.repositories import tags as tag_repo
from dam.schemas import FacetsResponse, FacetValue, SearchHit, SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(body: SearchRequest, session: Session, viewer: CurrentViewer):
    if body.filters.project_id:
        for pid in body.filters.project_id:
            if not viewer.can_read_project(pid):
                raise HTTPException(status_code=404, detail="project not found")

    if not body.q and body.similar_to is None:
        return await _browse(body, session, viewer)

    model = get_settings().embedding_model
    query_tags: list[tuple[str, str]] = []
    if body.similar_to is not None:
        vec = await search_repo.asset_vector(session, viewer, body.similar_to, model)
        if vec is None:
            raise HTTPException(status_code=404, detail="asset has no embedding yet")
        mode = "similar"
    else:
        embedder = get_embedder()
        vec = (await run_in_threadpool(embedder.embed_text, [body.q or ""]))[0]
        vocab = await tag_repo.vocabulary(session, viewer.firm_id)
        query_tags = search_repo.extract_query_tags(body.q or "", vocab)
        mode = "semantic"

    offset = search_repo.decode_offset(body.cursor)
    candidates = await search_repo.vector_candidates(
        session,
        viewer,
        body.filters,
        vec,
        model,
        limit=offset + body.limit,
        exclude_asset=body.similar_to,
    )
    ids = [c.asset_id for c in candidates]
    assets = await asset_repo.get_assets(session, viewer, ids)
    tags = await search_repo.tags_for_assets(session, ids)
    ranked = search_repo.rerank(
        [c for c in candidates if c.asset_id in assets],
        tags,
        {aid: a.created_at for aid, a in assets.items()},
        query_tags,
    )
    page = ranked[offset : offset + body.limit]
    favs = await asset_repo.favorites_for(session, viewer, [r.asset_id for r in page])
    hits = [
        SearchHit(
            asset=asset_repo.to_out(assets[r.asset_id], favorited=r.asset_id in favs),
            score=r.score,
            matched_tags=r.matched_tags,
            matched_timestamp_s=r.timestamp_s,
        )
        for r in page
    ]
    next_cursor = (
        search_repo.encode_offset(offset + body.limit) if len(ranked) > offset + body.limit else None
    )
    return SearchResponse(hits=hits, next_cursor=next_cursor, mode=mode)


async def _browse(body: SearchRequest, session, viewer) -> SearchResponse:
    stmt = search_repo.apply_filters(select(Asset), viewer, body.filters)
    after = asset_repo.decode_cursor(body.cursor)
    if after:
        t, aid = after
        stmt = stmt.where((Asset.created_at < t) | ((Asset.created_at == t) & (Asset.id < aid)))
    stmt = stmt.order_by(Asset.created_at.desc(), Asset.id.desc()).limit(body.limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > body.limit:
        rows = rows[: body.limit]
        next_cursor = asset_repo.encode_cursor(rows[-1].created_at, rows[-1].id)
    favs = await asset_repo.favorites_for(session, viewer, [a.id for a in rows])
    hits = [SearchHit(asset=asset_repo.to_out(a, favorited=a.id in favs), score=0.0) for a in rows]
    return SearchResponse(hits=hits, next_cursor=next_cursor, mode="browse")


@router.get("/facets", response_model=FacetsResponse)
async def facets(
    session: Session,
    viewer: CurrentViewer,
    project_id: Annotated[list[uuid.UUID] | None, Query()] = None,
):
    if project_id:
        for pid in project_id:
            if not viewer.can_read_project(pid):
                raise HTTPException(status_code=404, detail="project not found")
    data = await tag_repo.facets(session, viewer, project_id)
    return FacetsResponse(
        facets={ns: [FacetValue(value=v, count=n) for v, n in vals] for ns, vals in data.items()}
    )
