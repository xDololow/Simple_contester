"""Add moderator role and contest moderator assignments.

Revision ID: 20261012_0016
Revises: 20261012_0015
Create Date: 2026-10-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20261012_0016"
down_revision: Union[str, None] = "20261012_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name in {"mysql", "mariadb"}:
        op.execute("ALTER TABLE users MODIFY COLUMN role ENUM('admin', 'moderator', 'participant') NOT NULL")
    op.create_table(
        "contest_moderators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contest_id", sa.Integer(), sa.ForeignKey("contests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("contest_id", "user_id", name="uq_contest_moderator"),
    )
    op.create_index("ix_contest_moderators_contest_id", "contest_moderators", ["contest_id"])
    op.create_index("ix_contest_moderators_user_id", "contest_moderators", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_contest_moderators_user_id", table_name="contest_moderators")
    op.drop_index("ix_contest_moderators_contest_id", table_name="contest_moderators")
    op.drop_table("contest_moderators")
    bind = op.get_bind()
    if bind.dialect.name in {"mysql", "mariadb"}:
        op.execute("UPDATE users SET role = 'participant' WHERE role = 'moderator'")
        op.execute("ALTER TABLE users MODIFY COLUMN role ENUM('admin', 'participant') NOT NULL")
