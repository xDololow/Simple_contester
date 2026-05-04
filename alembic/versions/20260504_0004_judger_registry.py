"""Add judger registry.

Revision ID: 20260504_0004
Revises: 20260502_0003
Create Date: 2026-05-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260504_0004"
down_revision = "20260502_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judgers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("judger_id", sa.String(length=120), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("supported_languages", sa.Text(), nullable=False),
        sa.Column("sandbox_mode", sa.String(length=80), nullable=False),
        sa.Column("capabilities", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_submission_id", sa.Integer(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_state_change_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_judgers_current_submission_id"), "judgers", ["current_submission_id"], unique=False)
    op.create_index(op.f("ix_judgers_judger_id"), "judgers", ["judger_id"], unique=True)
    op.create_index(op.f("ix_judgers_last_seen_at"), "judgers", ["last_seen_at"], unique=False)
    op.create_index(op.f("ix_judgers_status"), "judgers", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_judgers_status"), table_name="judgers")
    op.drop_index(op.f("ix_judgers_last_seen_at"), table_name="judgers")
    op.drop_index(op.f("ix_judgers_judger_id"), table_name="judgers")
    op.drop_index(op.f("ix_judgers_current_submission_id"), table_name="judgers")
    op.drop_table("judgers")
