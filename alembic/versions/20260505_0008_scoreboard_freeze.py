"""Add scoreboard freeze fields.

Revision ID: 20260505_0008
Revises: 20260504_0007
Create Date: 2026-05-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260505_0008"
down_revision = "20260504_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contests", sa.Column("scoreboard_freeze_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("contests", sa.Column("scoreboard_unfrozen", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("contests", "scoreboard_unfrozen")
    op.drop_column("contests", "scoreboard_freeze_at")
