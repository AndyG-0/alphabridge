"""spouse profile fields and account owner

Revision ID: a1b2c3d4e5f6
Revises: 017e08611132
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "017e08611132"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.add_column(sa.Column("spouse_name", sa.String(120), nullable=False, server_default=""))
        b.add_column(sa.Column("spouse_age", sa.Float(), nullable=False, server_default="0"))
        b.add_column(sa.Column("spouse_annual_income", sa.Float(), nullable=False, server_default="0"))
        b.add_column(sa.Column("social_security_monthly", sa.Float(), nullable=False, server_default="0"))
    with op.batch_alter_table("account") as b:
        b.add_column(sa.Column("owner", sa.String(10), nullable=False, server_default="SELF"))


def downgrade() -> None:
    with op.batch_alter_table("account") as b:
        b.drop_column("owner")
    with op.batch_alter_table("user_profile") as b:
        for c in ("social_security_monthly", "spouse_annual_income", "spouse_age", "spouse_name"):
            b.drop_column(c)
