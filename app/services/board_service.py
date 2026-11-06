from sqlalchemy import Row, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Board, Stroke, Workspace, WorkspaceMember
from app.services.workspace_service import new_id


async def board_access(db: AsyncSession, board_id: str, user_id: int) -> Row | None:
    """(id, name, workspace_id, workspace_name) if the user is a member of the board's workspace, else None."""
    return (
        await db.execute(
            select(Board.id, Board.name, Board.workspace_id, Workspace.name.label("workspace_name"))
            .join(Workspace, Workspace.id == Board.workspace_id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Board.workspace_id)
            .where(Board.id == board_id, WorkspaceMember.user_id == user_id)
        )
    ).first()


async def create_board(db: AsyncSession, workspace_id: str, name: str) -> Board:
    board = Board(id=new_id(), workspace_id=workspace_id, name=name)
    db.add(board)
    await db.commit()
    return board


async def rename_board(db: AsyncSession, board_id: str, name: str) -> None:
    await db.execute(update(Board).where(Board.id == board_id).values(name=name))
    await db.commit()


async def delete_board(db: AsyncSession, board_id: str) -> None:
    await db.execute(delete(Stroke).where(Stroke.board_id == board_id))
    await db.execute(delete(Board).where(Board.id == board_id))
    await db.commit()
