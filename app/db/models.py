"""
Database models for mero.

Strokes are the only hot table. A stroke row's `data` is the stroke's JSON
exactly as it goes to clients, so opening a board is string concatenation
rather than re-serialisation, and its columns hold only what queries filter or
sort on. `seq` is the paint order.

Rooms read and write strokes through the engine directly (see
app/services/room_service.py and persist_service.py); everything else goes
through a session.
"""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base

# Integer on SQLite so it becomes the rowid alias and autoincrements.
BigId = BigInteger().with_variant(Integer, "sqlite")


class User(Base):
    """An account. Usernames are stored lowercased."""

    __tablename__ = "users"

    id = Column(BigId, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Workspace(Base):
    """A set of boards shared by its members. Anyone with the invite code can join."""

    __tablename__ = "workspaces"

    id = Column(String(16), primary_key=True)
    name = Column(String(200), nullable=False)
    owner_id = Column(BigId, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    invite_code = Column(String(32), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id = Column(String(16), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(BigId, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())


class Board(Base):
    __tablename__ = "boards"

    id = Column(String(16), primary_key=True)
    workspace_id = Column(String(16), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Stroke(Base):
    """One finished stroke. `id` is the client's id, unique within its board."""

    __tablename__ = "strokes"

    seq = Column(BigId, primary_key=True, autoincrement=True)
    id = Column(String(32), nullable=False)
    board_id = Column(String(16), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigId, nullable=True)
    data = Column(Text, nullable=False)

    __table_args__ = (
        Index("ix_strokes_board_seq", "board_id", "seq"),
        Index("ix_strokes_board_id_id", "board_id", "id"),
    )
