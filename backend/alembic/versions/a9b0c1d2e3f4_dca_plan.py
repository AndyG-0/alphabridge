"""user_profile.dca_plan (I6)

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "dca_plan" not in {c["name"] for c in insp.get_columns("user_profile")}:
        with op.batch_alter_table("user_profile") as b:
            b.add_column(sa.Column("dca_plan", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("dca_plan")
