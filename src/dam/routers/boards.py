from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from dam import audit
from dam.deps import CurrentViewer, Session
from dam.models import Board
from dam.repositories import assets as asset_repo
from dam.repositories import boards as board_repo
from dam.repositories import projects as project_repo
from dam.schemas import AssetOut, BoardAssetsUpdate, BoardCreate, BoardOut, BoardUpdate

router = APIRouter(prefix="/boards", tags=["boards"])


async def _load(session, viewer, board_id: uuid.UUID) -> Board:
    board = await board_repo.get_board(session, viewer, board_id)
    if board is None:
        raise HTTPException(status_code=404, detail="board not found")
    return board


def _out(board: Board, count: int, cover_url: str | None = None) -> BoardOut:
    return BoardOut(
        id=board.id,
        project_id=board.project_id,
        name=board.name,
        shared_with_clients=board.shared_with_clients,
        created_by=board.created_by,
        created_at=board.created_at,
        asset_count=count,
        cover_url=cover_url,
    )


@router.get("", response_model=list[BoardOut])
async def list_boards(session: Session, viewer: CurrentViewer, project_id: uuid.UUID | None = None):
    if project_id is not None and not viewer.can_read_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    return [_out(b, n) for b, n in await board_repo.list_boards(session, viewer, project_id)]


@router.post("", response_model=BoardOut, status_code=201)
async def create_board(body: BoardCreate, session: Session, viewer: CurrentViewer):
    project = await project_repo.get_project(session, viewer, body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    viewer.require_edit(project.id)
    board = Board(
        firm_id=viewer.firm_id,
        project_id=project.id,
        name=body.name,
        created_by=viewer.user_id,
        shared_with_clients=viewer.is_client,
    )
    session.add(board)
    await session.flush()
    audit.record(session, viewer, "board.create", "board", board.id, {"name": body.name})
    await session.commit()
    return _out(board, 0)


@router.get("/{board_id}", response_model=BoardOut)
async def get_board(board_id: uuid.UUID, session: Session, viewer: CurrentViewer):
    board = await _load(session, viewer, board_id)
    assets = await board_repo.board_assets(session, viewer, board)
    cover = asset_repo.to_out(assets[0]).thumb_url if assets else None
    return _out(board, len(assets), cover)


@router.patch("/{board_id}", response_model=BoardOut)
async def update_board(board_id: uuid.UUID, body: BoardUpdate, session: Session, viewer: CurrentViewer):
    board = await _load(session, viewer, board_id)
    viewer.require_edit(board.project_id)
    changes = body.model_dump(exclude_unset=True)
    if "shared_with_clients" in changes:
        viewer.require_staff()
    for k, v in changes.items():
        setattr(board, k, v)
    audit.record(session, viewer, "board.update", "board", board.id, changes)
    await session.commit()
    assets = await board_repo.board_assets(session, viewer, board)
    return _out(board, len(assets))


@router.delete("/{board_id}", status_code=204)
async def delete_board(board_id: uuid.UUID, session: Session, viewer: CurrentViewer) -> None:
    board = await _load(session, viewer, board_id)
    viewer.require_edit(board.project_id)
    if viewer.is_client and board.created_by != viewer.user_id:
        raise HTTPException(status_code=403, detail="clients can only delete their own boards")
    await session.delete(board)
    audit.record(session, viewer, "board.delete", "board", board.id)
    await session.commit()


@router.get("/{board_id}/assets", response_model=list[AssetOut])
async def board_assets(board_id: uuid.UUID, session: Session, viewer: CurrentViewer):
    board = await _load(session, viewer, board_id)
    assets = await board_repo.board_assets(session, viewer, board)
    favs = await asset_repo.favorites_for(session, viewer, [a.id for a in assets])
    return [asset_repo.to_out(a, favorited=a.id in favs) for a in assets]


@router.put("/{board_id}/assets", status_code=204)
async def set_assets(
    board_id: uuid.UUID, body: BoardAssetsUpdate, session: Session, viewer: CurrentViewer
) -> None:
    board = await _load(session, viewer, board_id)
    viewer.require_edit(board.project_id)
    visible = await asset_repo.get_assets(session, viewer, body.asset_ids)
    await board_repo.set_board_assets(session, board, [a for a in body.asset_ids if a in visible])
    await session.commit()


@router.post("/{board_id}/assets", status_code=204)
async def add_assets(
    board_id: uuid.UUID, body: BoardAssetsUpdate, session: Session, viewer: CurrentViewer
) -> None:
    board = await _load(session, viewer, board_id)
    viewer.require_edit(board.project_id)
    visible = await asset_repo.get_assets(session, viewer, body.asset_ids)
    await board_repo.add_board_assets(session, board, [a for a in body.asset_ids if a in visible])
    await session.commit()
