"""liabilities table and net-worth liabilities column

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "liability",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profile.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("apr", sa.Float(), nullable=False),
        sa.Column("monthly_payment", sa.Float(), nullable=False),
        sa.Column("payoff_date", sa.Date(), nullable=True),
        sa.Column("owner", sa.String(10), nullable=False),
        sa.Column("escrow_monthly", sa.Float(), nullable=False),
    )
    with op.batch_alter_table("net_worth_snapshot") as b:
        b.add_column(sa.Column("liabilities", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("net_worth_snapshot") as b:
        b.drop_column("liabilities")
    op.drop_table("liability")
