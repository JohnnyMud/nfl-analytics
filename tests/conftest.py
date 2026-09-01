"""Throwaway-database fixture for schema tests. DATABASE_URL is required."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url


def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    """Create a unique database, apply migrations, then drop it."""
    admin_url = make_url(_require_database_url())
    db_name = f"test_odds_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)
    test_url_str = test_url.render_as_string(hide_password=False)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url_str
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        engine = create_engine(test_url)
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :db_name AND pid <> pg_backend_pid()
                    """
                ),
                {"db_name": db_name},
            )
            conn.execute(text(f'DROP DATABASE "{db_name}"'))
        admin_engine.dispose()
