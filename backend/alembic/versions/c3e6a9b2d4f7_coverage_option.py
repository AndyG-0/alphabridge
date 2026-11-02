"""coverage_option table and user_profile.coverage_choice

Revision ID: c3e6a9b2d4f7
Revises: b2d5f8a31c06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e6a9b2d4f7"
down_revision: Union[str, Sequence[str], None] = "b2d5f8a31c06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "coverage_option" not in insp.get_table_names():
        op.create_table(
            "coverage_option",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profile.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("carrier", sa.String(120), nullable=False, server_default=""),
            sa.Column("plan_code", sa.String(60), nullable=False, server_default=""),
            sa.Column("category", sa.String(24), nullable=False, server_default="PRE_MEDICARE"),
            sa.Column("premium_by_year", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("premium_period", sa.String(8), nullable=False, server_default="MONTHLY"),
            sa.Column("premium_basis", sa.String(14), nullable=False, server_default="PER_PERSON"),
            sa.Column("deductible", sa.Float(), nullable=False, server_default="0"),
            sa.Column("oop_max", sa.Float(), nullable=False, server_default="0"),
            sa.Column("eligibility_min_age", sa.Float(), nullable=False, server_default="0"),
            sa.Column("eligibility_max_age", sa.Float(), nullable=True),
            sa.Column("requires_medicare_parts", sa.String(10), nullable=False, server_default=""),
            sa.Column("requires_part_b_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("includes_drugs", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("drug_option_id", sa.Integer(), sa.ForeignKey("coverage_option.id", ondelete="SET NULL"), nullable=True),
            sa.Column("owner", sa.String(10), nullable=False, server_default="BOTH"),
            sa.Column("cost_sharing_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
    if "coverage_choice" not in {c["name"] for c in insp.get_columns("user_profile")}:
        with op.batch_alter_table("user_profile") as b:
            b.add_column(sa.Column("coverage_choice", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("coverage_choice")
    op.drop_table("coverage_option")
