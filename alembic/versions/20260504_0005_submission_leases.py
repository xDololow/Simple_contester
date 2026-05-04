"""Add submission lease metadata.

Revision ID: 20260504_0005
Revises: 20260504_0004
Create Date: 2026-05-04 00:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260504_0005"
down_revision = "20260504_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("submissions", sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("submissions", sa.Column("claim_token", sa.String(length=80), nullable=True))
    op.add_column("submissions", sa.Column("attempt_number", sa.Integer(), server_default="0", nullable=False))
    op.create_index(op.f("ix_submissions_claim_expires_at"), "submissions", ["claim_expires_at"], unique=False)
    op.create_index(op.f("ix_submissions_claim_token"), "submissions", ["claim_token"], unique=False)
    op.create_index(
        "ix_submissions_verdict_claim_expires_at",
        "submissions",
        ["verdict", "claim_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_submissions_verdict_claim_expires_at", table_name="submissions")
    op.drop_index(op.f("ix_submissions_claim_token"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_claim_expires_at"), table_name="submissions")
    op.drop_column("submissions", "attempt_number")
    op.drop_column("submissions", "claim_token")
    op.drop_column("submissions", "claim_expires_at")
    op.drop_column("submissions", "claimed_at")
