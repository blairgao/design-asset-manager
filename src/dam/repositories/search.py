"""Semantic, similar-image, and browse search (DESIGN.md section 8)."""

from __future__ import annotations

import base64
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from dam.models import Asset, AssetEmbedding, AssetTag, Favorite, Tag
from dam.repositories import assets as asset_repo
from dam.schemas import SearchFilters
from dam.viewer import Viewer

CANDIDATE_MULTIPLIER = 4
MAX_CANDIDATES = 200


@dataclass
class Candidate:
    asset_id: uuid.UUID
    distance: float
    timestamp_s: float | None = None


@dataclass
class Ranked:
    asset_id: uuid.UUID
    score: float
    matched_tags: list[str] = field(default_factory=list)
    timestamp_s: float | None = None


# --- query understanding -----------------------------------------------------

_word = re.compile(r"[a-z0-9][a-z0-9\-]*")


def extract_query_tags(q: str, vocabulary: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Find controlled-vocabulary values mentioned in free text.

    Multi-word values match as phrases; single words match as whole tokens.
    """
    text = " " + " ".join(_word.findall(q.lower())) + " "
    found: list[tuple[str, str]] = []
    for ns, values in vocabulary.items():
        for value in values:
            needle = " " + " ".join(_word.findall(value.lower())) + " "
            if len(needle.strip()) >= 3 and needle in text:
                found.append((ns, value))
    return found


# --- filters -----------------------------------------------------------------

TAG_FILTER_NAMESPACES = ("room", "phase", "style", "material", "color", "object")


def apply_filters(stmt: Select, viewer: Viewer, filters: SearchFilters) -> Select:
    stmt = viewer.scope_assets(stmt)
    if filters.project_id:
        stmt = stmt.where(Asset.project_id.in_(filters.project_id))
    if filters.kind:
        stmt = stmt.where(Asset.kind == filters.kind)
    if filters.status:
        stmt = stmt.where(Asset.status == filters.status)
    if filters.favorites_only:
        stmt = stmt.where(exists().where(Favorite.asset_id == Asset.id, Favorite.user_id == viewer.user_id))
    for ns in TAG_FILTER_NAMESPACES:
        values = getattr(filters, ns)
        if values:
            stmt = stmt.where(
                exists()
                .where(AssetTag.asset_id == Asset.id, AssetTag.suppressed.is_(False))
                .where(AssetTag.tag_id == Tag.id, Tag.namespace == ns)
                .where(Tag.value.in_([v.lower() for v in values]))
            )
    return stmt


# --- candidate retrieval -----------------------------------------------------


async def vector_candidates(
    session: AsyncSession,
    viewer: Viewer,
    filters: SearchFilters,
    query_vector: list[float],
    model: str,
    *,
    limit: int,
    exclude_asset: uuid.UUID | None = None,
) -> list[Candidate]:
    distance = AssetEmbedding.vector.cosine_distance(query_vector)
    stmt = (
        select(AssetEmbedding.asset_id, distance.label("d"), AssetEmbedding.timestamp_s)
        .join(Asset, Asset.id == AssetEmbedding.asset_id)
        .where(AssetEmbedding.model == model, AssetEmbedding.firm_id == viewer.firm_id)
    )
    stmt = apply_filters(stmt, viewer, filters)
    if exclude_asset is not None:
        stmt = stmt.where(AssetEmbedding.asset_id != exclude_asset)
    # Over-fetch so per-keyframe rows collapse to enough distinct assets.
    stmt = stmt.order_by(distance).limit(min(MAX_CANDIDATES, limit * CANDIDATE_MULTIPLIER) * 2)
    rows = (await session.execute(stmt)).all()
    best: dict[uuid.UUID, Candidate] = {}
    for asset_id, d, ts in rows:
        if asset_id not in best:
            best[asset_id] = Candidate(asset_id=asset_id, distance=float(d), timestamp_s=ts)
    return list(best.values())


async def asset_vector(
    session: AsyncSession, viewer: Viewer, asset_id: uuid.UUID, model: str
) -> list[float] | None:
    asset = await asset_repo.get_asset(session, viewer, asset_id)
    if asset is None:
        return None
    stmt = select(AssetEmbedding.vector).where(
        AssetEmbedding.asset_id == asset_id,
        AssetEmbedding.model == model,
        AssetEmbedding.frame == -1,
    )
    vec = (await session.execute(stmt)).scalar_one_or_none()
    return list(vec) if vec is not None else None


# --- ranking -----------------------------------------------------------------


def recency_prior(created_at: datetime, now: datetime | None = None) -> float:
    """1.0 for brand new, decaying to ~0.37 after a year."""
    now = now or datetime.now(UTC)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400)
    return math.exp(-age_days / 365)


def rerank(
    candidates: list[Candidate],
    asset_tags: dict[uuid.UUID, set[tuple[str, str]]],
    created_at: dict[uuid.UUID, datetime],
    query_tags: list[tuple[str, str]],
    *,
    w_vector: float = 0.75,
    w_tags: float = 0.20,
    w_recency: float = 0.05,
) -> list[Ranked]:
    """Blend vector similarity, exact tag hits from the query, and a recency prior."""
    wanted = set(query_tags)
    out: list[Ranked] = []
    now = datetime.now(UTC)
    for c in candidates:
        sim = max(0.0, 1.0 - c.distance)
        hits = sorted(wanted & asset_tags.get(c.asset_id, set()))
        tag_score = len(hits) / len(wanted) if wanted else 0.0
        rec = recency_prior(created_at[c.asset_id], now) if c.asset_id in created_at else 0.0
        score = w_vector * sim + w_tags * tag_score + w_recency * rec
        out.append(
            Ranked(
                asset_id=c.asset_id,
                score=round(score, 5),
                matched_tags=[f"{ns}:{v}" for ns, v in hits],
                timestamp_s=c.timestamp_s,
            )
        )
    out.sort(key=lambda r: r.score, reverse=True)
    return out


def encode_offset(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def decode_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(cursor.encode()))["o"])
    except (ValueError, KeyError, TypeError):
        return 0


async def tags_for_assets(
    session: AsyncSession, asset_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[tuple[str, str]]]:
    if not asset_ids:
        return {}
    stmt = (
        select(AssetTag.asset_id, Tag.namespace, Tag.value)
        .join(Tag, Tag.id == AssetTag.tag_id)
        .where(AssetTag.asset_id.in_(asset_ids), AssetTag.suppressed.is_(False))
    )
    out: dict[uuid.UUID, set[tuple[str, str]]] = {}
    for aid, ns, value in (await session.execute(stmt)).all():
        out.setdefault(aid, set()).add((ns, value))
    return out
