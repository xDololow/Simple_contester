"""Add contest registrations.

Revision ID: 20260505_0010
Revises: 20260505_0009
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260505_0010"
down_revision: Union[str, None] = "20260505_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


registration_status = sa.Enum("pending", "approved", "rejected", name="contestregistrationstatus")


def upgrade() -> None:
    op.add_column("contests", sa.Column("registration_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "contests",
        sa.Column("registration_requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "contest_registrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("status", registration_status, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contest_id", "team_id", name="uq_contest_registration_team"),
        sa.UniqueConstraint("contest_id", "user_id", name="uq_contest_registration_user"),
    )
    op.create_index(op.f("ix_contest_registrations_contest_id"), "contest_registrations", ["contest_id"], unique=False)
    op.create_index(op.f("ix_contest_registrations_requested_at"), "contest_registrations", ["requested_at"], unique=False)
    op.create_index(op.f("ix_contest_registrations_status"), "contest_registrations", ["status"], unique=False)
    op.create_index(op.f("ix_contest_registrations_team_id"), "contest_registrations", ["team_id"], unique=False)
    op.create_index(op.f("ix_contest_registrations_user_id"), "contest_registrations", ["user_id"], unique=False)
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("contests", "registration_enabled", server_default=None)
        op.alter_column("contests", "registration_requires_approval", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_contest_registrations_user_id"), table_name="contest_registrations")
    op.drop_index(op.f("ix_contest_registrations_team_id"), table_name="contest_registrations")
    op.drop_index(op.f("ix_contest_registrations_status"), table_name="contest_registrations")
    op.drop_index(op.f("ix_contest_registrations_requested_at"), table_name="contest_registrations")
    op.drop_index(op.f("ix_contest_registrations_contest_id"), table_name="contest_registrations")
    op.drop_table("contest_registrations")
    registration_status.drop(op.get_bind(), checkfirst=True)
    op.drop_column("contests", "registration_requires_approval")
    op.drop_column("contests", "registration_enabled")
