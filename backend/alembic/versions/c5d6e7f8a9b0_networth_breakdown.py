"""net_worth_snapshot.breakdown (asset/liability breakdown for D3)

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("net_worth_snapshot")}
    if "breakdown" not in cols:
        with op.batch_alter_table("net_worth_snapshot") as b:
            b.add_column(sa.Column("breakdown", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("net_worth_snapshot") as b:
        b.drop_column("breakdown")
