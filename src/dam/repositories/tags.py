"""Tag vocabulary and asset tagging. Encodes ADR-010: auto never overwrites manual."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dam.models import Asset, AssetTag, Tag, TagSource
from dam.viewer import Viewer


async def get_or_create_tag(
    session: AsyncSession, namespace: str, value: str, firm_id: uuid.UUID | None
) -> Tag:
    value = value.strip().lower()
    stmt = select(Tag).where(Tag.namespace == namespace, Tag.value == value)
    stmt = stmt.where(Tag.firm_id == firm_id) if firm_id else stmt.where(Tag.firm_id.is_(None))
    tag = (await session.execute(stmt)).scalar_one_or_none()
    if tag is None:
        tag = Tag(namespace=namespace, value=value, firm_id=firm_id)
        session.add(tag)
        await session.flush()
    return tag


async def resolve_tag(session: AsyncSession, namespace: str, value: str, firm_id: uuid.UUID) -> Tag | None:
    """Find a global tag or a firm tag with this namespace/value."""
    value = value.strip().lower()
    stmt = select(Tag).where(
        Tag.namespace == namespace,
        Tag.value == value,
        or_(Tag.firm_id.is_(None), Tag.firm_id == firm_id),
    )
    return (await session.execute(stmt)).scalars().first()


async def vocabulary(session: AsyncSession, firm_id: uuid.UUID) -> dict[str, list[str]]:
    """Global plus firm vocabulary, grouped by namespace, sorted for prompt stability."""
    stmt = select(Tag.namespace, Tag.value).where(or_(Tag.firm_id.is_(None), Tag.firm_id == firm_id))
    out: dict[str, list[str]] = defaultdict(list)
    for ns, value in (await session.execute(stmt)).all():
        out[ns].append(value)
    return {ns: sorted(set(v)) for ns, v in sorted(out.items())}


async def add_manual_tag(
    session: AsyncSession, viewer: Viewer, asset: Asset, namespace: str, value: str
) -> AssetTag:
    tag = await resolve_tag(session, namespace, value, viewer.firm_id)
    if tag is None:
        tag = await get_or_create_tag(session, namespace, value, viewer.firm_id)
    existing = next((t for t in asset.tags if t.tag_id == tag.id), None)
    if existing is not None:
        existing.source = TagSource.manual
        existing.suppressed = False
        existing.confidence = None
        existing.created_by = viewer.user_id
        return existing
    row = AssetTag(
        asset_id=asset.id,
        tag_id=tag.id,
        firm_id=viewer.firm_id,
        source=TagSource.manual,
        suppressed=False,
        created_by=viewer.user_id,
    )
    session.add(row)
    asset.tags.append(row)
    await session.flush()
    return row


async def remove_tag(session: AsyncSession, viewer: Viewer, asset: Asset, tag_id: uuid.UUID) -> bool:
    row = next((t for t in asset.tags if t.tag_id == tag_id), None)
    if row is None:
        return False
    # Removing becomes a manual suppression so re-enrichment cannot re-add it.
    row.source = TagSource.manual
    row.suppressed = True
    row.confidence = None
    row.created_by = viewer.user_id
    return True


def merge_auto_tags(
    existing: list[AssetTag], proposed: dict[uuid.UUID, float]
) -> tuple[list[uuid.UUID], list[uuid.UUID], dict[uuid.UUID, float]]:
    """Decide what re-enrichment may change.

    Returns (tag_ids_to_add, tag_ids_to_remove, tag_ids_to_update_confidence).
    Manual rows (including suppressions) are untouched; auto rows are replaced by the
    proposed set.
    """
    manual = {t.tag_id for t in existing if t.source == TagSource.manual}
    auto = {t.tag_id for t in existing if t.source == TagSource.auto}
    wanted = {tid: conf for tid, conf in proposed.items() if tid not in manual}
    add = [tid for tid in wanted if tid not in auto]
    remove = [tid for tid in auto if tid not in wanted]
    update = {tid: conf for tid, conf in wanted.items() if tid in auto}
    return add, remove, update


async def apply_auto_tags(
    session: AsyncSession,
    asset: Asset,
    proposed: list[tuple[str, str, float]],
    firm_id: uuid.UUID,
) -> None:
    resolved: dict[uuid.UUID, float] = {}
    for namespace, value, confidence in proposed:
        tag = await resolve_tag(session, namespace, value, firm_id)
        if tag is None:
            # Open namespaces (object, misc) create firm-scoped tags; closed ones must exist.
            if namespace not in OPEN_NAMESPACES:
                continue
            tag = await get_or_create_tag(session, namespace, value, firm_id)
        resolved[tag.id] = max(confidence, resolved.get(tag.id, 0.0))
    add, remove, update = merge_auto_tags(asset.tags, resolved)
    by_tag = {t.tag_id: t for t in asset.tags}
    for tid in remove:
        asset.tags.remove(by_tag[tid])
    for tid, conf in update.items():
        by_tag[tid].confidence = conf
    for tid in add:
        row = AssetTag(
            asset_id=asset.id,
            tag_id=tid,
            firm_id=firm_id,
            source=TagSource.auto,
            confidence=resolved[tid],
        )
        session.add(row)
        asset.tags.append(row)
    await session.flush()


OPEN_NAMESPACES = {"object", "misc", "color"}
CLOSED_NAMESPACES = ("room", "phase", "style", "material")


async def facets(
    session: AsyncSession, viewer: Viewer, project_ids: list[uuid.UUID] | None
) -> dict[str, list[tuple[str, int]]]:
    stmt = (
        select(Tag.namespace, Tag.value, func.count(AssetTag.asset_id))
        .join(AssetTag, AssetTag.tag_id == Tag.id)
        .join(Asset, Asset.id == AssetTag.asset_id)
        .where(AssetTag.suppressed.is_(False))
        .group_by(Tag.namespace, Tag.value)
        .order_by(Tag.namespace, func.count(AssetTag.asset_id).desc())
    )
    stmt = viewer.scope_assets(stmt)
    if project_ids:
        stmt = stmt.where(Asset.project_id.in_(project_ids))
    out: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for ns, value, count in (await session.execute(stmt)).all():
        if len(out[ns]) < 50:
            out[ns].append((value, count))
    return dict(out)
