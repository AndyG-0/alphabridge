"""cash_flow table and user_profile.target_allocation (I2)

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "cash_flow" not in insp.get_table_names():
        op.create_table(
            "cash_flow",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("on", sa.Date(), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("note", sa.String(200), nullable=False, server_default=""),
        )
    if "target_allocation" not in {c["name"] for c in insp.get_columns("user_profile")}:
        with op.batch_alter_table("user_profile") as b:
            b.add_column(sa.Column("target_allocation", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("target_allocation")
    op.drop_table("cash_flow")
