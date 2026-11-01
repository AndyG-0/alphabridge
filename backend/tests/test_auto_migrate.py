"""The app brings an out-of-date database up to date on start, so the dev reloader never needs a manual restart."""

from pathlib import Path

from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text

import db
from alembic import command

BACKEND = Path(__file__).resolve().parents[1]


def test_init_db_upgrades_a_stale_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'stale.db'}"
    cfg = AlembicConfig(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "e5f6a7b8c9d0")  # before the pension and state migrations
    assert "state" not in {c["name"] for c in inspect(create_engine(url)).get_columns("user_profile")}

    db.init_db(url, auto_migrate=True)
    try:
        cols = {c["name"] for c in inspect(db._engine).get_columns("user_profile")}
        assert {"state", "meets_community_engagement"} <= cols
        with db._engine.connect() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() != "e5f6a7b8c9d0"
        db.init_db(url, auto_migrate=True)  # already current: no-op
    finally:
        db._engine.dispose()
