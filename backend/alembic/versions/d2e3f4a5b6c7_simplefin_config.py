"""simplefin_config table (D1)

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "simplefin_config" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "simplefin_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("access_url_encrypted", sa.Text(), nullable=False),
            sa.Column("last_sync", sa.DateTime(), nullable=True),
            sa.Column("last_status", sa.String(100), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("simplefin_config")
