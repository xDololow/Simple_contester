"""Add contest clarifications.

Revision ID: 20260504_0007
Revises: 20260504_0006
Create Date: 2026-05-04 13:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260504_0007"
down_revision = "20260504_0006"
branch_labels = None
depends_on = None


clarificationstatus = sa.Enum("open", "answered", "closed", name="clarificationstatus")
clarificationvisibility = sa.Enum("private", "broadcast", name="clarificationvisibility")


def upgrade() -> None:
    op.create_table(
        "clarifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", clarificationstatus, nullable=False),
        sa.Column("visibility", clarificationvisibility, nullable=False),
        sa.Column("answered_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["answered_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_clarifications_author_user_id"), "clarifications", ["author_user_id"], unique=False)
    op.create_index(op.f("ix_clarifications_contest_id"), "clarifications", ["contest_id"], unique=False)
    op.create_index(op.f("ix_clarifications_created_at"), "clarifications", ["created_at"], unique=False)
    op.create_index(op.f("ix_clarifications_status"), "clarifications", ["status"], unique=False)
    op.create_index(op.f("ix_clarifications_task_id"), "clarifications", ["task_id"], unique=False)
    op.create_index(op.f("ix_clarifications_visibility"), "clarifications", ["visibility"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_clarifications_visibility"), table_name="clarifications")
    op.drop_index(op.f("ix_clarifications_task_id"), table_name="clarifications")
    op.drop_index(op.f("ix_clarifications_status"), table_name="clarifications")
    op.drop_index(op.f("ix_clarifications_created_at"), table_name="clarifications")
    op.drop_index(op.f("ix_clarifications_contest_id"), table_name="clarifications")
    op.drop_index(op.f("ix_clarifications_author_user_id"), table_name="clarifications")
    op.drop_table("clarifications")
