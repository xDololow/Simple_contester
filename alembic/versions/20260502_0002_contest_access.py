"""Add contest access controls.

Revision ID: 20260502_0002
Revises: 20260502_0001
Create Date: 2026-05-02 00:00:00.000001
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260502_0002"
down_revision = "20260502_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contests", sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("participant_contests") as batch_op:
        batch_op.alter_column("started_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column("deadline_at", existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE participant_contests SET started_at = CURRENT_TIMESTAMP WHERE started_at IS NULL")
    op.execute("UPDATE participant_contests SET deadline_at = started_at WHERE deadline_at IS NULL")
    with op.batch_alter_table("participant_contests") as batch_op:
        batch_op.alter_column("deadline_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.alter_column("started_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.drop_column("contests", "is_public")
