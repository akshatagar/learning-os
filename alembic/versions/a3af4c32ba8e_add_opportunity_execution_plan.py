"""add opportunity execution plan

Revision ID: a3af4c32ba8e
Revises: eee2547dc3fa
Create Date: 2026-07-23 16:51:58.216606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3af4c32ba8e'
down_revision: Union[str, Sequence[str], None] = 'eee2547dc3fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.add_column(sa.Column("execution_plan", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_column("execution_plan")
