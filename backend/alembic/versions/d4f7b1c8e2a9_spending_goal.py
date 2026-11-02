"""spending_goal table (recurring retirement costs such as travel)

Revision ID: d4f7b1c8e2a9
Revises: c3e6a9b2d4f7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f7b1c8e2a9"
down_revision: Union[str, Sequence[str], None] = "c3e6a9b2d4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "spending_goal" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "spending_goal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profile.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(40), nullable=False, server_default="other"),
        sa.Column("annual_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("start_basis", sa.String(24), nullable=False, server_default="YEARS_AFTER_RETIREMENT"),
        sa.Column("start_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("end_basis", sa.String(24), nullable=False, server_default="YEARS_AFTER_RETIREMENT"),
        sa.Column("end_value", sa.Float(), nullable=True),
        sa.Column("owner", sa.String(10), nullable=False, server_default="SELF"),
        sa.Column("real_inflation", sa.Float(), nullable=False, server_default="0"),
        sa.Column("smile_applies", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("spending_goal")
