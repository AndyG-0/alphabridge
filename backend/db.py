from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker

from models import Base

_engine = None
_Session = None


def migrate(url: str) -> None:
    """Bring the database to the latest Alembic revision. Safe to call on every start (no-op when current)."""
    from pathlib import Path

    from alembic.config import Config as AlembicConfig

    from alembic import command

    backend = Path(__file__).resolve().parent
    cfg = AlembicConfig(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.attributes["url"] = url
    cfg.attributes["keep_app_logging"] = True  # env.py's fileConfig would replace the app's log handlers
    command.upgrade(cfg, "head")


def init_db(url: str, *, auto_migrate: bool = False):
    global _engine, _Session
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
        else:
            path = url.split("///", 1)[-1]
            if path:
                import os

                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if auto_migrate:
        migrate(url)
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    _Session = scoped_session(sessionmaker(bind=_engine, expire_on_commit=False))
    Base.metadata.create_all(_engine)
    return _engine


def session():
    return _Session()


def remove_session():
    if _Session is not None:
        _Session.remove()


@contextmanager
def session_scope():
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
