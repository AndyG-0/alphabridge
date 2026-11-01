"""assumption_override and run_snapshot tables

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "assumption_override" not in tables:
        op.create_table(
            "assumption_override",
            sa.Column("key", sa.String(60), primary_key=True),
            sa.Column("value", sa.Float(), nullable=False),
        )
    if "run_snapshot" not in tables:
        op.create_table(
            "run_snapshot",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("assumptions", sa.JSON(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("run_snapshot")
    op.drop_table("assumption_override")
