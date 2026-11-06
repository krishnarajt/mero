import secrets

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Board, Stroke, User, Workspace, WorkspaceMember


def new_id(n: int = 10) -> str:
    """A short URL-safe id with no '-' or '_', so it reads cleanly in a link."""
    return secrets.token_urlsafe(n)[:n].replace("-", "x").replace("_", "y")


async def list_for_user(db: AsyncSession, user_id: int) -> list[dict]:
    """Every workspace the user is in, with its boards and members, in three queries."""
    workspaces = (
        await db.execute(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.created_at)
        )
    ).scalars().all()
    ids = [w.id for w in workspaces]
    boards: dict[str, list] = {i: [] for i in ids}
    members: dict[str, list] = {i: [] for i in ids}
    if ids:
        for b in (await db.execute(select(Board).where(Board.workspace_id.in_(ids)).order_by(Board.created_at))).scalars():
            boards[b.workspace_id].append({"id": b.id, "name": b.name, "created_at": b.created_at})
        rows = await db.execute(
            select(WorkspaceMember.workspace_id, User.username)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id.in_(ids))
        )
        for workspace_id, username in rows:
            members[workspace_id].append(username)
    return [
        {
            "id": w.id,
            "name": w.name,
            "is_owner": w.owner_id == user_id,
            "invite_code": w.invite_code,
            "members": members[w.id],
            "boards": boards[w.id],
        }
        for w in workspaces
    ]


async def create_workspace(db: AsyncSession, name: str, owner_id: int) -> Workspace:
    workspace = Workspace(id=new_id(), name=name, owner_id=owner_id, invite_code=new_id(16))
    db.add(workspace)
    # Flush so the workspace row exists before the member row points at it.
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner_id))
    await db.commit()
    return workspace


async def get_for_member(db: AsyncSession, workspace_id: str, user_id: int) -> Workspace | None:
    """The workspace if the user is a member of it."""
    return (
        await db.execute(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(Workspace.id == workspace_id, WorkspaceMember.user_id == user_id)
        )
    ).scalar_one_or_none()


async def rename(db: AsyncSession, workspace: Workspace, name: str) -> None:
    workspace.name = name
    await db.commit()


async def leave(db: AsyncSession, workspace_id: str, user_id: int) -> None:
    await db.execute(
        delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
    )
    await db.commit()


async def delete_workspace(db: AsyncSession, workspace_id: str) -> list[str]:
    """Delete the workspace and everything in it. Returns its board ids, so their rooms can be closed.

    Deletes explicitly rather than relying on ON DELETE CASCADE, which SQLite
    only honours with foreign keys switched on.
    """
    board_ids = list((await db.execute(select(Board.id).where(Board.workspace_id == workspace_id))).scalars())
    if board_ids:
        await db.execute(delete(Stroke).where(Stroke.board_id.in_(board_ids)))
    await db.execute(delete(Board).where(Board.workspace_id == workspace_id))
    await db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id))
    await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
    await db.commit()
    return board_ids


async def join_by_code(db: AsyncSession, code: str, user_id: int) -> Workspace | None:
    """Add the user to the workspace with this invite code. None if the code is unknown."""
    workspace = (await db.execute(select(Workspace).where(Workspace.invite_code == code))).scalar_one_or_none()
    if workspace is None:
        return None
    if await db.get(WorkspaceMember, (workspace.id, user_id)) is None:
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user_id))
        await db.commit()
    return workspace
