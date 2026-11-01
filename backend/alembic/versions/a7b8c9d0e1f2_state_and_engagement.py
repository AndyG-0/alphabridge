"""profile.state and Medicaid community-engagement toggle

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_profile")}
    with op.batch_alter_table("user_profile") as b:
        if "state" not in cols:
            b.add_column(sa.Column("state", sa.String(2), nullable=False, server_default="AZ"))
        if "meets_community_engagement" not in cols:
            b.add_column(sa.Column("meets_community_engagement", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("meets_community_engagement")
        b.drop_column("state")
