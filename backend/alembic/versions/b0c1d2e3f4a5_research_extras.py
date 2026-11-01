"""watchlist_item, thesis_record, research_report.input_hash, llm_config.token_budget (I7)

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "watchlist_item" not in tables:
        op.create_table(
            "watchlist_item",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("symbol", sa.String(20), nullable=False, unique=True),
            sa.Column("added_at", sa.DateTime(), nullable=False),
            sa.Column("note", sa.String(500), nullable=False, server_default=""),
            sa.Column("buy_below", sa.Float(), nullable=True),
            sa.Column("upside_alert", sa.Float(), nullable=True),
            sa.Column("last_alerted_on", sa.Date(), nullable=True),
        )
    if "thesis_record" not in tables:
        op.create_table(
            "thesis_record",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("symbol", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("thesis", sa.Text(), nullable=False, server_default=""),
            sa.Column("criteria_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(12), nullable=False, server_default="ACTIVE"),
            sa.Column("invalidated_on", sa.Date(), nullable=True),
        )
    if "input_hash" not in {c["name"] for c in insp.get_columns("research_report")}:
        with op.batch_alter_table("research_report") as b:
            b.add_column(sa.Column("input_hash", sa.String(64), nullable=False, server_default=""))
    if "token_budget" not in {c["name"] for c in insp.get_columns("llm_config")}:
        with op.batch_alter_table("llm_config") as b:
            b.add_column(sa.Column("token_budget", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("llm_config") as b:
        b.drop_column("token_budget")
    with op.batch_alter_table("research_report") as b:
        b.drop_column("input_hash")
    op.drop_table("thesis_record")
    op.drop_table("watchlist_item")
