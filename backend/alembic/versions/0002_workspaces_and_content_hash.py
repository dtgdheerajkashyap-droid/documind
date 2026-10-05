"""Add anonymous workspaces and document content hashes.

Existing rows are assigned to the default (shared) workspace.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_WORKSPACE_ID = uuid.UUID(int=0)


def _add_workspace_column(table_name: str) -> None:
    op.add_column(table_name, sa.Column("workspace_id", sa.Uuid(), nullable=True))
    table = sa.table(table_name, sa.column("workspace_id", sa.Uuid()))
    op.execute(table.update().values(workspace_id=DEFAULT_WORKSPACE_ID))
    with op.batch_alter_table(table_name) as batch:
        batch.alter_column("workspace_id", existing_type=sa.Uuid(), nullable=False)
    op.create_index(op.f(f"ix_{table_name}_workspace_id"), table_name, ["workspace_id"])


def upgrade() -> None:
    _add_workspace_column("documents")
    _add_workspace_column("chat_sessions")
    op.add_column("documents", sa.Column("content_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "content_hash")
    for table_name in ("chat_sessions", "documents"):
        op.drop_index(op.f(f"ix_{table_name}_workspace_id"), table_name=table_name)
        op.drop_column(table_name, "workspace_id")
