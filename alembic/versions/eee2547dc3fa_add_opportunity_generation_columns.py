"""add opportunity generation columns

Revision ID: eee2547dc3fa
Revises: 35ec2147b900
Create Date: 2026-07-22 19:24:16.675180

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eee2547dc3fa'
down_revision: Union[str, Sequence[str], None] = '35ec2147b900'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.add_column(sa.Column("required_skills", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("source_concepts", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_column("source_concepts")
        batch_op.drop_column("created_at")
        batch_op.drop_column("required_skills")
