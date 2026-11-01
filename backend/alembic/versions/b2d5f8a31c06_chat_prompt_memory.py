"""ask-ai: prompt version and citations on messages, scenario and memory on sessions

Revision ID: b2d5f8a31c06
Revises: a1c4e7f20b95
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d5f8a31c06"
down_revision: Union[str, Sequence[str], None] = "a1c4e7f20b95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols("chat_session")
    with op.batch_alter_table("chat_session") as b:
        if "scenario" not in have:
            b.add_column(sa.Column("scenario", sa.String(80), nullable=False, server_default=""))
        if "memory" not in have:
            b.add_column(sa.Column("memory", sa.Text(), nullable=False, server_default=""))
    have = _cols("chat_message")
    with op.batch_alter_table("chat_message") as b:
        if "prompt_version" not in have:
            b.add_column(sa.Column("prompt_version", sa.String(30), nullable=False, server_default=""))
        if "citations" not in have:
            b.add_column(sa.Column("citations", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("chat_message") as b:
        b.drop_column("citations")
        b.drop_column("prompt_version")
    with op.batch_alter_table("chat_session") as b:
        b.drop_column("memory")
        b.drop_column("scenario")
