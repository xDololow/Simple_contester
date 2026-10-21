"""Add user last seen timestamp.

Revision ID: 20261012_0015
Revises: 20260505_0014
Create Date: 2026-10-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20261012_0015"
down_revision: Union[str, None] = "20260505_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_users_last_seen_at"), "users", ["last_seen_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_last_seen_at"), table_name="users")
    op.drop_column("users", "last_seen_at")
