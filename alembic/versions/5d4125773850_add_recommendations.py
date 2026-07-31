"""add recommendations

Revision ID: 5d4125773850
Revises: a3af4c32ba8e
Create Date: 2026-07-31 17:26:57.848975

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d4125773850'
down_revision: Union[str, Sequence[str], None] = 'a3af4c32ba8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("goals.id"), nullable=True),
        sa.Column("gap", sa.String(), nullable=True),
        sa.Column("gap_score", sa.Float(), nullable=True),
        sa.Column("results", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("recommendations")
