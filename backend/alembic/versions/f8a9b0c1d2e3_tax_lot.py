"""tax_lot table (I4)

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "tax_lot" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "tax_lot",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=False),
            sa.Column("symbol", sa.String(40), nullable=False),
            sa.Column("acquired", sa.Date(), nullable=False),
            sa.Column("shares", sa.Float(), nullable=False),
            sa.Column("cost_basis_total", sa.Float(), nullable=False, server_default="0"),
            sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
            sa.Column("source", sa.String(40), nullable=False, server_default="fidelity_lots"),
        )


def downgrade() -> None:
    op.drop_table("tax_lot")
