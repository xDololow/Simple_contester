"""Add contest scoring mode."""

from alembic import op
import sqlalchemy as sa


revision = "20260505_0014"
down_revision = "20260505_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contests",
        sa.Column("scoring_mode", sa.String(length=20), nullable=False, server_default="ioi"),
    )


def downgrade() -> None:
    op.drop_column("contests", "scoring_mode")
