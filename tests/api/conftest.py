"""API client fixture backed by the throwaway migrated database."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from api.app import create_app
from infra.db import get_db


@pytest.fixture
def api_client(migrated_engine: Engine) -> Iterator[TestClient]:
    app = create_app()

    def override_get_db() -> Iterator[Session]:
        session = Session(migrated_engine)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE nfl.games, nfl.players, nfl.teams CASCADE"))
