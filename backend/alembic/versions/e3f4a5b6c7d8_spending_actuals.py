"""spending_transaction and category_rule tables (D4)

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "spending_transaction" not in tables:
        op.create_table(
            "spending_transaction",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tx_date", sa.Date(), nullable=False, index=True),
            sa.Column("description", sa.String(300), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("account_label", sa.String(120), nullable=False, server_default=""),
            sa.Column("category", sa.String(40), nullable=False, server_default=""),
            sa.Column("category_source", sa.String(20), nullable=False, server_default=""),
            sa.Column("suggested_category", sa.String(40), nullable=False, server_default=""),
            sa.Column("tx_hash", sa.String(64), nullable=False, unique=True),
        )
    if "category_rule" not in tables:
        op.create_table(
            "category_rule",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("pattern", sa.String(120), nullable=False, unique=True),
            sa.Column("category", sa.String(40), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("category_rule")
    op.drop_table("spending_transaction")
