"""Add task test scoring metadata.

Revision ID: 20260505_0009
Revises: 20260505_0008
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260505_0009"
down_revision: Union[str, None] = "20260505_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_tests", sa.Column("points", sa.Float(), nullable=True))
    op.add_column("task_tests", sa.Column("group_name", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("task_tests", "group_name")
    op.drop_column("task_tests", "points")
