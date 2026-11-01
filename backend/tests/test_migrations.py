"""Alembic: upgrade from empty, downgrade round-trip, and no drift between models and migrations.

Runs on SQLite by default; set TEST_POSTGRES_URL to also run against Postgres (CI provides a service container).
"""

import os
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from alembic import command
from models import Base

BACKEND = Path(__file__).resolve().parents[1]


def _cfg(url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(params=["sqlite", "postgres"])
def url(request, tmp_path):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'm.db'}"
    pg = os.getenv("TEST_POSTGRES_URL")
    if not pg:
        pytest.skip("TEST_POSTGRES_URL not set")
    engine = create_engine(pg)
    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    return pg


def test_single_head():
    heads = ScriptDirectory(str(BACKEND / "alembic")).get_heads()
    assert len(heads) == 1, f"branching migration history: {heads}"


def test_upgrade_creates_every_model_table(url):
    command.upgrade(_cfg(url), "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_no_drift_between_models_and_migrations(url):
    command.upgrade(_cfg(url), "head")
    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models differ from migrations - generate a revision: {diff}"


def test_downgrade_roundtrip(url):
    cfg = _cfg(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    left = set(inspect(create_engine(url)).get_table_names()) - {"alembic_version"}
    assert left == set()
    command.upgrade(cfg, "head")  # and back up again
