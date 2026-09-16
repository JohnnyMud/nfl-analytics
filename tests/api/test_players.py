"""Player reads require an explicit team filter; missing ids are unknown."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.api.helpers import insert_player, insert_team


def test_list_players_requires_team_abbr(api_client: TestClient) -> None:
    response = api_client.get("/api/players")
    assert response.status_code == 422


def test_list_players_empty_team_is_empty_list(
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

    response = api_client.get("/api/players", params={"team_abbr": "SEA"})
    assert response.status_code == 200
    assert response.json() == []


def test_list_players_filters_to_requested_team(
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
            team_abbr="SF",
            team_name="San Francisco 49ers",
            team_nick="49ers",
            team_conf="NFC",
            team_division="NFC West",
        )
        insert_player(
            session,
            gsis_id="00-0033873",
            display_name="Russell Wilson",
            first_name="Russell",
            last_name="Wilson",
            latest_team="SF",
            position="QB",
        )
        insert_player(
            session,
            gsis_id="00-0029263",
            display_name="DK Metcalf",
            first_name="DK",
            last_name="Metcalf",
            latest_team="SEA",
            position="WR",
        )
        insert_player(
            session,
            gsis_id="00-0033288",
            display_name="Tyler Lockett",
            first_name="Tyler",
            last_name="Lockett",
            latest_team="SEA",
            position="WR",
        )

    response = api_client.get("/api/players", params={"team_abbr": "SEA"})
    assert response.status_code == 200
    names = [row["display_name"] for row in response.json()]
    assert names == ["Tyler Lockett", "DK Metcalf"]


def test_get_player_unknown_is_404(api_client: TestClient) -> None:
    response = api_client.get("/api/players/00-0000000")
    assert response.status_code == 404
    assert response.json() == {"detail": "player not found"}


def test_get_player_by_gsis_id(
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
        insert_player(
            session,
            gsis_id="00-0029263",
            display_name="DK Metcalf",
            latest_team="SEA",
            position="WR",
        )

    response = api_client.get("/api/players/00-0029263")
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "DK Metcalf"
    assert body["latest_team"] == "SEA"
    assert "ingested_at" not in body
