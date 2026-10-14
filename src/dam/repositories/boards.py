from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dam.models import Asset, Board, BoardAsset
from dam.viewer import Viewer


def _scope(stmt, viewer: Viewer):
    stmt = stmt.where(Board.firm_id == viewer.firm_id)
    if viewer.is_client:
        stmt = stmt.where(
            Board.project_id.in_(list(viewer.project_roles)), Board.shared_with_clients.is_(True)
        )
    return stmt


async def list_boards(
    session: AsyncSession, viewer: Viewer, project_id: uuid.UUID | None
) -> list[tuple[Board, int]]:
    count = select(func.count(BoardAsset.asset_id)).where(BoardAsset.board_id == Board.id).scalar_subquery()
    stmt = _scope(select(Board, count), viewer).order_by(Board.created_at.desc())
    if project_id:
        stmt = stmt.where(Board.project_id == project_id)
    return [(b, n) for b, n in (await session.execute(stmt)).all()]


async def get_board(session: AsyncSession, viewer: Viewer, board_id: uuid.UUID) -> Board | None:
    stmt = _scope(select(Board).where(Board.id == board_id), viewer)
    return (await session.execute(stmt)).scalar_one_or_none()


async def board_assets(session: AsyncSession, viewer: Viewer, board: Board) -> list[Asset]:
    stmt = (
        select(Asset)
        .join(BoardAsset, BoardAsset.asset_id == Asset.id)
        .where(BoardAsset.board_id == board.id)
        .order_by(BoardAsset.position, Asset.created_at.desc())
    )
    return list((await session.execute(viewer.scope_assets(stmt))).scalars().all())


async def set_board_assets(session: AsyncSession, board: Board, asset_ids: list[uuid.UUID]) -> None:
    await session.execute(delete(BoardAsset).where(BoardAsset.board_id == board.id))
    for pos, aid in enumerate(dict.fromkeys(asset_ids)):
        session.add(BoardAsset(board_id=board.id, asset_id=aid, position=pos))
    await session.flush()


async def add_board_assets(session: AsyncSession, board: Board, asset_ids: list[uuid.UUID]) -> None:
    existing = set(
        (await session.execute(select(BoardAsset.asset_id).where(BoardAsset.board_id == board.id)))
        .scalars()
        .all()
    )
    start = len(existing)
    for i, aid in enumerate(a for a in dict.fromkeys(asset_ids) if a not in existing):
        session.add(BoardAsset(board_id=board.id, asset_id=aid, position=start + i))
    await session.flush()
