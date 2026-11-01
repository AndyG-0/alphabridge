"""user_profile.onboarding (U2)

Revision ID: d5e6f7a8b9c0
Revises: e3f4a5b6c7d8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "onboarding" not in {c["name"] for c in insp.get_columns("user_profile")}:
        with op.batch_alter_table("user_profile") as b:
            b.add_column(sa.Column("onboarding", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("onboarding")
