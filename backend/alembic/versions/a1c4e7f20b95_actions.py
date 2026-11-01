"""action center: ActionItem table and employer match fields

Revision ID: a1c4e7f20b95
Revises: d5e6f7a8b9c0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c4e7f20b95"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("user_profile")}
    with op.batch_alter_table("user_profile") as b:
        for name in ("employer_match_rate", "employer_match_cap_pct"):
            if name not in cols:
                b.add_column(sa.Column(name, sa.Float(), nullable=False, server_default="0"))
    if "action_item" not in insp.get_table_names():
        op.create_table(
            "action_item",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profile.id"), nullable=False, server_default="1"),
            sa.Column("key", sa.String(120), nullable=False),
            sa.Column("kind", sa.String(30), nullable=False, server_default=""),
            sa.Column("status", sa.String(10), nullable=False, server_default="open"),
            sa.Column("snooze_until", sa.Date(), nullable=True),
            sa.Column("notified_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "key", name="uq_action_user_key"),
        )
        op.create_index("ix_action_item_key", "action_item", ["key"])


def downgrade() -> None:
    op.drop_table("action_item")
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("employer_match_cap_pct")
        b.drop_column("employer_match_rate")
