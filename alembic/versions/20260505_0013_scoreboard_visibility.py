"""Add contest scoreboard visibility."""

from alembic import op
import sqlalchemy as sa


revision = "20260505_0013"
down_revision = "20260505_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contests",
        sa.Column("scoreboard_visibility", sa.String(length=20), nullable=False, server_default="public"),
    )


def downgrade() -> None:
    op.drop_column("contests", "scoreboard_visibility")
