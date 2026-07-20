"""add merge_queue review columns

Revision ID: 35ec2147b900
Revises: 4bc037ad74e0
Create Date: 2026-07-20 14:51:13.017574

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '35ec2147b900'
down_revision: Union[str, Sequence[str], None] = '4bc037ad74e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("merge_queue") as batch_op:
        batch_op.add_column(sa.Column("adjudication_log_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_type", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_merge_queue_adjudication_log_id",
            "adjudication_log",
            ["adjudication_log_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("merge_queue") as batch_op:
        batch_op.drop_constraint("fk_merge_queue_adjudication_log_id", type_="foreignkey")
        batch_op.drop_column("source_type")
        batch_op.drop_column("adjudication_log_id")
