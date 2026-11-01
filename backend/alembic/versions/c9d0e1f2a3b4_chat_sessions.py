"""chat sessions and messages

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A running app's create_all may have made the tables already.
    existing = sa.inspect(op.get_bind()).get_table_names()
    if "chat_session" not in existing:
        op.create_table(
            "chat_session",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profile.id"), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("title_source", sa.String(10), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "chat_message" not in existing:
        op.create_table(
            "chat_message",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(10), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tools_used", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_chat_message_session_id", "chat_message", ["session_id"])


def downgrade() -> None:
    op.drop_table("chat_message")
    op.drop_table("chat_session")
