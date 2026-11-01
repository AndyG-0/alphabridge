"""household planning: health care, SS claiming, LTC, guardrails, extra debt payments, planned events

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROFILE_FLOATS = {
    "spouse_take_home_monthly": "0", "target_success_rate": "0.85", "ss_claim_age": "67", "spouse_ss_claim_age": "67",
    "aca_benchmark_premium_monthly": "0", "dental_vision_monthly": "50", "health_oop_annual": "2500",
    "medicare_monthly_per_person": "450", "health_inflation": "0.05", "home_value": "0", "home_upkeep_pct": "0.01",
    "ltc_annual": "100000", "ltc_years": "2", "ltc_start_age": "85",
}


def upgrade() -> None:
    # Safe to re-run: a running app's create_all may have made planned_event already, and an interrupted
    # SQLite batch leaves an _alembic_tmp_* table behind (SQLite can't roll back DDL).
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for t in ("user_profile", "liability"):
        if f"_alembic_tmp_{t}" in tables:
            op.drop_table(f"_alembic_tmp_{t}")
    cols = {t: {c["name"] for c in insp.get_columns(t)} for t in ("user_profile", "liability")}

    if "guardrails_enabled" not in cols["user_profile"]:
        with op.batch_alter_table("user_profile") as b:
            for name, default in PROFILE_FLOATS.items():
                if name not in cols["user_profile"]:
                    b.add_column(sa.Column(name, sa.Float(), nullable=False, server_default=default))
            b.add_column(sa.Column("guardrails_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "extra_payment_until" not in cols["liability"]:
        with op.batch_alter_table("liability") as b:
            if "extra_monthly_payment" not in cols["liability"]:
                b.add_column(sa.Column("extra_monthly_payment", sa.Float(), nullable=False, server_default="0"))
            b.add_column(sa.Column("extra_payment_until", sa.String(12), nullable=False, server_default="RETIREMENT"))
    if "planned_event" in tables:
        return
    op.create_table(
        "planned_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profile.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("start_year", sa.Integer(), nullable=False),
        sa.Column("repeat_every_years", sa.Integer(), nullable=False),
        sa.Column("repeat_until_year", sa.Integer(), nullable=True),
        sa.Column("owner", sa.String(10), nullable=False),
        sa.Column("financed", sa.Boolean(), nullable=False),
        sa.Column("down_payment", sa.Float(), nullable=False),
        sa.Column("loan_apr", sa.Float(), nullable=False),
        sa.Column("loan_term_months", sa.Integer(), nullable=False),
        sa.Column("is_home_sale", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("planned_event")
    with op.batch_alter_table("liability") as b:
        b.drop_column("extra_payment_until")
        b.drop_column("extra_monthly_payment")
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("guardrails_enabled")
        for name in reversed(PROFILE_FLOATS):
            b.drop_column(name)
