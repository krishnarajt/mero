from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, get_current_user
from app.api.schemas import JoinRequest, NameRequest, OkResponse, WorkspaceCreated, WorkspaceOut, WorkspaceRef
from app.db.database import get_db
from app.services import room_service, workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Every workspace the user is in, with its boards, in one round trip."""
    return await workspace_service.list_for_user(db, user.id)


@router.post("", response_model=WorkspaceCreated)
async def create_workspace(
    body: NameRequest, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    workspace = await workspace_service.create_workspace(db, body.name.strip(), user.id)
    return WorkspaceCreated(id=workspace.id, name=workspace.name, invite_code=workspace.invite_code)


@router.post("/join", response_model=WorkspaceRef)
async def join_workspace(body: JoinRequest, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    workspace = await workspace_service.join_by_code(db, body.code.strip(), user.id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite link is not valid")
    return WorkspaceRef(id=workspace.id, name=workspace.name)


@router.patch("/{workspace_id}", response_model=OkResponse, response_model_exclude_none=True)
async def rename_workspace(
    workspace_id: str, body: NameRequest, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    workspace = await workspace_service.get_for_member(db, workspace_id, user.id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    await workspace_service.rename(db, workspace, body.name.strip())
    return OkResponse()


@router.delete("/{workspace_id}", response_model=OkResponse, response_model_exclude_none=True)
async def delete_workspace(workspace_id: str, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The owner deletes the workspace; anyone else just leaves it."""
    workspace = await workspace_service.get_for_member(db, workspace_id, user.id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    if workspace.owner_id != user.id:
        await workspace_service.leave(db, workspace_id, user.id)
        return OkResponse(left=True)
    for board_id in await workspace_service.delete_workspace(db, workspace_id):
        await room_service.close_board(board_id)
    return OkResponse()
