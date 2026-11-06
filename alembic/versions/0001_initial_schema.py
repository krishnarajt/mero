"""initial schema

mero's full schema, identical to what create_all() built before migrations
existed; init_db() stamps such a database at this revision instead of running
it. The CURRENT_TIMESTAMP server defaults are deliberate: that spelling is
valid on both Postgres (deployed) and SQLite (local dev), which `now()` is not.

Ids are BIGINT on Postgres and INTEGER on SQLite, where only an INTEGER
primary key becomes the autoincrementing rowid.

Revision ID: 0001
Revises:
Create Date: 2026-11-05 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BigId = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', BigId, autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('workspaces',
    sa.Column('id', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('owner_id', BigId, nullable=False),
    sa.Column('invite_code', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('invite_code')
    )
    op.create_table('workspace_members',
    sa.Column('workspace_id', sa.String(length=16), nullable=False),
    sa.Column('user_id', BigId, nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('workspace_id', 'user_id')
    )
    op.create_table('boards',
    sa.Column('id', sa.String(length=16), nullable=False),
    sa.Column('workspace_id', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_boards_workspace_id'), 'boards', ['workspace_id'], unique=False)
    op.create_table('strokes',
    sa.Column('seq', BigId, autoincrement=True, nullable=False),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('board_id', sa.String(length=16), nullable=False),
    sa.Column('user_id', BigId, nullable=True),
    sa.Column('data', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['board_id'], ['boards.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('seq')
    )
    op.create_index('ix_strokes_board_id_id', 'strokes', ['board_id', 'id'], unique=False)
    op.create_index('ix_strokes_board_seq', 'strokes', ['board_id', 'seq'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_strokes_board_seq', table_name='strokes')
    op.drop_index('ix_strokes_board_id_id', table_name='strokes')
    op.drop_table('strokes')
    op.drop_index(op.f('ix_boards_workspace_id'), table_name='boards')
    op.drop_table('boards')
    op.drop_table('workspace_members')
    op.drop_table('workspaces')
    op.drop_table('users')
