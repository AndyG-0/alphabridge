"""user_profile.employer_symbol (Portfolio X-Ray employer-stock concentration)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_profile")}
    if "employer_symbol" not in cols:
        with op.batch_alter_table("user_profile") as b:
            b.add_column(sa.Column("employer_symbol", sa.String(20), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("employer_symbol")
