"""spouse social security and target retirement age

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.add_column(sa.Column("spouse_social_security_monthly", sa.Float(), nullable=False, server_default="0"))
        b.add_column(sa.Column("spouse_target_retirement_age", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("spouse_target_retirement_age")
        b.drop_column("spouse_social_security_monthly")
