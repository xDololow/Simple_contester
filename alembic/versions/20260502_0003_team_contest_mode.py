"""Add team contest mode.

Revision ID: 20260502_0003
Revises: 20260502_0002
Create Date: 2026-05-02 00:00:00.000002
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260502_0003"
down_revision = "20260502_0002"
branch_labels = None
depends_on = None


contestparticipationmode = sa.Enum("individual", "team", name="contestparticipationmode")


def upgrade() -> None:
    op.add_column(
        "contests",
        sa.Column("participation_mode", contestparticipationmode, nullable=False, server_default="individual"),
    )
    op.add_column("submissions", sa.Column("team_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_submissions_team_id"), "submissions", ["team_id"], unique=False)
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.create_foreign_key("fk_submissions_team_id_teams", "teams", ["team_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.drop_constraint("fk_submissions_team_id_teams", type_="foreignkey")
    op.drop_index(op.f("ix_submissions_team_id"), table_name="submissions")
    op.drop_column("submissions", "team_id")
    op.drop_column("contests", "participation_mode")
    contestparticipationmode.drop(op.get_bind(), checkfirst=True)
