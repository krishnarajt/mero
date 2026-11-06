from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, get_current_user
from app.api.schemas import BoardCreated, BoardOut, NameRequest, OkResponse, WorkspaceRef
from app.db.database import get_db
from app.services import board_service, room_service, workspace_service

router = APIRouter(tags=["boards"])


@router.post("/workspaces/{workspace_id}/boards", response_model=BoardCreated)
async def create_board(
    workspace_id: str, body: NameRequest, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if await workspace_service.get_for_member(db, workspace_id, user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    board = await board_service.create_board(db, workspace_id, body.name.strip())
    return BoardCreated(id=board.id, name=board.name, workspace_id=workspace_id)


@router.get("/boards/{board_id}", response_model=BoardOut)
async def get_board(board_id: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await board_service.board_access(db, board_id, user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board not found")
    return BoardOut(id=row.id, name=row.name, workspace=WorkspaceRef(id=row.workspace_id, name=row.workspace_name))


@router.patch("/boards/{board_id}", response_model=OkResponse, response_model_exclude_none=True)
async def rename_board(
    board_id: str, body: NameRequest, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if await board_service.board_access(db, board_id, user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board not found")
    await board_service.rename_board(db, board_id, body.name.strip())
    return OkResponse()


@router.delete("/boards/{board_id}", response_model=OkResponse, response_model_exclude_none=True)
async def delete_board(board_id: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if await board_service.board_access(db, board_id, user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board not found")
    # Close the room first, so nobody draws into a board that is going away.
    await room_service.close_board(board_id)
    await board_service.delete_board(db, board_id)
    return OkResponse()
