"""Add task version snapshots.

Revision ID: 20260505_0011
Revises: 20260505_0010
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260505_0011"
down_revision: Union[str, None] = "20260505_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("input_format", sa.Text(), nullable=False),
        sa.Column("output_format", sa.Text(), nullable=False),
        sa.Column("samples", sa.Text(), nullable=False),
        sa.Column("time_limit_ms", sa.Integer(), nullable=False),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.Column("partial_scoring", sa.Boolean(), nullable=False),
        sa.Column("tests_snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "version_number", name="uq_task_version_number"),
    )
    op.create_index(op.f("ix_task_versions_created_at"), "task_versions", ["created_at"], unique=False)
    op.create_index(op.f("ix_task_versions_task_id"), "task_versions", ["task_id"], unique=False)
    op.add_column("submissions", sa.Column("task_version_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_submissions_task_version_id"), "submissions", ["task_version_id"], unique=False)
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_submissions_task_version_id",
            "submissions",
            "task_versions",
            ["task_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_submissions_task_version_id", "submissions", type_="foreignkey")
    op.drop_index(op.f("ix_submissions_task_version_id"), table_name="submissions")
    op.drop_column("submissions", "task_version_id")
    op.drop_index(op.f("ix_task_versions_task_id"), table_name="task_versions")
    op.drop_index(op.f("ix_task_versions_created_at"), table_name="task_versions")
    op.drop_table("task_versions")
