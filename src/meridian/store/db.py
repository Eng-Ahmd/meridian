"""Engine and session management. SQLite by default; Postgres via DATABASE_URL."""
from __future__ import annotations

import os
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_engine = None
_SessionFactory = None


def init_db(database_url: str) -> None:
    global _engine, _SessionFactory
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        path = urlparse(database_url).path
        if path and path not in (":memory:", "/:memory:"):
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
    _engine = create_engine(database_url, **kwargs)
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    from meridian.store.models import Base

    Base.metadata.create_all(_engine)


def get_session() -> Session:
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionFactory()
