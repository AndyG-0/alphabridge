"""ingestion audit/undo columns and holding currency (D2)

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _log_cols() -> list:
    return [
    sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
    sa.Column("batch_id", sa.String(32), nullable=False, server_default=""),
    sa.Column("before", sa.JSON(), nullable=True),
    sa.Column("created_account", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("undone_at", sa.DateTime(), nullable=True),
]
def _holding_cols() -> list:
    return [
    sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
    sa.Column("fx_rate", sa.Float(), nullable=False, server_default="1.0"),
]


def _add(table: str, cols: list) -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    with op.batch_alter_table(table) as b:
        for c in cols:
            if c.name not in have:
                b.add_column(c)


def upgrade() -> None:
    _add("ingestion_log", _log_cols())
    _add("holding", _holding_cols())


def downgrade() -> None:
    with op.batch_alter_table("ingestion_log") as b:
        for c in _log_cols():
            b.drop_column(c.name)
    with op.batch_alter_table("holding") as b:
        for c in _holding_cols():
            b.drop_column(c.name)
