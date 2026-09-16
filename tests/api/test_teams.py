"""Team read endpoints return stored dimension rows, not inferred stand-ins."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.api.helpers import insert_team


def test_list_teams_empty(api_client: TestClient) -> None:
    response = api_client.get("/api/teams")
    assert response.status_code == 200
    assert response.json() == []


def test_list_teams_orders_by_conference_division_name(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        insert_team(
            session,
            team_abbr="SEA",
            team_name="Seattle Seahawks",
            team_nick="Seahawks",
            team_conf="NFC",
            team_division="NFC West",
        )
        insert_team(
            session,
            team_abbr="BUF",
            team_name="Buffalo Bills",
            team_nick="Bills",
            team_conf="AFC",
            team_division="AFC East",
        )
        insert_team(
            session,
            team_abbr="MIA",
            team_name="Miami Dolphins",
            team_nick="Dolphins",
            team_conf="AFC",
            team_division="AFC East",
        )

    response = api_client.get("/api/teams")
    assert response.status_code == 200
    abbrs = [row["team_abbr"] for row in response.json()]
    assert abbrs == ["BUF", "MIA", "SEA"]
    assert response.json()[0]["team_logo_espn"] == "https://example.test/BUF.png"


def test_get_team_unknown_is_404(api_client: TestClient) -> None:
    response = api_client.get("/api/teams/ZZZ")
    assert response.status_code == 404
    assert response.json() == {"detail": "team not found"}


def test_get_team_by_abbr(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        insert_team(
            session,
            team_abbr="SEA",
            team_name="Seattle Seahawks",
            team_nick="Seahawks",
            team_conf="NFC",
            team_division="NFC West",
        )

    response = api_client.get("/api/teams/SEA")
    assert response.status_code == 200
    body = response.json()
    assert body["team_abbr"] == "SEA"
    assert body["team_name"] == "Seattle Seahawks"
    assert body["team_division"] == "NFC West"
    assert "ingested_at" not in body
