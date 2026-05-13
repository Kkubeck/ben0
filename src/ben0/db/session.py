"""SQLite session factory for BEN-0."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ben0 import config
from ben0.db.models import Base


def _get_engine(db_url: str | None = None):
    url = db_url or config.DB_URL
    # Ensure parent directory exists for SQLite file paths
    if url.startswith("sqlite:///"):
        db_path = Path(url[len("sqlite:///"):])
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url, echo=False)

    # Enable WAL mode and foreign keys for SQLite
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


_engine = None
_SessionFactory = None


def get_engine(db_url: str | None = None):
    global _engine
    if _engine is None:
        _engine = _get_engine(db_url)
    return _engine


def get_session_factory(db_url: str | None = None) -> sessionmaker:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(db_url), expire_on_commit=False)
    return _SessionFactory


def get_session(db_url: str | None = None) -> Session:
    """Return a new Session. Caller is responsible for closing."""
    factory = get_session_factory(db_url)
    return factory()


def init_db(db_url: str | None = None) -> None:
    """Create all tables (idempotent)."""
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)


def reset_singletons() -> None:
    """Reset cached engine/session — useful for tests."""
    global _engine, _SessionFactory
    _engine = None
    _SessionFactory = None
