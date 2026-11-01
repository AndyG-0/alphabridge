import os
import sys
from pathlib import Path

import pytest

# litellm otherwise downloads its model-cost map from GitHub at import time
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app

# Set TEST_DATABASE_URL (e.g. postgresql+psycopg://...) to run the whole suite against another database.
# On a server database each test gets its own schema, so a lingering transaction can never block the next test.
TEST_DB = os.getenv("TEST_DATABASE_URL", "sqlite://")
_schemas: list[str] = []


def _test_url() -> str:
    if TEST_DB.startswith("sqlite"):
        return TEST_DB
    import uuid

    from sqlalchemy import create_engine

    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_engine(TEST_DB, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    admin.dispose()
    _schemas.append(schema)
    sep = "&" if "?" in TEST_DB else "?"
    return f"{TEST_DB}{sep}options=-csearch_path%3D{schema}"


def _make_app(token: str):
    return create_app({"DATABASE_URL": _test_url(), "ACCESS_TOKEN": token, "TESTING": True})


def pytest_sessionfinish(session, exitstatus):
    if _schemas:
        from sqlalchemy import create_engine

        admin = create_engine(TEST_DB, isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            for sch in _schemas:
                c.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{sch}" CASCADE')
        admin.dispose()


def _release_db():
    import db

    db.remove_session()
    if db._engine is not None and not TEST_DB.startswith("sqlite"):
        db._engine.dispose()


@pytest.fixture
def app():
    yield _make_app("")
    _release_db()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The suite must never touch the real network; mock requests/yfinance/litellm instead."""
    import socket

    real_connect = socket.socket.connect

    def guarded(self, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("localhost", "127.0.0.1", "::1") and not host.startswith("/"):
            raise RuntimeError(f"network access blocked in tests: {address!r}")
        return real_connect(self, address, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def authed_app():
    yield _make_app("s3cret")
    _release_db()
