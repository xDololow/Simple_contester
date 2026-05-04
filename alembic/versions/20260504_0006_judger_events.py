"""Add judger events.

Revision ID: 20260504_0006
Revises: 20260504_0005
Create Date: 2026-05-04 00:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260504_0006"
down_revision = "20260504_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judger_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("judger_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_judger_events_created_at"), "judger_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_judger_events_judger_id"), "judger_events", ["judger_id"], unique=False)
    op.create_index(op.f("ix_judger_events_submission_id"), "judger_events", ["submission_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_judger_events_submission_id"), table_name="judger_events")
    op.drop_index(op.f("ix_judger_events_judger_id"), table_name="judger_events")
    op.drop_index(op.f("ix_judger_events_created_at"), table_name="judger_events")
    op.drop_table("judger_events")
