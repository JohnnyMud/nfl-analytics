"""Engine and short-lived sessions. URL comes from Settings."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from common.settings import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _require_database_url() -> str:
    return get_settings().sqlalchemy_url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_require_database_url())
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
