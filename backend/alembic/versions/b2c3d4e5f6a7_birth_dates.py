"""replace current_age/spouse_age with birth dates

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""
from datetime import date, timedelta
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

YEAR = 365.2425


def upgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.add_column(sa.Column("birth_date", sa.Date(), nullable=True))
        b.add_column(sa.Column("spouse_birth_date", sa.Date(), nullable=True))
    conn = op.get_bind()
    today = date.today()
    for pid, age, sp in conn.execute(sa.text("SELECT id, current_age, spouse_age FROM user_profile")).fetchall():
        conn.execute(
            sa.text("UPDATE user_profile SET birth_date = :b, spouse_birth_date = :s WHERE id = :id"),
            {"b": today - timedelta(days=round(age * YEAR)),
             "s": today - timedelta(days=round(sp * YEAR)) if sp and sp > 0 else None, "id": pid})
    with op.batch_alter_table("user_profile") as b:
        b.alter_column("birth_date", existing_type=sa.Date(), nullable=False)
        b.drop_column("current_age")
        b.drop_column("spouse_age")


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as b:
        b.add_column(sa.Column("current_age", sa.Float(), nullable=False, server_default="35"))
        b.add_column(sa.Column("spouse_age", sa.Float(), nullable=False, server_default="0"))
    conn = op.get_bind()
    today = date.today()
    for pid, bd, sbd in conn.execute(sa.text("SELECT id, birth_date, spouse_birth_date FROM user_profile")).fetchall():
        bd = date.fromisoformat(bd) if isinstance(bd, str) else bd
        sbd = date.fromisoformat(sbd) if isinstance(sbd, str) else sbd
        conn.execute(
            sa.text("UPDATE user_profile SET current_age = :a, spouse_age = :s WHERE id = :id"),
            {"a": (today - bd).days / YEAR, "s": (today - sbd).days / YEAR if sbd else 0.0, "id": pid})
    with op.batch_alter_table("user_profile") as b:
        b.drop_column("birth_date")
        b.drop_column("spouse_birth_date")
