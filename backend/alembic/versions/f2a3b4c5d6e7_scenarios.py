"""scenario table: named what-if overrides

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "scenario" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "scenario",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profile.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("overrides", sa.JSON(), nullable=False),
        sa.Column("shock", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("scenario")
