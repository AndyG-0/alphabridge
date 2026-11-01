from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker

from models import Base
from userctx import current_user_id

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


def _scope_to_user(state) -> None:
    """Tenant filter: every ORM SELECT, bulk UPDATE and bulk DELETE only touches the current user's rows.

    Models with a `user_id` are filtered directly; account children (holdings, lots, menus, import logs) through their account. The household-level
    tables listed in `models.SHARED_TABLES` are intentionally not scoped."""
    if state.is_select and (state.is_column_load or state.is_relationship_load):
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    from sqlalchemy import or_, select
    from sqlalchemy.orm import with_loader_criteria

    import models as m

    uid = current_user_id()
    mine = select(m.Account.id).where(m.Account.user_id == uid).scalar_subquery()
    opts = [with_loader_criteria(M, M.user_id == uid, include_aliases=True) for M in m.USER_SCOPED]
    opts += [with_loader_criteria(M, M.account_id.in_(mine), include_aliases=True) for M in m.ACCOUNT_CHILDREN]
    opts.append(with_loader_criteria(m.IngestionLog, or_(m.IngestionLog.account_id.is_(None), m.IngestionLog.account_id.in_(mine)), include_aliases=True))
    state.statement = state.statement.options(*opts)


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

    factory = sessionmaker(bind=_engine, expire_on_commit=False)
    event.listen(factory, "do_orm_execute", _scope_to_user)
    _Session = scoped_session(factory)
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
