"""pension table (cash-balance plans)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A running app's create_all may have made the table already (it ran before migrations were automatic).
    if "pension" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "pension",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profile.id"), nullable=False),
        sa.Column("owner", sa.String(10), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("plan_balance", sa.Float(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("pay_credit_pct", sa.Float(), nullable=False),
        sa.Column("covered_pay_annual", sa.Float(), nullable=False),
        sa.Column("interest_credit_rate", sa.Float(), nullable=False),
        sa.Column("start_age", sa.Float(), nullable=False),
        sa.Column("payout", sa.String(10), nullable=False),
        sa.Column("ytd_interest", sa.Float(), nullable=False),
        sa.Column("ytd_pay_credits", sa.Float(), nullable=False),
        sa.UniqueConstraint("user_id", "owner", name="uq_pension_user_owner"),
    )


def downgrade() -> None:
    op.drop_table("pension")
